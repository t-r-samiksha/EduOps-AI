"""Monthly (or on-demand) fee invoicing: generates FeeRecord rows from active
FeeSchedules for a school/academic_year, then marks past-due records overdue and
runs the reminder cadence heuristic against them.

SCHEDULING - now real, wired into APScheduler (was manual-only for several sessions)
--------------------------------------------------------------------------------------
`run_monthly_invoicing()` (below) now runs automatically at 03:00 UTC on the 1st
of every month, for every active school/academic_year, via `app/scheduler.py`'s
`run_monthly_fee_invoicing_job()` - started in `app/main.py`'s FastAPI lifespan.
`run_monthly_invoicing()` itself is unchanged: still a pure function of
(Session, school_id, academic_year); `main()` below remains a thin CLI wrapper
for manual/on-demand invocation:
`python -m scripts.run_monthly_fee_invoicing --school-id 41 --academic-year 2026-27`.

WHAT IT DOES
--------------
1. For every FeeSchedule in the school/academic_year, creates a FeeRecord for every
   primary-enrolled student it applies to (the whole school if class_id is null,
   just that class if set) who doesn't already have one for that schedule -
   idempotent, re-running never creates duplicates (the same UniqueConstraint
   FeeRecord itself enforces is checked first).
2. Any pending/partial record whose due_date has passed is marked overdue.
3. Every overdue record is run through services/fee_reminder_engine.py's cadence
   heuristic; a FeeReminder row is logged (sent_at stays null - no email
   infrastructure exists, see FeeReminder's own docstring) whenever a new tier is
   reached that hasn't already fired for that record.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

AUTO_GENERATE_WINDOW_DAYS = 7
"""How close a schedule's due_date must be before records generate on their own
(schedule creation, nightly job) - further out than this, generation is manual-
only (POST /admin/fees/schedules/{id}/generate) until the window is entered.
Manual paths (this script's CLI, POST /admin/fees/invoicing/run, the per-schedule
endpoint) never apply this - they're an explicit human "do it now", ungated."""

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.fees import FeeRecord, FeeReminder, FeeSchedule
from app.services.fee_reminder_engine import determine_reminder


def _students_for_schedule(session: Session, schedule: FeeSchedule, school_id: int, academic_year: str) -> set[int]:
    query = session.query(Enrollment.student_id).join(SchoolClass, Enrollment.class_id == SchoolClass.id).filter(
        SchoolClass.school_id == school_id, SchoolClass.academic_year == academic_year, Enrollment.is_primary.is_(True)
    )
    if schedule.class_id is not None:
        query = query.filter(Enrollment.class_id == schedule.class_id)
    return {row.student_id for row in query}


def _generate_records_for_one_schedule(session: Session, schedule: FeeSchedule) -> int:
    created = 0
    for student_id in _students_for_schedule(session, schedule, schedule.school_id, schedule.academic_year):
        existing = (
            session.query(FeeRecord)
            .filter(FeeRecord.student_id == student_id, FeeRecord.fee_schedule_id == schedule.id)
            .one_or_none()
        )
        if existing is not None:
            continue
        session.add(
            FeeRecord(
                student_id=student_id, fee_schedule_id=schedule.id, amount_due=schedule.amount,
                amount_paid=0.0, status="pending", due_date=schedule.due_date,
            )
        )
        created += 1
    return created


def generate_fee_records_for_schedule(session: Session, schedule: FeeSchedule) -> int:
    """Generates records for exactly ONE schedule, regardless of due_date - the
    manual per-schedule "Generate records now" action (POST /admin/fees/schedules/
    {id}/generate), always ungated since it's an explicit admin choice to do this
    early rather than wait for the auto-generate window."""
    created = _generate_records_for_one_schedule(session, schedule)
    session.flush()
    return created


