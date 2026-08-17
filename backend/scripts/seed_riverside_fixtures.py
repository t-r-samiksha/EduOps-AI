"""Minimal, idempotent fixtures so the notification center is demonstrable against
the REAL Riverside data - not a second demo dataset.

WHY THIS EXISTS INSTEAD OF scripts/seed_demo_data.py
--------------------------------------------------------
seed_demo_data.py builds its own school ("EduOps Demo School") and its own
@eduopsai.test users from scratch. Running it against this database would create
a THIRD school alongside two schools of hand-made data, and a parallel set of
students nobody can tell apart from the real ones a week later. An audit of this
DB found zero @eduopsai.test users, i.e. seed_demo_data.py has never been run
here and all current data is hand-created - so this script deliberately does not
create any school, class, teacher, student or parent. It only adds the few
missing rows needed for one real, already-existing parent to receive a real
notification.

WHAT WAS ACTUALLY MISSING (audited before writing this)
-----------------------------------------------------------
For school 5707 (Riverside Public School) and guardian.kumar@riverside-school.test's
two linked children:
  enrollments 2, attendance_records 5, timetable_slots 54, risk_flags 1  <- fine
  fee_schedules 0, fee_records 0, remark_stubs 0                         <- empty
Both notification sources we want to demo therefore needed help: `fee_reminder`
had nothing to remind about at all, and `early_warning` only covered one of the
two children. This adds an overdue fee for each child and a risk flag for the
child that lacked one.

IDEMPOTENT, like seed_demo_data.py: every row is get-or-create by natural key, so
re-running changes nothing and never duplicates. It also never updates a row it
finds - if you want different values, delete the row first.

Usage (from /backend, venv active):
    PYTHONPATH=. venv/Scripts/python.exe -m scripts.seed_riverside_fixtures
"""

from __future__ import annotations

import os
import uuid
from datetime import date, time, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.fees import FeeRecord, FeeSchedule
from app.models.parent_student import ParentStudent
from app.models.resource import Resource
from app.models.risk import RiskFlag
from app.models.role import Role
from app.models.subject import Subject
from app.models.timetable import Room, TimetableSlot
from app.models.user import User

PARENT_EMAIL = "guardian.kumar@riverside-school.test"
ACADEMIC_YEAR = "2026-27"
SCHOOL_ID = 5707
"""Riverside Public School. Hardcoded because this script exists to wire up THAT
school's real data - it is not a general-purpose seeder (see the module docstring)."""

# --- Grade 3 - B: the second section ------------------------------------------------
# Added for the Top Doubts cross-section story. Before this, every class in school 5707
# was a single "- A" section (Grade 1 - A, Grade 2 - A, Grade 3 - A), so "the same
# confusion appearing in two sections of one grade" was not expressible at all. The new
# section deliberately shares Grade 3 - A's SUBJECT TEACHERS (see _ensure_grade3b_slots)
# - that shared teacher is the person who sees both sections' confusion as one insight.
GRADE_3B_NAME = "Grade 3 - B"
GRADE_3B_STUDENTS = [
    ("kabir.b.student@riverside-school.test", "Kabir Sharma"),
    ("anaya.b.student@riverside-school.test", "Anaya Iyer"),
    ("rohan.b.student@riverside-school.test", "Rohan Das"),
]
SEEDED_STUDENT_PASSWORD = "RiversideDemo!2026"
"""Used for newly created Grade 3 - B students AND as the reset value for the demo
login below. A shared known password is correct for demo fixtures on a throwaway
project; it is obviously not a pattern for real accounts."""

DEMO_LOGINS = [
    ("aarav.student@riverside-school.test", "Doubt Bot demo (student, Grade 3 - A)"),
    ("meera.teacher@riverside-school.test", "Top Doubts demo (teacher, Math across 3-A + 3-B)"),
]
"""Accounts whose passwords are reset to SEEDED_STUDENT_PASSWORD on every run and
printed at the end. Both were created through the admin endpoints with a caller-
supplied password that was never recorded anywhere in this repo, so without this reset
each demo depends on someone remembering it. Meera (user 22398) is the Step 8 login:
she teaches Math to BOTH Grade 3 sections, so she is the person who sees one
cross-section cluster rather than two separate ones."""

