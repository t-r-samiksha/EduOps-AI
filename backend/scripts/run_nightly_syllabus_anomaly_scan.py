"""Nightly (or on-demand) scan: compares syllabus actual-vs-planned progress and runs
the anomaly detectors, writing results into AnomalyFlag.

SCHEDULING - same finding as every prior session, trusted rather than re-verified
------------------------------------------------------------------------------------
No Celery, Dramatiq, Huey, APScheduler, or other job-scheduling infrastructure exists
anywhere in this repo (confirmed independently by Early-Warning, OCR, and Command
Center sessions - not re-checked here per the task's own instruction to trust that
finding). Same dependency-free-script pattern as scripts/run_nightly_risk_scoring.py:
`run_scan()` is a pure function of (Session, school_id, academic_year) with no
argparse/print/process-exit concerns baked in; `main()` is a thin CLI wrapper for
manual/cron invocation: `python -m scripts.run_nightly_syllabus_anomaly_scan
--school-id 41 --academic-year 2026-27`.

WHY SYLLABUS DRIFT AND ANOMALY DETECTION SHARE ONE SCRIPT (AND ONE TABLE)
------------------------------------------------------------------------------
Playbook 11.3 ("scheduled task to compare actual progress to pacing plan, alert on
significant drift") and 11.4 (anomaly detection) are described as separate line
items, but they're the same *kind* of operation - compute something from current
data, compare to a threshold, persist a flag if it crosses. One script, one
AnomalyFlag table - see that model's docstring for the same reasoning.

WHICH CATEGORIES THIS SCRIPT ACTUALLY RUNS
---------------------------------------------
- syllabus_drift, attendance_drop, document_backlog, teacher_overload: all real,
  built from tables this codebase owns (SyllabusPlan/SyllabusCheckpoint,
  AttendanceRecord, Document, TimetableSlot).
- submission_rate: NEVER called here. Person B's submissions table doesn't exist -
  see services/anomaly_detector.py's module docstring. There is no real
  SubmissionRateSignal data anywhere in this codebase to build. Silently skipping it
  would look identical to "ran and found nothing" - this script logs explicitly, on
  every run, that it was skipped and why.

LOW-SIGNAL RUNS DON'T AUTO-RESOLVE OLD FLAGS - same philosophy as
run_nightly_risk_scoring.py
------------------------------------------------------------------------------------
If an entity no longer trips a detector (attendance recovered, syllabus caught up),
this script does NOT close its existing open AnomalyFlag automatically. Whether "no
longer detected" means "actually resolved" or "detector missed it this run" is a
judgment call left to a human via PUT /admin/anomalies/{id}/resolve - exactly the
same reasoning the early-warning nightly job already documents for RiskFlag.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.attendance import AttendanceRecord
from app.models.class_ import SchoolClass
from app.models.document import Document
from app.models.syllabus import AnomalyFlag, SyllabusCheckpoint, SyllabusPlan
from app.models.timetable import TimetableSlot
from app.models.user import User
from app.services.anomaly_detector import (
    ClassAttendanceWindow,
    DetectedAnomaly,
    DocumentBacklogItem,
    TeacherLoadObservation,
    detect_attendance_drops,
    detect_document_backlogs,
    detect_teacher_overload,
)
from app.services.syllabus_pace import SyllabusPlanInput, compute_pace

RECENT_ATTENDANCE_WINDOW_DAYS = 7
BASELINE_ATTENDANCE_WINDOW_DAYS = 30
SYLLABUS_DRIFT_URGENT_THRESHOLD = -0.30
"""A plain drift-magnitude escalation on top of syllabus_pace.py's behind/on_pace/
ahead classification - twice BEHIND_THRESHOLD, a documented round number."""


def _detect_syllabus_drift(session: Session, school_id: int, academic_year: str, today: date) -> list[DetectedAnomaly]:
    plans = (
        session.query(SyllabusPlan)
        .join(SchoolClass, SyllabusPlan.class_id == SchoolClass.id)
        .filter(SchoolClass.school_id == school_id, SyllabusPlan.academic_year == academic_year)
        .all()
    )
    anomalies = []
    for plan in plans:
        checkpoints_logged = session.query(SyllabusCheckpoint).filter(SyllabusCheckpoint.plan_id == plan.id).count()
        result = compute_pace(
            SyllabusPlanInput(
                plan_id=plan.id,
                class_id=plan.class_id,
                subject_id=plan.subject_id,
                total_units=plan.total_units,
                term_start_date=plan.term_start_date,
                term_end_date=plan.term_end_date,
                checkpoints_logged=checkpoints_logged,
            ),
            today,
        )
        if result.status != "behind":
            continue
        anomalies.append(
            DetectedAnomaly(
                type="syllabus_drift",
                entity_type="syllabus_plans",
                entity_id=plan.id,
                severity="urgent" if result.drift <= SYLLABUS_DRIFT_URGENT_THRESHOLD else "normal",
                message=f"Syllabus plan {plan.id} (class {plan.class_id}, subject {plan.subject_id}) is {abs(result.drift):.0%} behind pace",
                detail={"expected_fraction": result.expected_fraction, "actual_fraction": result.actual_fraction, "drift": result.drift},
            )
        )
    return anomalies


def _detect_attendance_drops_for_school(session: Session, school_id: int, academic_year: str, today: date) -> list[DetectedAnomaly]:
    classes = (
        session.query(SchoolClass)
        .filter(SchoolClass.school_id == school_id, SchoolClass.academic_year == academic_year)
        .all()
    )
    recent_start = today - timedelta(days=RECENT_ATTENDANCE_WINDOW_DAYS)
    baseline_start = today - timedelta(days=BASELINE_ATTENDANCE_WINDOW_DAYS)

    windows = []
    for c in classes:
        baseline_rows = (
            session.query(AttendanceRecord)
            .filter(AttendanceRecord.class_id == c.id, AttendanceRecord.date >= baseline_start, AttendanceRecord.date < recent_start)
            .all()
        )
        recent_rows = (
            session.query(AttendanceRecord)
            .filter(AttendanceRecord.class_id == c.id, AttendanceRecord.date >= recent_start, AttendanceRecord.date <= today)
            .all()
        )
        if not baseline_rows or not recent_rows:
            continue  # can't compute a meaningful drop without both windows populated

        baseline_rate = sum(1 for r in baseline_rows if r.status == "present") / len(baseline_rows)
        recent_present = sum(1 for r in recent_rows if r.status == "present")
        windows.append(
            ClassAttendanceWindow(
                class_id=c.id, recent_present_count=recent_present, recent_total_count=len(recent_rows), baseline_rate=baseline_rate
            )
        )

    return detect_attendance_drops(windows)


def _detect_document_backlogs_for_school(session: Session, school_id: int, now: datetime) -> list[DetectedAnomaly]:
    docs = (
        session.query(Document)
        .join(User, Document.uploaded_by == User.id)
        .filter(User.school_id == school_id, Document.status.in_(("queued", "processing")))
        .all()
    )
    items = [
        DocumentBacklogItem(document_id=d.id, status=d.status, hours_since_upload=(now - d.uploaded_at).total_seconds() / 3600)
        for d in docs
    ]
    return detect_document_backlogs(items)


def _detect_teacher_overload_for_school(session: Session, school_id: int, academic_year: str) -> list[DetectedAnomaly]:
    rows = (
        session.query(TimetableSlot.teacher_id, func.count(TimetableSlot.id))
        .join(SchoolClass, TimetableSlot.class_id == SchoolClass.id)
        .filter(SchoolClass.school_id == school_id, TimetableSlot.academic_year == academic_year, TimetableSlot.is_active.is_(True))
        .group_by(TimetableSlot.teacher_id)
        .all()
    )
    observations = [TeacherLoadObservation(teacher_id=teacher_id, periods_per_week=count) for teacher_id, count in rows]
    return detect_teacher_overload(observations)


def _upsert_flag(session: Session, anomaly: DetectedAnomaly) -> bool:
    """True if a new AnomalyFlag was created, False if an existing open one for the
    same (type, entity_type, entity_id) was refreshed instead - mirrors
    run_nightly_risk_scoring.py's created/updated bookkeeping exactly, so re-running
    this script doesn't produce duplicate flags for the same unresolved situation."""
    existing_open = (
        session.query(AnomalyFlag)
        .filter(
            AnomalyFlag.type == anomaly.type,
            AnomalyFlag.entity_type == anomaly.entity_type,
            AnomalyFlag.entity_id == anomaly.entity_id,
            AnomalyFlag.status == "open",
        )
        .one_or_none()
    )
    detail = {**anomaly.detail, "message": anomaly.message}
    if existing_open is not None:
        existing_open.severity = anomaly.severity
        existing_open.detail = detail
        return False

    session.add(
        AnomalyFlag(
            type=anomaly.type, entity_type=anomaly.entity_type, entity_id=anomaly.entity_id,
            severity=anomaly.severity, detail=detail, status="open",
        )
    )
    return True


