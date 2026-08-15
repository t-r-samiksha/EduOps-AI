"""Wipes ALL application data for a truly clean slate - the counterpart to
`scripts/seed_demo_data.py`, kept around as a real, reusable reset tool rather
than a one-off script.

WHY A FULL WIPE, NOT JUST "undo what seed_demo_data.py inserted"
--------------------------------------------------------------------
Over the life of this project, real feature-testing (real API calls, not just
the seed script) has layered real data on top of what `seed_demo_data.py`
created - real TimetableSlot generations, real RiskFlag/AnomalyFlag/FeeRecord
rows from `app/scheduler.py`'s automated jobs, real FeeSchedule rows created
through the Fees UI in an earlier session, real throwaway verification schools
from various testing sessions, etc. None of it is genuine production data.
Tracing "exactly what seed_demo_data.py itself inserted" and leaving everything
else would leave a demo environment still full of test debris - not a clean
slate. This script instead wipes every content table, keeping only:
  - The 5 fixed `roles` rows (principal/admin/teacher/student/parent) - Phase 0
    system reference data, not seed/demo data. Deleting these would break
    RBAC for every future real signup too.
  - Any `User` row whose email is explicitly passed via `--preserve-email`
    (repeatable) - defaults to none; the caller decides who survives.

REAL vs SEED-SYNTHETIC ACCOUNTS - how this script tells them apart
------------------------------------------------------------------------
`scripts/seed_demo_data.py`'s own docstring documents this: every user IT
creates gets `supabase_id = uuid.uuid5(uuid.NAMESPACE_DNS, email)` - a
deterministic value with no corresponding real Supabase Auth account, so that
user can never actually log in. A REAL, login-capable account (created via
`services/supabase_admin.py`'s `auth.admin.create_user`, or via
`_get_or_create_user` on a real first login) has a `supabase_id` that does NOT
match this formula. This script recomputes the deterministic UUID for every
local user's email and flags any MISMATCH as "real" - printed explicitly in
the dry run, whether or not it's in `--preserve-email`, so nothing is deleted
silently.

DELETION ORDER - a real topological sort of the FK graph, verified by reading
every model's ForeignKey declarations (see PR/commit for the derivation),
children before parents. `roles` never appears - it's never touched.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.admissions import AdmissionApplication
from app.models.alerts import AlertDismissal
from app.models.attendance import AttendanceReconciliation, AttendanceRecord, FaceEmbedding
from app.models.audit import AuditLogEntry
from app.models.class_ import SchoolClass
from app.models.document import Document, ExtractedEntity, OcrResult
from app.models.enrollment import Enrollment
from app.models.exams import Exam, ExamRoomAssignment, InvigilationAssignment, SeatingAssignment
from app.models.fees import FeeRecord, FeeReminder, FeeSchedule
from app.models.parent_student import ParentStudent
from app.models.risk import Intervention, RemarkStub, RiskFlag
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest, StaffingForecast, Substitution
from app.models.subject import Subject
from app.models.syllabus import AnomalyFlag, SyllabusCheckpoint, SyllabusPlan
from app.models.timetable import (
    ClassSubjectRequirement,
    Room,
    SubjectRoomRequirement,
    TeacherProfile,
    TeacherSubject,
    TeacherUnavailability,
    TimetableSlot,
)
from app.models.user import User

# Order matters - a real topological sort of the FK graph (children before
# parents). See this module's docstring for how it was derived. `roles` is
# deliberately absent - it is never deleted.
DELETION_ORDER: list[type] = [
    OcrResult,
    ExtractedEntity,
    TeacherProfile,
    TeacherSubject,
    SubjectRoomRequirement,
    TeacherUnavailability,
    ClassSubjectRequirement,
    Enrollment,
    FaceEmbedding,
    AttendanceReconciliation,
    AuditLogEntry,
    AlertDismissal,
    ParentStudent,
    Intervention,
    RemarkStub,
    Substitution,
    StaffingForecast,
    SyllabusCheckpoint,
    AnomalyFlag,
    AdmissionApplication,
    FeeReminder,
    ExamRoomAssignment,
    SeatingAssignment,
    InvigilationAssignment,
    Document,
    RiskFlag,
    LeaveRequest,
    SyllabusPlan,
    FeeRecord,
    Exam,
    AttendanceRecord,
    TimetableSlot,
    FeeSchedule,
    SchoolClass,
    Room,
    Subject,
    # `User` is handled separately (see `_users_to_delete`) - it's not a plain
    # "delete every row" table, some rows survive.
    # `School` is handled separately too - deleted last, after users, since
    # `users.school_id` references it.
]


def _deterministic_supabase_id(email: str) -> uuid.UUID:
    """MUST exactly match scripts/seed_demo_data.py's own function of the same
    name - this is the whole classification mechanism."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, email)