# --- Seeded doubt logs for Top Doubts (Step 8) ---------------------------------------
# Written as GENUINE student phrasing - misspellings, no capitals, half-sentences.
# That is not decoration: clean textbook queries cluster at almost any threshold, so
# seeding them would prove nothing about whether the chosen threshold is right. Real
# phrasing is what makes "why do we carry the one" and "i dont get the small number on
# top" land in the same cluster despite sharing almost no vocabulary.
#
# (section, subject_name, question). The MATH cluster deliberately spans BOTH Grade 3
# sections - Meera Iyer teaches Math to A and B, so she is the one person who sees it
# as a single insight. That is the whole demo beat.
SEEDED_DOUBTS: list[tuple[str, str, str]] = [
    # --- Headline cluster: regrouping/carrying in multiplication. 6 questions,
    #     both sections, 6 different children. ---
    ("A", "Math", "why do we carry the one when we multiply"),
    ("A", "Math", "i dont get the small number you write on top"),
    ("B", "Math", "what does the little 2 above the tens mean"),
    ("B", "Math", "when do i have to regroup and when do i not"),
    ("A", "Math", "miss i keep forgetting to add the carried number, why does it go to the tens"),
    ("B", "Math", "is carrying the one the same as regrouping? confused"),
    # --- Second cluster: the dark-cupboard plant result. 5 questions, both sections. ---
    ("A", "Science", "why did pot B get taller if it had no light"),
    ("B", "Science", "how can the plant in the cupboard grow without sun"),
    ("A", "Science", "i thought no light means no growing but pot b grew"),
    ("B", "Science", "why did the plant in the dark go yellow after week 2"),
    ("A", "Science", "does the seed have food inside it already"),
    # --- Third cluster: proper nouns / capital letters. 4 questions. ---
    ("A", "English", "do i put a capital on monday"),
    ("B", "English", "why is august capital but summer is not"),
    ("A", "English", "when do days of the week get big letters"),
    ("B", "English", "is winter a proper noun or not"),
    # --- Singletons, so the ranking has something to discard. ---
    ("A", "Math", "how many marks is the term 1 test"),
    ("B", "Science", "can i bring my plant home after the experiment"),
    ("A", "English", "how long should the paragraph be"),
]

DEMO_CONTENT_DIR = Path(__file__).parent / "demo_content"
DEMO_RESOURCES = [
    ("grade3-math-multiplication.md", "Grade 3 Math — Multiplication and Regrouping", "Math"),
    ("grade3-science-plants.md", "Grade 3 Science — How Plants Make Their Food", "Science"),
    ("grade3-english-nouns-paragraphs.md", "Grade 3 English — Nouns, Adjectives and Paragraphs", "English"),
]
FEE_TYPE = "Term 1 Tuition"
FEE_AMOUNT = 4500.0
DAYS_OVERDUE = 21
"""Past due by enough to clear the fee reminder engine's later cadence tiers, not
just the first - so POST /admin/fees/reminders has something real to decide on.
See services/fee_reminder_engine.py::determine_reminder."""

RISK_REASONS = ["attendance rate 60% is below the 90% threshold"]


def _get_parent(session: Session) -> User:
    parent = session.query(User).filter(User.email == PARENT_EMAIL).one_or_none()
    if parent is None:
        raise SystemExit(
            f"No user with email {PARENT_EMAIL!r}. This script only wires up EXISTING "
            "Riverside accounts - it does not create people. Check the email or pick "
            "another real parent."
        )
    return parent


def _children(session: Session, parent_id: int) -> list[User]:
    return (
        session.query(User)
        .join(ParentStudent, ParentStudent.student_id == User.id)
        .filter(ParentStudent.parent_id == parent_id)
        .order_by(User.id)
        .all()
    )


