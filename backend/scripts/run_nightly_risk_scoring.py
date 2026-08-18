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
builds a real AttendanceSignal from AttendanceRecord and a RemarkSignal from the
`remarks` table, falling back to RemarkStub only for students with no real remark yet
(see _build_remark_signal - real teacher remarks used to be ignored entirely), scores them via
services/risk_scorer.py (including a real GradeSignal from Person B gradebook_entries),
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
from app.models.parent_student import ParentStudent
from app.models.remark import Remark
from app.models.risk import RemarkStub, RiskFlag
from app.models.user import User
from app.services.attendance_stats import attendance_snapshot
from app.services.notify import dispatch_bulk
from app.services.gradebook_service import get_student_gradebook_summary
from app.services.risk_scorer import AttendanceSignal, GradeSignal, RemarkSignal, score_student

ATTENDANCE_LOOKBACK_DAYS = 30
REMARK_LOOKBACK_COUNT = 5


def _build_attendance_signal(session: Session, student_id: int, since: date) -> AttendanceSignal:
    """M-2: counts come from services/attendance_stats.py so this job, the parent portal
    and student analytics cannot drift apart."""
    snap = attendance_snapshot(session, student_id, start=since)
    return AttendanceSignal(
        student_id=student_id,
        present_count=snap.present_count,
        absent_count=snap.absent_count,
        late_count=snap.late_count,
        total_records=snap.total_records,
    )


def _build_grade_signal(session: Session, student_id: int, term: str = "Term 1") -> GradeSignal | None:
    """The student's weighted term average from `gradebook_entries`, or None.

    Returns None when the student has no graded assessments, which is not the same as a
    zero: score_student() then EXCLUDES the grade component and renormalises the
    remaining weights, so a school that doesn't use the gradebook scores exactly as it
    did before grades were wired in. Passing 0.0 here would flag every such student.

    `trend` is left None deliberately - gradebook_entries carries no ordering that
    distinguishes "improving" from "declining" without assuming assessment_type maps to
    time, which it does not.
    """
    summary = get_student_gradebook_summary(session, student_id, term)
    average = summary.get("term_average")
    if average is None:
        return None
    return GradeSignal(student_id=student_id, average_score_pct=float(average))


def _build_remark_signal(session: Session, student_id: int) -> RemarkSignal | None:
    """Recent remark TEXT for this student, real remarks preferred over seeded stubs.

    REAL REMARKS NOW COUNT. This read `remark_stubs` and nothing else, which was correct
    when Person B had no remarks table - but `remarks` exists now and the Bulk Remarks
    page writes to it, so every remark a teacher actually typed was invisible to the
    scorer. The two features looked related in the UI and were completely disconnected
    underneath: a teacher could log "disengaged, missed three assignments" for a whole
    class and no risk score would move.

    Real rows WIN rather than merge. Mixing them would let the synthetic demo text dilute
    (or invent) a signal about a student a teacher has actually written about, and the
    stubs are seeded per-student, so a union would almost always be part-fiction. The
    fallback is kept because the Riverside demo fixtures rely on it - a student with no
    real remarks yet still scores off the stub, which is what makes the seeded
    healthy-vs-flagged contrast work (see CLAUDE.md on SEED_ANCHOR_DATE).
    """
    real = (
        session.query(Remark)
        .filter(Remark.student_id == student_id)
        .order_by(Remark.created_at.desc())
        .limit(REMARK_LOOKBACK_COUNT)
        .all()
    )
    if real:
        return RemarkSignal(student_id=student_id, remark_texts=[r.content for r in real])

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


def _notify_new_flag(session: Session, flag: RiskFlag, student_name: str | None) -> int:
    """Tell the homeroom teacher and the linked parents that a flag was raised.

    This job created flags and told NOBODY. Manual POST /risk/flag dispatched; the nightly
    job - which is the real flag source, and now the one that sees grades - did not, so
    the tail of the learning chain ended in a database row nobody was looking at.

    ON CREATION ONLY. run_nightly_scoring refreshes an already-open flag's score and
    reasons every night; dispatching there would re-notify the same family nightly for as
    long as the situation persists, which is how a useful alert becomes ignored noise. The
    same reasoning as report-card publication (see report_card_service).

    Audience matches POST /risk/flag's: parents via ParentStudent, plus the homeroom
    teacher resolved from the student's primary enrollment.
    """
    enrollment = (
        session.query(Enrollment)
        .filter(Enrollment.student_id == flag.student_id, Enrollment.is_primary.is_(True))
        .one_or_none()
    )
    school_class = (
        session.query(SchoolClass).filter(SchoolClass.id == enrollment.class_id).one_or_none()
        if enrollment is not None
        else None
    )
    recipients = [
        row.parent_id
        for row in session.query(ParentStudent.parent_id).filter(
            ParentStudent.student_id == flag.student_id
        )
    ]
    if school_class is not None and school_class.class_teacher_id is not None:
        recipients.append(school_class.class_teacher_id)
    if not recipients:
        return 0

    dispatch_bulk(
        session,
        user_ids=recipients,
        source_type="early_warning",
        title=f"{student_name or 'A student'} flagged as {flag.risk_level} risk",
        body="; ".join(flag.reasons),
        priority="urgent" if flag.risk_level == "high" else "important",
        source_id=flag.id,
    )
    return len(recipients)


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
    created = updated = low_risk_skipped = notified = 0

    for student_id in student_ids:
        attendance = _build_attendance_signal(session, student_id, since)
        grades = _build_grade_signal(session, student_id)
        remarks = _build_remark_signal(session, student_id)
        result = score_student(attendance, grades=grades, remarks=remarks)

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
            flag = RiskFlag(
                student_id=student_id, risk_level=result.risk_level, score=result.score,
                reasons=result.reasons, status="open",
            )
            session.add(flag)
            session.flush()  # need flag.id for the notification's source_id
            student = session.query(User).filter(User.id == student_id).one_or_none()
            notified += _notify_new_flag(session, flag, student.full_name if student else None)
            created += 1

    session.commit()
    return {
        "students_scored": len(student_ids),
        "flags_created": created,
        "flags_updated": updated,
        "low_risk_skipped": low_risk_skipped,
        "people_notified": notified,
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
    print(f"  people notified:        {summary['people_notified']}")


if __name__ == "__main__":
    main()