def generate_fee_records(session: Session, school_id: int, academic_year: str, due_within_days: int | None = None) -> int:
    """`due_within_days`, when given, skips any schedule whose due_date is further
    out than that - used by the automatic paths (schedule creation, the nightly
    job) so a fee due in 2 months doesn't materialize the moment its schedule is
    created. Manual callers (this script's CLI, POST /admin/fees/invoicing/run)
    leave this None - an explicit "generate everything now" stays ungated."""
    schedules = (
        session.query(FeeSchedule)
        .filter(FeeSchedule.school_id == school_id, FeeSchedule.academic_year == academic_year)
        .all()
    )
    if due_within_days is not None:
        cutoff = date.today() + timedelta(days=due_within_days)
        schedules = [s for s in schedules if s.due_date <= cutoff]

    created = sum(_generate_records_for_one_schedule(session, schedule) for schedule in schedules)

    # Explicit flush, not relying on autoflush: app.database.SessionLocal sets
    # autoflush=False, so without this, mark_overdue_and_send_reminders()'s query
    # (called right after, same session) would silently miss every record just
    # created here - a real bug caught by running this script against the live
    # session, not by the test suite (whose db_session fixture happens to default to
    # autoflush=True, which papered over it).
    session.flush()
    return created


def mark_overdue_and_send_reminders(session: Session, school_id: int, academic_year: str, today: date) -> dict:
    student_ids = {
        row.student_id
        for row in session.query(Enrollment.student_id)
        .join(SchoolClass, Enrollment.class_id == SchoolClass.id)
        .filter(SchoolClass.school_id == school_id, SchoolClass.academic_year == academic_year, Enrollment.is_primary.is_(True))
    }
    if not student_ids:
        return {"overdue_marked": 0, "reminders_sent": 0}

    newly_overdue = (
        session.query(FeeRecord)
        .filter(FeeRecord.student_id.in_(student_ids), FeeRecord.status.in_(("pending", "partial")), FeeRecord.due_date < today)
        .all()
    )
    for record in newly_overdue:
        record.status = "overdue"
    # Same autoflush=False staleness issue as generate_fee_records() above - without
    # this, the "overdue" query below (same session, no autoflush in production)
    # would still see the OLD status for every record just updated on the line
    # above, silently skipping every newly-overdue record's reminder this run.
    session.flush()

    overdue_records = session.query(FeeRecord).filter(FeeRecord.student_id.in_(student_ids), FeeRecord.status == "overdue").all()
    reminders_sent = 0
    for record in overdue_records:
        days_overdue = (today - record.due_date).days
        already_sent = {
            r.cadence_reason for r in session.query(FeeReminder).filter(FeeReminder.fee_record_id == record.id)
        }
        decision = determine_reminder(days_overdue, already_sent)
        if decision.should_send:
            session.add(FeeReminder(fee_record_id=record.id, cadence_reason=decision.cadence_reason, sent_at=None))
            reminders_sent += 1

    return {"overdue_marked": len(newly_overdue), "reminders_sent": reminders_sent}


def run_monthly_invoicing(
    session: Session, school_id: int, academic_year: str, generate_only_due_within_days: int | None = None
) -> dict:
    today = date.today()
    records_created = generate_fee_records(session, school_id, academic_year, due_within_days=generate_only_due_within_days)
    reminder_summary = mark_overdue_and_send_reminders(session, school_id, academic_year, today)
    session.commit()
    return {"records_created": records_created, **reminder_summary}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--school-id", type=int, required=True)
    parser.add_argument("--academic-year", required=True)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        summary = run_monthly_invoicing(session, args.school_id, args.academic_year)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(f"Invoiced school_id={args.school_id}, academic_year={args.academic_year!r}")
    print(f"  fee records created: {summary['records_created']}")
    print(f"  newly marked overdue: {summary['overdue_marked']}")
    print(f"  reminders logged:     {summary['reminders_sent']} (sent_at stays null - no email integration exists yet)")


if __name__ == "__main__":
    main()