def _get_or_create_fee_schedule(session: Session, school_id: int, counts: dict) -> FeeSchedule:
    """Natural key: (school_id, academic_year, fee_type) - school-wide, no class_id,
    so it applies to both children regardless of which section they're in."""
    schedule = (
        session.query(FeeSchedule)
        .filter(
            FeeSchedule.school_id == school_id,
            FeeSchedule.academic_year == ACADEMIC_YEAR,
            FeeSchedule.fee_type == FEE_TYPE,
        )
        .one_or_none()
    )
    if schedule is not None:
        return schedule

    schedule = FeeSchedule(
        school_id=school_id, class_id=None, academic_year=ACADEMIC_YEAR,
        fee_type=FEE_TYPE, amount=FEE_AMOUNT, due_date=date.today() - timedelta(days=DAYS_OVERDUE),
    )
    session.add(schedule)
    session.flush()
    counts["fee_schedules"] = counts.get("fee_schedules", 0) + 1
    return schedule


def _get_or_create_fee_record(session: Session, student: User, schedule: FeeSchedule, counts: dict) -> FeeRecord:
    """Natural key: (student_id, fee_schedule_id) - the same pair
    scripts/run_monthly_fee_invoicing.py treats as unique."""
    record = (
        session.query(FeeRecord)
        .filter(FeeRecord.student_id == student.id, FeeRecord.fee_schedule_id == schedule.id)
        .one_or_none()
    )
    if record is not None:
        return record

    record = FeeRecord(
        student_id=student.id, fee_schedule_id=schedule.id, amount_due=schedule.amount,
        amount_paid=0.0, status="overdue", due_date=schedule.due_date,
    )
    session.add(record)
    session.flush()
    counts["fee_records"] = counts.get("fee_records", 0) + 1
    return record


def _ensure_homeroom_teacher(session: Session, children: list[User], counts: dict) -> SchoolClass | None:
    """Give the children's class a class_teacher_id if it has none.

    Without this the early-warning dispatch's teacher recipient resolves to None
    and only the parents are notified - the class these children are in
    (Grade 3 - A) was created with a NULL class_teacher_id. Get-or-create
    semantics like everything else here: a class that ALREADY has a teacher is
    left completely alone, never reassigned.
    """
    enrollment = (
        session.query(Enrollment)
        .filter(Enrollment.student_id.in_([c.id for c in children]), Enrollment.is_primary.is_(True))
        .first()
    )
    if enrollment is None:
        return None

    school_class = session.query(SchoolClass).filter(SchoolClass.id == enrollment.class_id).one()
    if school_class.class_teacher_id is not None:
        return school_class

    teacher_role = session.query(Role).filter(Role.name == "teacher").one()
    teacher = (
        session.query(User)
        .filter(User.school_id == school_class.school_id, User.role_id == teacher_role.id)
        .order_by(User.id)
        .first()
    )
    if teacher is None:
        print(f"  ! no teacher exists in school {school_class.school_id} - leaving class_teacher_id NULL")
        return school_class

    school_class.class_teacher_id = teacher.id
    session.flush()
    counts["class_teacher_assigned"] = counts.get("class_teacher_assigned", 0) + 1
    return school_class


def _get_or_create_risk_flag(session: Session, student: User, counts: dict) -> RiskFlag:
    """Natural key: one OPEN flag per student. A student who already has an open
    flag (one of the two children does) is left exactly as-is."""
    flag = (
        session.query(RiskFlag)
        .filter(RiskFlag.student_id == student.id, RiskFlag.status == "open")
        .first()
    )
    if flag is not None:
        return flag

    flag = RiskFlag(student_id=student.id, risk_level="high", score=0.8, reasons=RISK_REASONS, status="open")
    session.add(flag)
    session.flush()
    counts["risk_flags"] = counts.get("risk_flags", 0) + 1
    return flag