def run_scan(session: Session, school_id: int, academic_year: str) -> dict:
    today = date.today()
    now = datetime.now(timezone.utc)

    anomalies: list[DetectedAnomaly] = []
    anomalies += _detect_syllabus_drift(session, school_id, academic_year, today)
    anomalies += _detect_attendance_drops_for_school(session, school_id, academic_year, today)
    anomalies += _detect_document_backlogs_for_school(session, school_id, now)
    anomalies += _detect_teacher_overload_for_school(session, school_id, academic_year)
    # submission_rate deliberately not called - see this module's docstring.

    created = updated = 0
    for anomaly in anomalies:
        if _upsert_flag(session, anomaly):
            created += 1
        else:
            updated += 1

    session.commit()
    return {"anomalies_found": len(anomalies), "flags_created": created, "flags_updated": updated}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--school-id", type=int, required=True)
    parser.add_argument("--academic-year", required=True)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        summary = run_scan(session, args.school_id, args.academic_year)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(f"Scanned school_id={args.school_id}, academic_year={args.academic_year!r}")
    print(f"  anomalies found: {summary['anomalies_found']}")
    print(f"  flags created:   {summary['flags_created']}")
    print(f"  flags updated:   {summary['flags_updated']}")
    print("  submission_rate: SKIPPED - no Person B submissions table exists yet")


if __name__ == "__main__":
    main()