def _classify_users(session: Session, preserve_emails: set[str]) -> tuple[list[User], list[User], list[User]]:
    """Returns (to_delete, real_and_deleted, real_and_preserved). A user is
    "real" if their stored supabase_id does NOT match the deterministic
    seed-script formula for their email - i.e. a genuine Supabase Auth
    account, whether created by an admin/teacher/parent's real first login or
    by services/supabase_admin.py."""
    all_users = session.query(User).all()
    to_delete: list[User] = []
    real_and_deleted: list[User] = []
    real_and_preserved: list[User] = []

    for user in all_users:
        is_real = user.supabase_id != _deterministic_supabase_id(user.email)
        if user.email in preserve_emails:
            real_and_preserved.append(user)
            continue
        to_delete.append(user)
        if is_real:
            real_and_deleted.append(user)

    return to_delete, real_and_deleted, real_and_preserved


def _print_dry_run(session: Session, preserve_emails: set[str]) -> None:
    print("=== DRY RUN - nothing will be deleted. Re-run with --confirm to execute. ===\n")

    print("--- Per-table counts that WOULD be deleted ---")
    for model in DELETION_ORDER:
        count = session.query(func.count()).select_from(model).scalar()
        if count:
            print(f"  {model.__tablename__:<28} {count}")

    to_delete, real_and_deleted, real_and_preserved = _classify_users(session, preserve_emails)
    schools_total = session.query(func.count(School.id)).scalar()
    print(f"  {'users':<28} {len(to_delete)}")
    print(f"  {'schools':<28} {schools_total}")

    print("\n--- roles table: NEVER touched (5 fixed system rows) ---")

    print("\n--- Real (login-capable) Supabase Auth accounts found ---")
    real_users = [u for u in session.query(User).all() if u.supabase_id != _deterministic_supabase_id(u.email)]
    if not real_users:
        print("  (none found)")
    for u in real_users:
        role_name = session.query(Role.name).filter(Role.id == u.role_id).scalar()
        status = "PRESERVED" if u.email in preserve_emails else "WOULD BE DELETED"
        print(f"  {u.email:<40} role={role_name:<10} user_id={u.id:<8} -> {status}")

    print("\n--- Accounts explicitly preserved (--preserve-email) ---")
    if not real_and_preserved:
        print("  (none specified)")
    for u in real_and_preserved:
        role_name = session.query(Role.name).filter(Role.id == u.role_id).scalar()
        is_real = u.supabase_id != _deterministic_supabase_id(u.email)
        print(f"  {u.email:<40} role={role_name:<10} user_id={u.id:<8} real_account={is_real}")

    admin_survivors = [u for u in real_and_preserved]
    login_capable_survivors = [
        u for u in session.query(User).all()
        if u.email in preserve_emails and u.supabase_id != _deterministic_supabase_id(u.email)
    ]
    print("\n--- Lockout check ---")
    if login_capable_survivors:
        print(f"  OK - {len(login_capable_survivors)} real, login-capable account(s) will survive:")
        for u in login_capable_survivors:
            role_name = session.query(Role.name).filter(Role.id == u.role_id).scalar()
            print(f"    {u.email} (role={role_name})")
    else:
        print(
            "  *** WARNING: zero real, login-capable accounts would survive this wipe. ***\n"
            "  Pass at least one real account via --preserve-email before running --confirm,\n"
            "  or you will not be able to log in to run the onboarding flow afterward."
        )


def _wipe(session: Session, preserve_emails: set[str]) -> None:
    for model in DELETION_ORDER:
        session.query(model).delete(synchronize_session=False)

    to_delete, _real_and_deleted, real_and_preserved = _classify_users(session, preserve_emails)
    delete_ids = [u.id for u in to_delete]
    if delete_ids:
        session.query(User).filter(User.id.in_(delete_ids)).delete(synchronize_session=False)

    # A preserved user might still point at a school we're about to delete
    # (users.school_id is a real FK) - null it out first rather than leaving
    # an orphaned reference or skipping the school's deletion.
    for user in real_and_preserved:
        if user.school_id is not None:
            user.school_id = None
    session.flush()

    session.query(School).delete(synchronize_session=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--preserve-email", action="append", default=[], metavar="EMAIL",
        help="Email of a real user row to keep (repeatable). The Supabase Auth account itself is never "
        "touched by this script either way - only the local `users` row.",
    )
    parser.add_argument("--confirm", action="store_true", help="Actually execute the wipe. Without this, dry-run only.")
    args = parser.parse_args()
    preserve_emails = set(args.preserve_email)

    session = SessionLocal()
    try:
        if not args.confirm:
            _print_dry_run(session, preserve_emails)
            return

        print("Executing real wipe...")
        _wipe(session, preserve_emails)
        session.commit()
        print("Done. All tables wiped except `roles` and the preserved user(s):")
        for email in sorted(preserve_emails):
            print(f"  {email}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