def _grade3_a(session: Session) -> SchoolClass:
    school_class = (
        session.query(SchoolClass)
        .filter(SchoolClass.school_id == SCHOOL_ID, SchoolClass.grade_level == 3, SchoolClass.section == "A")
        .one_or_none()
    )
    if school_class is None:
        raise SystemExit("Grade 3 - A does not exist in school 5707 - nothing to mirror a B section from.")
    return school_class


def _get_or_create_grade3b(session: Session, counts: dict) -> SchoolClass:
    """Natural key: (school_id, grade_level=3, section="B")."""
    school_class = (
        session.query(SchoolClass)
        .filter(SchoolClass.school_id == SCHOOL_ID, SchoolClass.grade_level == 3, SchoolClass.section == "B")
        .one_or_none()
    )
    if school_class is not None:
        return school_class

    grade_3a = _grade3_a(session)
    teacher_role = session.query(Role).filter(Role.name == "teacher").one()
    # A DIFFERENT homeroom teacher from 3-A where one is available: two sections of a
    # grade normally have different class teachers, and it keeps the Top Doubts story
    # honest (the insight is shared via the SUBJECT teacher, not because one person
    # happens to own both homerooms).
    teacher = (
        session.query(User)
        .filter(
            User.school_id == SCHOOL_ID,
            User.role_id == teacher_role.id,
            User.id != grade_3a.class_teacher_id,
        )
        .order_by(User.id)
        .first()
    )
    school_class = SchoolClass(
        school_id=SCHOOL_ID, name=GRADE_3B_NAME, academic_year=ACADEMIC_YEAR,
        grade_level=3, section="B",
        class_teacher_id=teacher.id if teacher else grade_3a.class_teacher_id,
        home_room_id=None,
    )
    session.add(school_class)
    session.flush()
    counts["classes"] = counts.get("classes", 0) + 1
    return school_class


def _get_or_create_grade3b_students(session: Session, school_class: SchoolClass, counts: dict) -> list[User]:
    """Real, login-capable accounts via the same create_auth_account path
    routers/students.py uses - so these are consistent with the existing Riverside
    students (which are genuine Supabase Auth identities), not uuid5 stubs like
    seed_demo_data.py's. Natural key is the email, in both Supabase and our table."""
    from app.services.supabase_admin import create_auth_account

    students: list[User] = []
    student_role = session.query(Role).filter(Role.name == "student").one()
    for email, full_name in GRADE_3B_STUDENTS:
        user = session.query(User).filter(User.email == email).one_or_none()
        if user is None:
            try:
                supabase_id = create_auth_account(
                    email=email, password=SEEDED_STUDENT_PASSWORD, full_name=full_name, role="student"
                )
            except Exception as exc:  # noqa: BLE001
                # 409 means the Auth account exists but our local row does not (a
                # half-finished earlier run). Recover by looking the identity up
                # rather than dying - that is what keeps this script re-runnable.
                supabase_id = _lookup_auth_id(email)
                if supabase_id is None:
                    raise SystemExit(f"Could not create or find an auth account for {email}: {exc}") from exc
            user = User(
                supabase_id=supabase_id, email=email, full_name=full_name,
                role_id=student_role.id, school_id=SCHOOL_ID,
            )
            session.add(user)
            session.flush()
            counts["students"] = counts.get("students", 0) + 1

        enrollment = (
            session.query(Enrollment)
            .filter(Enrollment.student_id == user.id, Enrollment.class_id == school_class.id, Enrollment.subject_id.is_(None))
            .one_or_none()
        )
        if enrollment is None:
            session.add(Enrollment(student_id=user.id, class_id=school_class.id, subject_id=None, is_primary=True))
            session.flush()
            counts["enrollments"] = counts.get("enrollments", 0) + 1
        students.append(user)
    return students


def _lookup_auth_id(email: str) -> uuid.UUID | None:
    from app.services.supabase_admin import _new_client

    client = _new_client()
    page = 1
    while page <= 10:
        batch = client.auth.admin.list_users(page=page, per_page=1000)
        rows = batch if isinstance(batch, list) else getattr(batch, "users", [])
        if not rows:
            return None
        for row in rows:
            if (row.email or "").lower() == email.lower():
                return uuid.UUID(str(row.id))
        page += 1
    return None


