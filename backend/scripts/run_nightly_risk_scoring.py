"""Nightly (or on-demand) re-scoring job for the early-warning system.

SCHEDULING - now real, wired into APScheduler (was manual-only for several sessions)
--------------------------------------------------------------------------------------
`run_nightly_scoring()` (below) now runs automatically every night at 02:00 UTC
for every active school/academic_year, via `app/scheduler.py`'s
`run_nightly_risk_scoring_job()` - started in `app/main.py`'s FastAPI lifespan,
so it fires for real whenever the backend process is running, no human/cron
required. This function itself is unchanged: still a pure function of
(session, school_id, academic_year) with no argparse/print/process-exit
concerns baked in - `app/scheduler.py` imports and calls it directly, same as
`main()` below does.

The manual CLI invocation below still works exactly as before, for on-demand/
single-school runs: `python -m scripts.run_nightly_risk_scoring --school-id 41
--academic-year 2026-27`. `main()` is only a thin CLI wrapper (argparse + a
session + a printed summary) around the same function the real scheduler uses.

WHAT IT DOES
--------------
For every student enrolled (primary enrollment) in the given school/academic_year,
builds a real AttendanceSignal from AttendanceRecord and a RemarkSignal from
RemarkStub (see that model's docstring - a seeded placeholder), scores them via
services/risk_scorer.py (grades intentionally omitted - no real signal exists yet),
and:
  - low risk: no flag created; an existing OPEN flag for that student is left alone
    (auto-resolving it is a judgment call for a human via PUT /risk/{id}/resolve, not
    something this job does silently - a counselor may be mid-intervention).
  - medium/high risk: creates a new open RiskFlag, or refreshes score/risk_level/
    reasons on an already-open one so re-running doesn't produce duplicate flags for
    the same unresolved situation.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.attendance import AttendanceRecord
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.risk import RemarkStub, RiskFlag
from app.services.risk_scorer import AttendanceSignal, RemarkSignal, score_student

ATTENDANCE_LOOKBACK_DAYS = 30
REMARK_LOOKBACK_COUNT = 5


def _build_attendance_signal(session: Session, student_id: int, since: date) -> AttendanceSignal:
    rows = (
        session.query(AttendanceRecord)
        .filter(AttendanceRecord.student_id == student_id, AttendanceRecord.date >= since)
        .all()
    )
    present = sum(1 for r in rows if r.status == "present")
    absent = sum(1 for r in rows if r.status == "absent")
    late = sum(1 for r in rows if r.status == "late")
    return AttendanceSignal(student_id=student_id, present_count=present, absent_count=absent, late_count=late, total_records=len(rows))


def _build_remark_signal(session: Session, student_id: int) -> RemarkSignal | None:
    rows = (
        session.query(RemarkStub)
        .filter(RemarkStub.student_id == student_id)
        .order_by(RemarkStub.created_at.desc())
        .limit(REMARK_LOOKBACK_COUNT)
        .all()
    )
    if not rows:
        return None
    return RemarkSignal(student_id=student_id, remark_texts=[r.remark_text for r in rows])


def run_nightly_scoring(session: Session, school_id: int, academic_year: str) -> dict:
    student_ids = {
        row.student_id
        for row in session.query(Enrollment.student_id)
        .join(SchoolClass, Enrollment.class_id == SchoolClass.id)
        .filter(
            SchoolClass.school_id == school_id,
            SchoolClass.academic_year == academic_year,
            Enrollment.is_primary.is_(True),
        )
    }

    since = date.today() - timedelta(days=ATTENDANCE_LOOKBACK_DAYS)
    created = updated = low_risk_skipped = 0

    for student_id in student_ids:
        attendance = _build_attendance_signal(session, student_id, since)
        remarks = _build_remark_signal(session, student_id)
        result = score_student(attendance, grades=None, remarks=remarks)

        if result.risk_level == "low":
            low_risk_skipped += 1
            continue

        existing_open = (
            session.query(RiskFlag).filter(RiskFlag.student_id == student_id, RiskFlag.status == "open").one_or_none()
        )
        if existing_open is not None:
            existing_open.score = result.score
            existing_open.risk_level = result.risk_level
            existing_open.reasons = result.reasons
            updated += 1
        else:
            session.add(
                RiskFlag(student_id=student_id, risk_level=result.risk_level, score=result.score, reasons=result.reasons, status="open")
            )
            created += 1

    session.commit()
    return {
        "students_scored": len(student_ids),
        "flags_created": created,
        "flags_updated": updated,
        "low_risk_skipped": low_risk_skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--school-id", type=int, required=True)
    parser.add_argument("--academic-year", required=True)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        summary = run_nightly_scoring(session, args.school_id, args.academic_year)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(f"Scored {summary['students_scored']} students (school_id={args.school_id}, academic_year={args.academic_year!r})")
    print(f"  new flags created:      {summary['flags_created']}")
    print(f"  existing flags updated: {summary['flags_updated']}")
    print(f"  low risk (no flag):     {summary['low_risk_skipped']}")


if __name__ == "__main__":
    main()
