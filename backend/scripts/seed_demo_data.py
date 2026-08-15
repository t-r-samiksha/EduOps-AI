"""Seed realistic demo data for manual/Postman testing of the Timetable + Attendance
endpoints, so nobody has to hand-write SQL to populate an empty dev DB.

Run from `backend/` with the venv active:

    python -m scripts.seed_demo_data
    python -m scripts.seed_demo_data --force   # skip the safety prompt

IDEMPOTENCY - "check-then-insert by natural key", not fixed UUIDs
------------------------------------------------------------------
This codebase's primary keys are all auto-increment integers (`id: Mapped[int]`) -
only `users.supabase_id` is a UUID, and that column exists to link to a *real*
Supabase Auth identity (see `app/services/auth.py::_get_or_create_user`), not as a
seed-friendly natural key. Hardcoding fixed UUIDs doesn't fit this schema. Instead,
every entity below is looked up by a natural key (school/class/room/subject name,
user email, or the FK tuple an existing UniqueConstraint already enforces - e.g.
`(teacher_id, subject_id)` for TeacherSubject) via `get_or_create()`: if a row with
that key exists, it's reused as-is (never updated - a rerun never clobbers manual
edits made during testing); if not, it's inserted. Re-running this script is
therefore always safe and creates zero duplicate rows.

Seeded users are direct DB inserts, NOT linked to real Supabase Auth accounts (their
`supabase_id` is a deterministic uuid5 of their email, only to satisfy the NOT NULL
UNIQUE column) - they can't log in themselves. That's intentional: this script's
output is meant to be pasted as request-body/query IDs when calling the API as an
*already-authenticated* admin/teacher (see `gettoken.py` for getting that token),
not to be logged into directly.

WHAT THIS DOES NOT SEED
------------------------
timetable_slots and face_embeddings are deliberately left empty - they should come
from actually calling POST /timetable/generate and POST /attendance/enroll against
the base data this script creates, which is the point of testing those endpoints for
real. attendance_records is *mostly* left empty for the same reason (call POST
/attendance/mark for real), with one deliberate exception - see the Task Group 5
extension below.

EXTENSION (Task Group 4 - Predictive Staffing): synthetic leave history
--------------------------------------------------------------------------
The staffing forecast model (services/staffing_forecast.py) needs historical
approved-leave data to find a day-of-week pattern in - a fresh demo DB has none, so
this script now seeds HISTORY_WEEKS of synthetic `LeaveRequest` rows (status=
"approved", dated in the past relative to whenever the script runs, via date.today()
so it stays meaningful on any rerun date). The pattern is hand-picked, not random,
so idempotent reruns always produce the exact same rows: teacher 1 (who already has
a seeded Friday TeacherUnavailability block above) also gets an elevated historical
Friday absence rate, giving the forecaster a real, thematically-consistent signal to
find; the other teachers get a low, scattered baseline. Natural key for idempotency
is (teacher_id, start_date, end_date) - see HISTORICAL_LEAVE_PATTERN below.
`decided_by` is left null (nullable) rather than inventing a seeded admin user for it.

EXTENSION (Task Group 5 - Early-Warning System): synthetic attendance history + remarks
--------------------------------------------------------------------------------------------
The risk scorer (services/risk_scorer.py) needs a real attendance trend to score
against, and something to run sentiment analysis on. Attendance is genuinely this
project's own data, so this script now seeds ATTENDANCE_HISTORY_DAYS of synthetic
`AttendanceRecord` rows (source="manual", so they read as legitimate manually-marked
records, not fabricated CV output) for two students: one with a deliberately poor
attendance pattern (SYNTHETIC_ATTENDANCE_PROFILES == "at_risk") and one with a good
one ("healthy"), so both a real "flag this student" and a real "don't flag this
student" case are demonstrable end-to-end. `timetable_slot_id` is left null - these
are day-level records, not tied to any specific generated period, so they stay valid
regardless of whether/when POST /timetable/generate has been run. Idempotency is by
(student_id, date, source) checked in application code (the DB's own unique
constraint on attendance_records includes timetable_slot_id, which is NULL here and
therefore never DB-enforces uniqueness across reruns - see attendance.py's model).

Also seeds a handful of `RemarkStub` rows (see app/models/risk.py - a clearly-marked
PLACEHOLDER for Person B's not-yet-built remarks system) for the same two students,
authored by their homeroom teacher, so remark-sentiment analysis has real text to run
against instead of only unit-test strings.

NOTE: this means `_check_safety`'s "has_generated_data" check on attendance_records
will now always be true after the first run of this script (a handful of rows will
always exist), even though most of them are this script's own synthetic data, not
externally-generated real usage. Left as-is rather than special-cased - a slightly
more conservative safety prompt is a fine tradeoff for not adding complexity here.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import date, timedelta
from urllib.parse import urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models.attendance import AttendanceRecord
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.risk import RemarkStub
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest
from app.models.subject import Subject
from app.models.timetable import (
    ClassSubjectRequirement,
    Room,
    SubjectRoomRequirement,
    TeacherProfile,
    TeacherSubject,
    TeacherUnavailability,
)
from app.models.user import User

SCHOOL_NAME = "EduOps Demo School"
ACADEMIC_YEAR = "2026-27"
DEMO_EMAIL_DOMAIN = "eduopsai.test"

SUBJECT_NAMES = ["Math", "Science", "English"]

# subject -> list of teacher indices (1-based) qualified to teach it. Every subject
# gets >=3 qualified teachers so the solver has real routing flexibility, not just a
# single legal assignment - and teacher 1's Friday unavailability (below) actually
# forces the solver to route around someone instead of being trivially infeasible.
TEACHER_COUNT = 6
TEACHER_SUBJECTS = {
    1: ["Math", "Science"],
    2: ["Math", "English"],
    3: ["Science", "English"],
    4: ["Math"],
    5: ["Science"],
    6: ["English"],
}
DEFAULT_MAX_PERIODS_PER_WEEK = 24
"""TeacherProfile default - a realistic middle-school weekly load, comfortably
under a 5-day x 6-period=30-slot ceiling so the solver has real room to route
around it rather than every teacher being maxed out by construction."""

CLASS_NAMES = ["Class 8A", "Class 8B"]
CLASS_TEACHER_INDEX = {"Class 8A": 1, "Class 8B": 2}
STUDENTS_PER_CLASS = 12

ROOMS = [
    {"name": "Room 101", "capacity": 40, "room_type": "classroom"},
    {"name": "Lab 1", "capacity": 30, "room_type": "lab"},
]
# Beyond the letter of the ask, but squarely in its spirit: without this, the solver
# never actually exercises its room-type constraint (only teacher/room/class
# double-booking would ever get tested with "2 rooms" of the same generic type).
SCIENCE_ROOM_TYPE = "lab"

PERIODS_PER_WEEK = {"Math": 5, "Science": 4, "English": 4}

# Teacher 1 unavailable all of Friday - forces the solver to route Math/Science
# periods that would otherwise land on them through teachers 2/4/5 instead.
UNAVAILABLE_TEACHER_INDEX = 1
UNAVAILABLE_DAY = 4  # Friday (0 = Monday)
UNAVAILABLE_PERIODS = range(6)

# Students (by 1-based index within their class) who get a linked parent, for
# parent-portal testing. 3 total, spread across both classes.
PARENT_LINKED_STUDENTS = [("Class 8A", 1), ("Class 8A", 2), ("Class 8B", 1)]

# EXTENSION (frontend session - real multi-child parent dashboard testing):
# test.parent@eduopsai.test is a genuine Supabase Auth account (see gettoken.py) an
# engineer can actually log in as - unlike demo.parentN above, which are direct DB
# inserts with a synthetic deterministic supabase_id and can never log in for real
# (see the module docstring). It had zero parent_student links, which meant the
# real multi-child selector on the parent dashboard could only ever be verified
# against a mocked API response - not good enough. Linked here to two real children:
# - ("Class 8A", 1): the SAME student as demo.parent1 above (real multi-guardian
#   support - ParentStudent explicitly allows a student to have >1 linked parent,
#   see its docstring) AND the "at_risk" synthetic-attendance student below, so
#   this child's stat tiles show real non-zero attendance/risk numbers, not just
#   empty states.
# - ("Class 8B", 2): a second, distinct child in the other class, genuinely unlinked
#   to any other parent, purely to exercise the multi-child selector for real.
REAL_TEST_PARENT_EMAIL = f"test.parent@{DEMO_EMAIL_DOMAIN}"
REAL_TEST_PARENT_LINKED_STUDENTS = [("Class 8A", 1), ("Class 8B", 2)]

# Synthetic historical leave data for the staffing forecast model - see the module
# docstring's "EXTENSION" section. (teacher_index, weeks_back, weekday) tuples;
# weekday is 0=Monday matching the rest of this codebase's convention. Each becomes a
# single-day approved LeaveRequest at weeks_back weeks before "today" (computed at
# run time, not hardcoded, so the data is always in the past on any rerun date).
HISTORY_WEEKS = 8
HISTORICAL_LEAVE_PATTERN = [
    # Teacher 1 already has a standing Friday TeacherUnavailability block (above) -
    # give them a matching elevated *historical* Friday absence rate too, so the
    # forecast model has a real, thematically-consistent day-of-week signal to find.
    (1, 1, 4),
    (1, 3, 4),
    (1, 5, 4),
    (1, 7, 4),
    # Low, scattered baseline across the other teachers/weekdays.
    (2, 2, 0),
    (3, 4, 2),
    (4, 6, 1),
    (5, 3, 3),
    (6, 5, 4),
    (2, 7, 0),
]

# Synthetic attendance history + remarks for the early-warning risk scorer - see the
# module docstring's Task Group 5 "EXTENSION" section. Keyed the same way as
# PARENT_LINKED_STUDENTS: (class_name, 1-based student index within that class).
ATTENDANCE_HISTORY_DAYS = 20  # 4 school weeks (weekdays only)
SYNTHETIC_ATTENDANCE_PROFILES = {
    ("Class 8A", 1): "at_risk",  # same student as the parent-linked one above -
    # also exercises parent-scoping on GET /risk/flagged with a real flag to find.
    ("Class 8A", 5): "healthy",
}
SYNTHETIC_REMARKS = {
    ("Class 8A", 1): [
        "Seems withdrawn and disengaged in class lately.",
        "Missed handing in the last two homework assignments without explanation.",
        "Struggling to keep up with the rest of the group during activities.",
    ],
    ("Class 8A", 5): [
        "Consistently engaged and participates well in class discussions.",
    ],
}


def _attendance_status_for_profile(profile: str, day_index: int) -> str:
    if profile == "at_risk":
        cycle = day_index % 5
        if cycle in (0, 1, 2):
            return "absent"
        if cycle == 3:
            return "late"
        return "present"
    # "healthy": present all but roughly one day in fifteen.
    return "absent" if day_index % 15 == 0 else "present"


def _past_school_days(count: int) -> list[date]:
    """The `count` most recent weekdays (Mon-Fri) strictly before today, oldest
    first."""
    days: list[date] = []
    d = date.today() - timedelta(days=1)
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


# Row counts beyond this suggest the DB has real, non-seed-script data in it - this
# script's own seed run tops out around 6 + 2*12 + 3 = 33 users, so 60 gives headroom
# for reruns/manual test accounts without false-triggering the safety prompt.
NON_TRIVIAL_USER_COUNT_THRESHOLD = 60


def get_or_create(session: Session, model, defaults: dict | None = None, **natural_key):
    instance = session.query(model).filter_by(**natural_key).one_or_none()
    if instance is not None:
        return instance, False
    params = {**natural_key, **(defaults or {})}
    instance = model(**params)
    session.add(instance)
    session.flush()
    return instance, True


def _deterministic_supabase_id(email: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, email)


def _date_weeks_ago_on_weekday(weeks_back: int, weekday: int) -> date:
    """The `weeks_back`-th most recent past occurrence of `weekday` (0=Monday;
    weeks_back=1 is the most recent one, always strictly before today even if today
    happens to be that weekday)."""
    today = date.today()
    days_since_weekday = (today.weekday() - weekday) % 7
    days_since_weekday = days_since_weekday or 7
    most_recent = today - timedelta(days=days_since_weekday)
    return most_recent - timedelta(weeks=weeks_back - 1)


def _mask_database_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or "?"
    netloc = f"{parts.username or '?'}:****@{host}" + (f":{parts.port}" if parts.port else "")
    return f"{parts.scheme}://{netloc}{parts.path}"


def _check_safety(session: Session, force: bool) -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    host = urlsplit(database_url).hostname or ""
    print(f"Target DB: {_mask_database_url(database_url)}")

    if "supabase.co" not in host and "supabase.com" not in host:
        print(f"  WARNING: host '{host}' doesn't look like a Supabase host - double-check this is the right DB.")

    user_count = session.query(func.count(User.id)).scalar() or 0
    generated_data = {
        table: session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        for table in ("timetable_slots", "attendance_records", "face_embeddings")
    }
    has_generated_data = any(generated_data.values())
    looks_non_trivial = user_count > NON_TRIVIAL_USER_COUNT_THRESHOLD

    if not (has_generated_data or looks_non_trivial):
        return

    print("\nThis database already has non-seed-script data in it:")
    print(f"  users: {user_count}")
    for table, count in generated_data.items():
        if count:
            print(f"  {table}: {count} (real feature-testing data - this script won't touch it, but double-check)")

    if force:
        print("--force given, continuing anyway.\n")
        return

    if not sys.stdin.isatty():
        print("\nNot running in an interactive terminal - re-run with --force to proceed anyway. Aborting.")
        sys.exit(1)

    answer = input("\nType 'yes' to continue seeding this database: ").strip().lower()
    if answer != "yes":
        print("Aborted.")
        sys.exit(1)
    print()


def seed(session: Session, counts: dict[str, int]) -> dict:
    def track(created: bool, key: str):
        counts[key] = counts.get(key, 0) + (1 if created else 0)

    school, created = get_or_create(session, School, name=SCHOOL_NAME)
    track(created, "schools")

    subjects: dict[str, Subject] = {}
    for name in SUBJECT_NAMES:
        subject, created = get_or_create(session, Subject, name=name, school_id=school.id)
        track(created, "subjects")
        subjects[name] = subject

    science_subject = subjects.get("Science")
    if science_subject is not None:
        _srr, created = get_or_create(
            session, SubjectRoomRequirement, subject_id=science_subject.id, defaults={"room_type": SCIENCE_ROOM_TYPE}
        )
        track(created, "subject_room_requirements")

    teachers: dict[int, User] = {}
    teacher_role = session.query(Role).filter(Role.name == "teacher").one()
    for i in range(1, TEACHER_COUNT + 1):
        email = f"demo.teacher{i}@{DEMO_EMAIL_DOMAIN}"
        teacher, created = get_or_create(
            session,
            User,
            email=email,
            defaults={
                "supabase_id": _deterministic_supabase_id(email),
                "full_name": f"Demo Teacher {i}",
                "role_id": teacher_role.id,
                "school_id": school.id,
            },
        )
        track(created, "teachers")
        teachers[i] = teacher

        _profile, created = get_or_create(
            session,
            TeacherProfile,
            teacher_id=teacher.id,
            defaults={"max_periods_per_week": DEFAULT_MAX_PERIODS_PER_WEEK},
        )
        track(created, "teacher_profiles")

        for subject_name in TEACHER_SUBJECTS[i]:
            _ts, created = get_or_create(
                session, TeacherSubject, teacher_id=teacher.id, subject_id=subjects[subject_name].id
            )
            track(created, "teacher_subjects")

    for period in UNAVAILABLE_PERIODS:
        _tu, created = get_or_create(
            session,
            TeacherUnavailability,
            teacher_id=teachers[UNAVAILABLE_TEACHER_INDEX].id,
            day_of_week=UNAVAILABLE_DAY,
            period_number=period,
            academic_year=ACADEMIC_YEAR,
        )
        track(created, "teacher_unavailabilities")

    rooms: list[Room] = []
    for room_def in ROOMS:
        room, created = get_or_create(
            session,
            Room,
            name=room_def["name"],
            school_id=school.id,
            defaults={"capacity": room_def["capacity"], "room_type": room_def["room_type"]},
        )
        track(created, "rooms")
        rooms.append(room)

    student_role = session.query(Role).filter(Role.name == "student").one()
    parent_role = session.query(Role).filter(Role.name == "parent").one()

    classes: dict[str, SchoolClass] = {}
    students_by_class: dict[str, list[User]] = {}
    parent_links: list[tuple[User, User]] = []

    for class_name in CLASS_NAMES:
        class_teacher = teachers[CLASS_TEACHER_INDEX[class_name]]
        school_class, created = get_or_create(
            session,
            SchoolClass,
            name=class_name,
            academic_year=ACADEMIC_YEAR,
            school_id=school.id,
            defaults={"class_teacher_id": class_teacher.id},
        )
        track(created, "classes")
        classes[class_name] = school_class

        for subject_name, periods in PERIODS_PER_WEEK.items():
            _csr, created = get_or_create(
                session,
                ClassSubjectRequirement,
                class_id=school_class.id,
                subject_id=subjects[subject_name].id,
                academic_year=ACADEMIC_YEAR,
                defaults={"periods_per_week": periods},
            )
            track(created, "class_subject_requirements")

        class_slug = class_name.replace("Class ", "").replace(" ", "").lower()
        students = []
        for i in range(1, STUDENTS_PER_CLASS + 1):
            email = f"demo.student.{class_slug}.{i:02d}@{DEMO_EMAIL_DOMAIN}"
            student, created = get_or_create(
                session,
                User,
                email=email,
                defaults={
                    "supabase_id": _deterministic_supabase_id(email),
                    "full_name": f"Demo Student {class_name} #{i:02d}",
                    "role_id": student_role.id,
                    "school_id": school.id,
                },
            )
            track(created, "students")
            students.append(student)

            _enroll, created = get_or_create(
                session,
                Enrollment,
                student_id=student.id,
                class_id=school_class.id,
                subject_id=None,
                defaults={"is_primary": True},
            )
            track(created, "enrollments")

            elective_subject = SUBJECT_NAMES[(i - 1) % len(SUBJECT_NAMES)]
            _enroll2, created = get_or_create(
                session,
                Enrollment,
                student_id=student.id,
                class_id=school_class.id,
                subject_id=subjects[elective_subject].id,
                defaults={"is_primary": False},
            )
            track(created, "enrollments")

        students_by_class[class_name] = students

    for parent_index, (class_name, student_index) in enumerate(PARENT_LINKED_STUDENTS, start=1):
        student = students_by_class[class_name][student_index - 1]
        email = f"demo.parent{parent_index}@{DEMO_EMAIL_DOMAIN}"
        parent, created = get_or_create(
            session,
            User,
            email=email,
            defaults={
                "supabase_id": _deterministic_supabase_id(email),
                "full_name": f"Demo Parent {parent_index}",
                "role_id": parent_role.id,
                "school_id": school.id,
            },
        )
        track(created, "parents")

        _link, created = get_or_create(session, ParentStudent, parent_id=parent.id, student_id=student.id)
        track(created, "parent_student_links")
        parent_links.append((parent, student))

    # Real multi-child parent link - see REAL_TEST_PARENT_LINKED_STUDENTS above.
    # Deliberately NOT get_or_create'd on User: this must be a pre-existing real
    # Supabase-authenticated row (created by _get_or_create_user on first real
    # login, not by this script) - creating it here with a synthetic supabase_id
    # would race the real one and later break that account's actual login with a
    # UNIQUE constraint violation on users.email. If it hasn't logged in yet on
    # this DB, we skip the link this run rather than fake the account into being.
    real_parent = session.query(User).filter(User.email == REAL_TEST_PARENT_EMAIL).one_or_none()
    real_parent_children: list[User] = []
    if real_parent is not None:
        for class_name, student_index in REAL_TEST_PARENT_LINKED_STUDENTS:
            student = students_by_class[class_name][student_index - 1]
            _link, created = get_or_create(session, ParentStudent, parent_id=real_parent.id, student_id=student.id)
            track(created, "parent_student_links")
            real_parent_children.append(student)

    for teacher_index, weeks_back, weekday in HISTORICAL_LEAVE_PATTERN:
        leave_date = _date_weeks_ago_on_weekday(weeks_back, weekday)
        _leave, created = get_or_create(
            session,
            LeaveRequest,
            teacher_id=teachers[teacher_index].id,
            start_date=leave_date,
            end_date=leave_date,
            defaults={"reason": "Synthetic historical leave (seed data)", "status": "approved"},
        )
        track(created, "leave_requests")

    school_days = _past_school_days(ATTENDANCE_HISTORY_DAYS)
    for (class_name, student_index), profile in SYNTHETIC_ATTENDANCE_PROFILES.items():
        student = students_by_class[class_name][student_index - 1]
        school_class = classes[class_name]
        for day_index, record_date in enumerate(school_days):
            record_status = _attendance_status_for_profile(profile, day_index)
            _record, created = get_or_create(
                session,
                AttendanceRecord,
                student_id=student.id,
                date=record_date,
                source="manual",
                defaults={"class_id": school_class.id, "status": record_status},
            )
            track(created, "attendance_records")

    for (class_name, student_index), remarks in SYNTHETIC_REMARKS.items():
        student = students_by_class[class_name][student_index - 1]
        remark_teacher = teachers[CLASS_TEACHER_INDEX[class_name]]
        for remark_text in remarks:
            _remark, created = get_or_create(
                session, RemarkStub, student_id=student.id, remark_text=remark_text, defaults={"teacher_id": remark_teacher.id}
            )
            track(created, "remark_stubs")

    return {
        "school": school,
        "subjects": subjects,
        "teachers": teachers,
        "rooms": rooms,
        "classes": classes,
        "students_by_class": students_by_class,
        "parent_links": parent_links,
        "real_parent": real_parent,
        "real_parent_children": real_parent_children,
    }


def _print_summary(session: Session, counts: dict[str, int], data: dict) -> None:
    print("\n=== Seed summary (created this run / total now in DB) ===")
    table_totals = {
        "schools": School,
        "subjects": Subject,
        "classes": SchoolClass,
        "rooms": Room,
        "teacher_profiles": TeacherProfile,
        "teacher_subjects": TeacherSubject,
        "teacher_unavailabilities": TeacherUnavailability,
        "class_subject_requirements": ClassSubjectRequirement,
        "enrollments": Enrollment,
        "parent_student_links": ParentStudent,
        "leave_requests": LeaveRequest,
        "attendance_records": AttendanceRecord,
        "remark_stubs": RemarkStub,
    }
    for key, model in table_totals.items():
        total = session.query(func.count()).select_from(model).scalar()
        print(f"  {key:<28} +{counts.get(key, 0):<3} / {total} total")

    total_users = session.query(func.count(User.id)).scalar()
    teacher_total = session.query(func.count(User.id)).filter(User.role_id == session.query(Role.id).filter(Role.name == "teacher").scalar_subquery()).scalar()
    student_total = session.query(func.count(User.id)).filter(User.role_id == session.query(Role.id).filter(Role.name == "student").scalar_subquery()).scalar()
    parent_total = session.query(func.count(User.id)).filter(User.role_id == session.query(Role.id).filter(Role.name == "parent").scalar_subquery()).scalar()
    print(f"  {'teachers':<28} +{counts.get('teachers', 0):<3} / {teacher_total} total")
    print(f"  {'students':<28} +{counts.get('students', 0):<3} / {student_total} total")
    print(f"  {'parents':<28} +{counts.get('parents', 0):<3} / {parent_total} total")
    print(f"  {'users (all roles)':<28} {'':<4} / {total_users} total")

    print("\n=== Ready-to-test IDs ===")
    print(f"  school_id ({SCHOOL_NAME}): {data['school'].id}")
    for class_name, school_class in data["classes"].items():
        print(f"  class_id ({class_name}): {school_class.id}")
    for room in data["rooms"]:
        print(f"  room_id ({room.name}, {room.room_type}): {room.id}")
    for subject_name, subject in data["subjects"].items():
        print(f"  subject_id ({subject_name}): {subject.id}")

    homeroom_teacher = data["teachers"][CLASS_TEACHER_INDEX["Class 8A"]]
    print(f"  teacher user_id (Class 8A homeroom): {homeroom_teacher.id}")
    unavailable_teacher = data["teachers"][UNAVAILABLE_TEACHER_INDEX]
    print(f"  teacher user_id (Friday unavailability set): {unavailable_teacher.id}")

    class_8a_students = data["students_by_class"]["Class 8A"]
    linked_student_ids = {student.id for _parent, student in data["parent_links"]}
    no_parent_student = next(s for s in class_8a_students if s.id not in linked_student_ids)
    parent, linked_student = data["parent_links"][0]
    print(f"  student user_id (Class 8A, no parent linked): {no_parent_student.id}")
    print(f"  student user_id (Class 8A, parent linked): {linked_student.id}")
    print(f"  parent user_id (linked to student {linked_student.id}): {parent.id}")

    at_risk_student = data["students_by_class"]["Class 8A"][0]
    healthy_student = data["students_by_class"]["Class 8A"][4]
    print(f"  student user_id (synthetic AT-RISK attendance + negative remarks): {at_risk_student.id}")
    print(f"  student user_id (synthetic healthy attendance + positive remark): {healthy_student.id}")

    if data["real_parent"] is not None:
        child_ids = ", ".join(str(c.id) for c in data["real_parent_children"])
        print(f"  {REAL_TEST_PARENT_EMAIL} (user_id {data['real_parent'].id}) linked to real children: {child_ids}")
    else:
        print(
            f"  NOTE: {REAL_TEST_PARENT_EMAIL} has no users row yet on this DB (hasn't logged in via "
            "Supabase Auth) - its multi-child link was skipped this run. Log in once (frontend or "
            "`python gettoken.py parent`), then re-run this script to link its 2 demo children."
        )

    print(f"\nacademic_year for /timetable/generate and /timetable/active: {ACADEMIC_YEAR!r}")
    print(
        "Next: POST /timetable/generate with the school_id/academic_year above, then "
        "POST /attendance/enroll a reference photo for a student_id, then POST "
        "/attendance/mark against a generated timetable_slot_id. "
        f"{sum(1 for t, w, d in HISTORICAL_LEAVE_PATTERN if t == UNAVAILABLE_TEACHER_INDEX)} weeks of synthetic "
        f"Friday leave history is seeded for teacher {unavailable_teacher.id} - GET /admin/staffing/forecast "
        "with the school_id above is ready to query. "
        f"{ATTENDANCE_HISTORY_DAYS} days of synthetic attendance history + remark stubs are seeded for students "
        f"{at_risk_student.id} (at-risk) and {healthy_student.id} (healthy) - run "
        "`python -m scripts.run_nightly_risk_scoring --school-id <id> --academic-year "
        f"{ACADEMIC_YEAR!r}` to generate real RiskFlag rows from them."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="Skip the non-trivial-data confirmation prompt")
    args = parser.parse_args()

    session = SessionLocal()
    counts: dict[str, int] = {}
    try:
        _check_safety(session, args.force)
        data = seed(session, counts)
        session.commit()
    except Exception:
        session.rollback()
        raise
    else:
        _print_summary(session, counts, data)
    finally:
        session.close()


if __name__ == "__main__":
    main()