def _ensure_grade3b_slots(session: Session, school_class: SchoolClass, counts: dict) -> int:
    """Give 3-B timetable slots for Math/Science/English taught by the SAME teachers who
    already teach those subjects to 3-A.

    This is the mechanism that makes Step 8 work: GET /bots/insights/top-doubts resolves
    "who teaches subject S at grade G" from timetable_slots, so sharing the teacher
    across both sections is what lets one person see both sections' confusion as a
    single cross-section insight.
    """
    grade_3a = _grade3_a(session)
    room = session.query(Room).filter(Room.school_id == SCHOOL_ID, Room.is_active.is_(True)).order_by(Room.id).first()
    if room is None:
        print("  ! no active room in school 5707 - skipping Grade 3 - B timetable slots")
        return 0

    created = 0
    for subject_name in ("Math", "Science", "English"):
        subject = session.query(Subject).filter(Subject.school_id == SCHOOL_ID, Subject.name == subject_name).one_or_none()
        if subject is None:
            continue
        source_slot = (
            session.query(TimetableSlot)
            .filter(TimetableSlot.class_id == grade_3a.id, TimetableSlot.subject_id == subject.id)
            .order_by(TimetableSlot.id)
            .first()
        )
        if source_slot is None:
            continue

        # Same weekday as 3-A's slot but a later period, so the shared teacher is not
        # double-booked against their own 3-A lesson.
        day_of_week, period_number = source_slot.day_of_week, source_slot.period_number + 4
        existing = (
            session.query(TimetableSlot)
            .filter(
                TimetableSlot.class_id == school_class.id,
                TimetableSlot.subject_id == subject.id,
                TimetableSlot.academic_year == ACADEMIC_YEAR,
            )
            .first()
        )
        if existing is not None:
            continue

        session.add(
            TimetableSlot(
                day_of_week=day_of_week, period_number=period_number,
                start_time=time(hour=min(8 + period_number, 16)), end_time=time(hour=min(9 + period_number, 17)),
                subject_id=subject.id, teacher_id=source_slot.teacher_id, class_id=school_class.id,
                room_id=room.id, academic_year=ACADEMIC_YEAR, is_active=True,
            )
        )
        session.flush()
        created += 1
    if created:
        counts["timetable_slots"] = counts.get("timetable_slots", 0) + created
    return created


def _get_or_create_resources(session: Session, school_class: SchoolClass, uploader: User, counts: dict) -> list[Resource]:
    """Upload the three demo curriculum documents as real Resource rows + real stored
    objects. Natural key: (class_id, title).

    `indexed_at` is deliberately left NULL - chunking/embedding is ingestion's job, not
    this script's, and leaving it null means the reindex path (POST /bots/reindex, or
    the nightly job) picks them up. That also keeps this script free of any Gemini
    dependency, so it can run without an API key.
    """
    from app.services.supabase_admin import upload_resource_file

    created: list[Resource] = []
    for filename, title, subject_name in DEMO_RESOURCES:
        existing = (
            session.query(Resource)
            .filter(Resource.grade_level == school_class.grade_level, Resource.title == title,
                    Resource.school_id == SCHOOL_ID)
            .one_or_none()
        )
        if existing is not None:
            created.append(existing)
            continue

        path = DEMO_CONTENT_DIR / filename
        if not path.exists():
            print(f"  ! missing demo content file {path} - skipping")
            continue
        subject = session.query(Subject).filter(Subject.school_id == SCHOOL_ID, Subject.name == subject_name).one_or_none()

        resource = Resource(
            school_id=SCHOOL_ID, grade_level=school_class.grade_level,
            subject_id=subject.id if subject else None,
            title=title, file_url="pending", mime_type="text/markdown",
            uploaded_by=uploader.id,
        )
        session.add(resource)
        session.flush()
        resource.file_url = upload_resource_file(
            path=f"{SCHOOL_ID}/grade-{school_class.grade_level}/{resource.id}-{filename}",
            data=path.read_bytes(),
            content_type="text/markdown",
        )
        session.flush()
        counts["resources"] = counts.get("resources", 0) + 1
        created.append(resource)
    return created


def _get_or_create_doubt_logs(
    session: Session, class_a: SchoolClass, class_b: SchoolClass, counts: dict
) -> int:
    """Seed SEEDED_DOUBTS as real chatbot_logs rows, embedded through the REAL
    embedding path (services/llm.py, RETRIEVAL_QUERY, 1536 dims, L2-normalized).

    Embedding for real matters: the clustering threshold is tuned against these
    vectors, so fabricating random ones would tune it against noise and tell us
    nothing. This is the one part of the seed script that needs GEMINI_API_KEY.

    Natural key: (class_id, query) - a question already present is left alone, so the
    embedding spend happens once and re-runs are free.
    """
    from app.models.knowledge import ChatbotLog
    from app.services.llm import embed_query

    classes = {"A": class_a, "B": class_b}
    students = {
        section: (
            session.query(User)
            .join(Enrollment, Enrollment.student_id == User.id)
            .filter(Enrollment.class_id == school_class.id, Enrollment.is_primary.is_(True))
            .order_by(User.id)
            .all()
        )
        for section, school_class in classes.items()
    }
    subjects = {
        name: session.query(Subject).filter(Subject.school_id == SCHOOL_ID, Subject.name == name).one_or_none()
        for name in ("Math", "Science", "English")
    }

    created = 0
    per_section_cursor = {"A": 0, "B": 0}
    for section, subject_name, question in SEEDED_DOUBTS:
        school_class = classes[section]
        roster = students[section]
        if not roster:
            continue
        # Rotate through the section's real students so distinct_student_count is
        # meaningful rather than every question coming from one child.
        student = roster[per_section_cursor[section] % len(roster)]
        per_section_cursor[section] += 1

        existing = (
            session.query(ChatbotLog)
            .filter(ChatbotLog.class_id == school_class.id, ChatbotLog.query == question)
            .one_or_none()
        )
        if existing is not None:
            continue

        subject = subjects.get(subject_name)
        session.add(
            ChatbotLog(
                user_id=student.id,
                bot_type="student",
                query=question,
                response="(seeded fixture - no generated answer stored)",
                kb_chunks_used={"chunk_ids": []},
                query_embedding=embed_query(question),
                class_id=school_class.id,
                subject_id=subject.id if subject else None,
            )
        )
        session.flush()
        created += 1

    if created:
        counts["chatbot_logs"] = counts.get("chatbot_logs", 0) + created
    return created


def _reset_demo_passwords() -> list[tuple[str, str]]:
    """Reset every DEMO_LOGINS account to a known password, every run.

    Not get-or-create: this is an idempotent SET, which is the point - the whole reason
    it exists is that nobody recorded the original passwords when these accounts were
    created via the admin endpoints. Returns the (email, purpose) pairs that succeeded.
    """
    from app.services.supabase_admin import _new_client

    client = _new_client()
    reset: list[tuple[str, str]] = []
    for email, purpose in DEMO_LOGINS:
        auth_id = _lookup_auth_id(email)
        if auth_id is None:
            print(f"  ! no Supabase Auth account for {email} - cannot reset its password")
            continue
        client.auth.admin.update_user_by_id(str(auth_id), {"password": SEEDED_STUDENT_PASSWORD})
        reset.append((email, purpose))
    return reset


def seed(session: Session, counts: dict) -> dict:
    parent = _get_parent(session)
    children = _children(session, parent.id)
    if not children:
        raise SystemExit(f"{PARENT_EMAIL} has no linked children in parent_student - nothing to seed.")

    schedule = _get_or_create_fee_schedule(session, parent.school_id, counts)
    records = [_get_or_create_fee_record(session, child, schedule, counts) for child in children]
    flags = [_get_or_create_risk_flag(session, child, counts) for child in children]
    school_class = _ensure_homeroom_teacher(session, children, counts)

    # --- RAG / Top Doubts fixtures ---
    grade_3b = _get_or_create_grade3b(session, counts)
    grade_3b_students = _get_or_create_grade3b_students(session, grade_3b, counts)
    slots_created = _ensure_grade3b_slots(session, grade_3b, counts)

    # Resources go on Grade 3 - A (where the demo student is enrolled). Retrieval is
    # scoped by class_id, so a 3-B student would need their own copies - deliberately
    # not seeded, since it is exactly the cross-class isolation the security test
    # asserts.
    grade_3a = _grade3_a(session)
    uploader = (
        session.query(User).filter(User.id == grade_3a.class_teacher_id).one_or_none()
        or session.query(User).filter(User.school_id == SCHOOL_ID).order_by(User.id).first()
    )
    resources = _get_or_create_resources(session, grade_3a, uploader, counts)
    doubt_logs = _get_or_create_doubt_logs(session, grade_3a, grade_3b, counts)

    return {
        "doubt_logs": doubt_logs,
        "parent": parent, "children": children, "schedule": schedule,
        "records": records, "flags": flags, "class": school_class,
        "grade_3a": grade_3a, "grade_3b": grade_3b, "grade_3b_students": grade_3b_students,
        "grade_3b_slots": slots_created, "resources": resources,
    }


def main() -> None:
    session = SessionLocal()
    counts: dict[str, int] = {}
    try:
        data = seed(session, counts)
        session.commit()
    except Exception:
        session.rollback()
        raise
    else:
        parent, children = data["parent"], data["children"]
        print(f"Parent: {parent.email} (id={parent.id}, school_id={parent.school_id})")
        for child in children:
            print(f"  child: {child.full_name} (id={child.id})")
        print(f"Fee schedule id={data['schedule'].id} due {data['schedule'].due_date} ({FEE_TYPE})")
        print(f"Fee records:  {[r.id for r in data['records']]}")
        print(f"Risk flags:   {[f.id for f in data['flags']]}")
        school_class = data["class"]
        if school_class is not None:
            print(f"Class {school_class.id} ({school_class.name}): class_teacher_id={school_class.class_teacher_id}")
        grade_3b = data["grade_3b"]
        print(f"\nGrade 3 - B: class_id={grade_3b.id} class_teacher_id={grade_3b.class_teacher_id}")
        for student in data["grade_3b_students"]:
            print(f"  student: {student.full_name} (id={student.id}, {student.email})")
        print(f"  timetable slots created this run: {data['grade_3b_slots']}")
        print(f"\nResources on {data['grade_3a'].name} (class_id={data['grade_3a'].id}):")
        for resource in data["resources"]:
            state = "indexed" if resource.indexed_at else "NOT yet indexed"
            print(f"  [{resource.id}] {resource.title}  ({state})")
        print(f"\nSeeded doubt logs created this run: {data['doubt_logs']}")
        print(f"Rows created this run: {counts or 'none - everything already existed'}")

        reset = _reset_demo_passwords()
        if reset:
            print("\n" + "=" * 72)
            print("  DEMO LOGINS (passwords reset on every run of this script)")
            print(f"  shared password: {SEEDED_STUDENT_PASSWORD}")
            for email, purpose in reset:
                print(f"    {email:44} {purpose}")
            print(f"  student class_id: {data['grade_3a'].id} ({data['grade_3a'].name})"
                  f"   |   sibling section: {data['grade_3b'].id} ({data['grade_3b'].name})")
            print("=" * 72)

        print(
            "\nNotifications are NOT created by this script - they are a side effect of the\n"
            "real endpoints. To make the bell light up for this parent, call:\n"
            "  POST /admin/fees/reminders  {\"overdue_only\": true}   -> fee_reminder\n"
            "  POST /risk/flag             {...}                     -> early_warning\n"
            "Resources are seeded UNINDEXED - to embed them, call:\n"
            "  POST /bots/reindex          {}                        -> chunks written"
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
