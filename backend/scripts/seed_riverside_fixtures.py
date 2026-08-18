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
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.attendance import AttendanceRecord
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
    ("aarav.student@riverside-school.test", "student  - Doubt Bot, Grade 3 - A"),
    ("meera.teacher@riverside-school.test", "teacher  - Top Doubts, Math across 3-A + 3-B"),
    ("guardian.kumar@riverside-school.test", "parent   - portal + Parent Bot, 2 children"),
    ("founder@riverside-school.test", "admin    - Command Center, resources, approvals"),
]

# --- Parent-portal demo profiles -----------------------------------------------------
# The two children must read DIFFERENTLY or the child selector looks decorative. Before
# this, Aarav had 5 attendance rows (all one day) and Diya had none at all, both had the
# same overdue fee, and neither had a single remark - so switching child changed almost
# nothing on screen and emptied the attendance card.
#
# Every number below is chosen against services/risk_scorer.py's real arithmetic, so the
# flags that come out of the NIGHTLY SCORER (not hand-written reasons) land where the
# demo needs them. With no gradebook, effective weights are attendance 0.50 / remarks
# 0.15 of a 0.65 total:
#   Aarav  28 present + 1 absent + 1 late of 30 = 93% -> attendance risk 0.0,
#          positive remarks -> remark risk 0.0 -> score 0.0 -> LOW -> NO FLAG.
#   Diya   19 present + 11 absent of 30 = 63%  -> attendance risk (0.90-0.63)/0.90
#          = 0.30, negative remarks (avg compound ~-0.3) -> score ~0.32 -> MEDIUM -> FLAGGED.
# That asymmetry is the point: the at-risk banner appears and disappears as you switch
# child, which reads far better on stage than two identically-flagged children.
SEED_ANCHOR_DATE = date(2026, 8, 18)
"""FIXED anchor for every date this script generates. Deliberately NOT date.today().

Two bugs came from anchoring on today, and pinning fixes both at once:

1. DRIFT. Rows are never deleted, so each run on a new weekday appended one more row at
   pattern[-1] - "absent" for Diya, "present" for Aarav. The demo figures moved every
   day, and the printed numbers stopped matching any checklist written the day before.

2. WINDOW MISMATCH. ATTENDANCE_SCHOOL_DAYS was 30 SCHOOL days, which spans ~42 CALENDAR
   days. But the risk scorer and the parent portal both look back
   ATTENDANCE_LOOKBACK_DAYS = 30 CALENDAR days (routers/parent.py imports the very same
   constant). The oldest third of the seeded window was therefore outside the window
   that scores it, and this script's printed percentage could never agree with the one
   the portal showed. ATTENDANCE_SCHOOL_DAYS is now sized to fit INSIDE the lookback.

KEEP THIS WITHIN A FEW DAYS OF THE DEMO. A fixed anchor stops the drift but does not
stop the calendar: once the whole window ages past ATTENDANCE_LOOKBACK_DAYS, the scorer
sees zero attendance rows, scores attendance risk as 0.0 with no reason string, and
Diya's flag quietly disappears. _warn_if_anchor_is_stale() prints a loud warning before
that happens - re-pin this to today's date and re-run when it fires."""

ATTENDANCE_SCHOOL_DAYS = 21
"""21 weekdays back from the anchor spans ~27 calendar days, so the generated window
sits inside ATTENDANCE_LOOKBACK_DAYS (30) with a few days of slack for the anchor to
age before anything falls out. Was 30, which spanned ~42 days and overflowed it. Do not
raise this above ~21 without also raising the scorer's lookback, or you reintroduce the
mismatch described in SEED_ANCHOR_DATE."""

# (present_count, absent_count, late_count) is NOT how these are built - the ORDER
# matters. Diya's absences are deliberately clustered into the most recent run so the
# feed shows a visible decline rather than a low average scattered through the term.
AARAV_ATTENDANCE_PATTERN = ["present"] * 15 + ["late"] + ["present"] * 5
"""One late, no absences. Deliberately cleaner than it looks like it needs to be,
because Aarav ALSO carries 5 real `source="cv"` rows from an actual CV-attendance run
on 2026-08-15 - 5 period-level records for a single day, 4 of them absent. Those are
genuine feature output, not fixture junk, so they are left alone; this pattern is
sized so his overall rate still lands comfortably clear of a flag despite them.

Worth knowing: attendance_records mixes granularities - `manual` rows here are
DAY-level, `cv` rows are PERIOD-level - so one heavily-absent CV day counts as much as
four absent days. That is a pre-existing modelling wrinkle, not something introduced
here, but it is why Aarav's headline percentage is lower than a 30-day all-present
pattern would suggest."""
DIYA_ATTENDANCE_PATTERN = ["present"] * 11 + ["absent"] + ["present"] + ["absent"] * 8
"""12 present / 21 = 57%, comfortably under the 90% threshold, with the 8 absences
clustered at the recent end so the feed shows a visible decline. Resized from 30 to 21
entries alongside ATTENDANCE_SCHOOL_DAYS - the ratio is what matters, not the length."""

# 6 remarks each, from the teachers who genuinely teach Grade 3 - A (resolved from
# timetable_slots at runtime, not hardcoded ids). Aarav skews positive, Diya negative.
# Sentiment is scored per-request by services/remark_sentiment.py - nothing is stored -
# so the text itself has to do the work. Note REMARK_LOOKBACK_COUNT=5 in the nightly
# scorer: only the 5 most RECENT remarks feed the risk score, so Diya's newest five are
# the negative ones.
AARAV_REMARKS = [
    ("Math", 38, "Aarav volunteered to show his ladder method on the board and explained every rung clearly. Excellent work."),
    ("English", 31, "A thoughtful, well-structured burger paragraph this week. He is using stronger adjectives without being reminded."),
    ("Science", 24, "Aarav ran the Pot D measurement carefully and spotted that the petroleum jelly was the only difference. Sharp observation."),
    ("Math", 17, "Confident with regrouping now. He helped Kabir understand carrying the tens, which was kind and patient."),
    ("English", 10, "Reads aloud with lovely expression. A pleasure to teach."),
    ("Science", 4, "Consistently curious and asks genuinely good questions about the experiment."),
]
DIYA_REMARKS = [
    ("Science", 40, "Diya enjoyed setting up the bean pots and labelled all four correctly."),
    ("Math", 33, "Struggling with regrouping. She gets frustrated and gives up quickly when the first attempt is wrong."),
    ("English", 26, "Diya has not handed in the last two writing tasks. She is quiet and withdrawn in class."),
    ("Math", 18, "Absent again for the multiplication test. She is falling behind the rest of the class."),
    ("Science", 11, "Disruptive during the group activity and refused to take part. This is unlike her earlier in the term."),
    ("English", 5, "Worried about Diya. She is disengaged, rarely speaks, and her attendance is getting worse."),
]

FEE_PAID_STUDENT = "Aarav"
"""Aarav's fee record is SET to paid and Diya's left overdue, so the fees card also
changes on child switch. Before this both children had an identical 4500 overdue row."""
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
        fee_type=FEE_TYPE, amount=FEE_AMOUNT, due_date=SEED_ANCHOR_DATE - timedelta(days=DAYS_OVERDUE),
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


# --- Doubt threads --------------------------------------------------------------------
# Human-to-human threads in Grade 3 - A. Three already answered so the list doesn't look
# empty, and ONE deliberately left open with its answer written and waiting - that is the
# thread to verify live on stage.
#
# THE OPEN THREAD'S QUESTION MUST NOT BE ANSWERABLE FROM ANY UPLOADED DOCUMENT. If a
# resource already covered it, verifying the reply would change nothing observable and
# the whole demo beat fails - the bot would answer identically before and after. So it
# asks about a made-up Riverside marking convention with a specific number in it: nothing
# in DEMO_RESOURCES mentions it, and the answer cannot be inferred from general knowledge
# either. Checked against the three seeded documents.
#
# (author, title, body, [(reply_author, reply_body, verified?), ...])
# author/reply_author: "student" = Aarav, "teacher" = 3-A's homeroom teacher (Meera).
DEMO_THREADS: tuple[tuple[str, str, str, tuple[tuple[str, str, bool], ...]], ...] = (
    (
        "student",
        "Why do we carry the 1 when adding 47 and 38?",
        "I get 15 for 7 plus 8 but I don't understand where the 1 goes.",
        (
            ("student", "I think you write the 5 and move the 1 to the tens column?", False),
            (
                "teacher",
                "That's right, and here is why. 7 + 8 = 15, which is one ten and five ones. "
                "The ones column can only hold a single digit, so the five stays there and the "
                "one ten moves across to the tens column. Then 4 + 3 + 1 = 8, giving 85. "
                "Regrouping is just moving a full group of ten into the next column.",
                True,
            ),
        ),
    ),
    (
        "student",
        "Is 'happiness' a noun or an adjective?",
        "Happy is an adjective so I thought happiness would be too.",
        (
            (
                "teacher",
                "Happiness is a noun - it names a thing you can have. Happy is the adjective, "
                "because it describes somebody. A good test: if you can put 'the' in front of it "
                "and it still makes sense, it's a noun. 'The happiness' works; 'the happy' does not.",
                True,
            ),
        ),
    ),
    (
        "student",
        "Do plants eat the soil to make their food?",
        "My cousin said plants eat soil but the chapter talks about sunlight.",
        (
            ("student", "I think they use sunlight, not soil.", False),
            (
                "teacher",
                "Plants do not eat soil. They make their own food in their leaves using sunlight, "
                "water and carbon dioxide from the air - that is photosynthesis. Soil holds the "
                "water and a few minerals the plant needs, but it is not the food itself.",
                True,
            ),
        ),
    ),
    # ---- THE LIVE DEMO THREAD: left unverified, with its answer ready to certify ----
    (
        "student",
        "What is the Riverside three-star rule for a science diagram?",
        "Ma'am mentioned a rule about labelling diagrams before the test but I forgot how many "
        "stars each part is worth.",
        (
            (
                "teacher",
                "At Riverside we mark every science diagram with the three-star rule. One star for "
                "drawing the outline in pencil, one star for labelling at least three parts in "
                "lowercase, and one star for ruled pointer lines that never cross each other. "
                "All three stars must be earned for full marks - a beautiful drawing with only two "
                "labels still loses a star, and pointer lines drawn freehand lose one even if every "
                "label is correct.",
                False,
            ),
        ),
    ),
)

UNVERIFIED_DEMO_THREAD_TITLE = DEMO_THREADS[-1][1]
"""The thread to verify on stage. Named so the summary output can point at it."""


def _get_or_create_doubt_threads(
    session: Session, school_class: SchoolClass, student: User, teacher: User | None, counts: dict
) -> list:
    """Seed the demo doubt threads. Natural key: (class_id, title).

    Idempotent in the strong sense: an existing thread is left EXACTLY as found,
    including its verified/unverified state. That matters more here than elsewhere -
    re-running this script after a rehearsal must not silently re-verify the thread you
    just unverified to reset the demo, or the live beat is gone with no warning.
    """
    from app.models.doubt import DoubtThread, ThreadReply

    authors = {"student": student, "teacher": teacher or student}
    threads = []
    for author_key, title, body, replies in DEMO_THREADS:
        existing = (
            session.query(DoubtThread)
            .filter(DoubtThread.class_id == school_class.id, DoubtThread.title == title)
            .one_or_none()
        )
        if existing is not None:
            threads.append(existing)
            continue

        thread = DoubtThread(
            school_id=SCHOOL_ID,
            class_id=school_class.id,
            subject_id=None,
            author_id=authors[author_key].id,
            title=title,
            body=body,
            resolved=False,
        )
        session.add(thread)
        session.flush()
        counts["doubt_threads"] = counts.get("doubt_threads", 0) + 1

        for reply_author_key, reply_body, is_verified in replies:
            reply = ThreadReply(
                thread_id=thread.id, author_id=authors[reply_author_key].id, body=reply_body
            )
            session.add(reply)
            session.flush()
            counts["thread_replies"] = counts.get("thread_replies", 0) + 1
            if is_verified:
                # Sets the flag WITHOUT ingesting - embedding is the verify endpoint's
                # job, and this script stays free of any Gemini dependency (same choice
                # as resources being seeded with indexed_at NULL). Run POST
                # /bots/reindex or re-verify through the API to embed these.
                thread.resolved = True
                thread.verified_reply_id = reply.id
        threads.append(thread)

    session.commit()
    return threads


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


def _school_days_back(count: int, *, end: date | None = None) -> list[date]:
    """The last `count` weekdays, oldest first. Weekends skipped - attendance on a
    Saturday would be obviously wrong to anyone reading the feed on stage.

    Defaults to SEED_ANCHOR_DATE, not date.today() - see that constant for why."""
    day = end or SEED_ANCHOR_DATE
    days: list[date] = []
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return list(reversed(days))


def _warn_if_anchor_is_stale() -> None:
    """Fail LOUDLY when the anchor has drifted out of the scorer's lookback window.

    The failure this guards against is silent: once every seeded row is older than
    ATTENDANCE_LOOKBACK_DAYS, _attendance_component() sees total_records == 0, returns
    (0.0, None), and Diya's risk flag is downgraded or resolved by the nightly scorer.
    Nothing errors - the demo just quietly loses its best contrast, and the first time
    anyone notices is on stage.
    """
    from scripts.run_nightly_risk_scoring import ATTENDANCE_LOOKBACK_DAYS

    oldest = _school_days_back(ATTENDANCE_SCHOOL_DAYS)[0]
    age = (date.today() - oldest).days
    anchor_age = (date.today() - SEED_ANCHOR_DATE).days

    if age > ATTENDANCE_LOOKBACK_DAYS:
        lost = age - ATTENDANCE_LOOKBACK_DAYS
        print(
            f"\n!!! SEED_ANCHOR_DATE IS STALE ({SEED_ANCHOR_DATE}, {anchor_age} days ago) !!!\n"
            f"    The oldest seeded school day is {age} calendar days old, but the risk\n"
            f"    scorer and parent portal only look back {ATTENDANCE_LOOKBACK_DAYS} days.\n"
            f"    Roughly {lost} day(s) of the window has fallen outside it, so the\n"
            f"    attendance figures - and Diya's risk flag - are already degraded.\n"
            f"    FIX: set SEED_ANCHOR_DATE to today's date and re-run.\n"
        )
    elif anchor_age > 2:
        slack = ATTENDANCE_LOOKBACK_DAYS - age
        print(
            f"\n!   SEED_ANCHOR_DATE ({SEED_ANCHOR_DATE}) was pinned {anchor_age} days ago.\n"
            f"    {slack} day(s) of slack left before the oldest seeded day falls outside\n"
            f"    the {ATTENDANCE_LOOKBACK_DAYS}-day scoring window. Re-pin it to today\n"
            f"    before the demo.\n"
        )


def _get_or_create_attendance(session: Session, student: User, class_id: int, pattern: list[str], counts: dict) -> int:
    """Seed one attendance row per school day, following `pattern` oldest-first.

    Natural key: (student_id, date, source). timetable_slot_id is left NULL - these are
    day-level records, not tied to a generated period, so they stay valid regardless of
    whether POST /timetable/generate has been run. source="manual" matches the rows that
    already existed, so nothing here reads as fabricated CV output.

    RECONCILES rather than skips. An earlier version returned early on any existing row,
    which meant a changed pattern could never take effect: the days already had rows, so
    the new statuses were silently ignored and the fixtures kept whatever a previous run
    had written. Now an existing row's status is UPDATED to match the pattern.

    Only ever inserts or updates - never deletes. Rows outside the anchored window
    (including the genuine source="cv" rows from a real CV-attendance run) are left
    completely alone.
    """
    days = _school_days_back(len(pattern))
    created = 0
    updated = 0
    for day, status in zip(days, pattern):
        existing = (
            session.query(AttendanceRecord)
            .filter(
                AttendanceRecord.student_id == student.id,
                AttendanceRecord.date == day,
                AttendanceRecord.source == "manual",
            )
            .one_or_none()
        )
        if existing is not None:
            if existing.status != status:
                existing.status = status
                updated += 1
            continue
        session.add(
            AttendanceRecord(
                student_id=student.id, class_id=class_id, timetable_slot_id=None,
                date=day, status=status, source="manual",
            )
        )
        created += 1
    if created or updated:
        session.flush()
    if created:
        counts["attendance_records"] = counts.get("attendance_records", 0) + created
    if updated:
        counts["attendance_records_realigned"] = counts.get("attendance_records_realigned", 0) + updated
    return created


def _get_or_create_remarks(session: Session, student: User, remarks: list[tuple[str, int, str]], counts: dict) -> int:
    """Seed teacher remarks, authored by the teacher who actually teaches that subject
    to this student's class (resolved from timetable_slots).

    `created_at` is backdated by the given number of days so the feed looks lived-in
    rather than six remarks all posted this morning - and so the nightly scorer's
    "5 most recent" window picks the intended ones.
    """
    from app.models.risk import RemarkStub

    enrollment = (
        session.query(Enrollment)
        .filter(Enrollment.student_id == student.id, Enrollment.is_primary.is_(True))
        .first()
    )
    if enrollment is None:
        return 0

    teacher_by_subject = {
        subject_name: teacher_id
        for subject_name, teacher_id in session.query(Subject.name, TimetableSlot.teacher_id)
        .join(TimetableSlot, TimetableSlot.subject_id == Subject.id)
        .filter(TimetableSlot.class_id == enrollment.class_id)
        .distinct()
    }

    created = 0
    for subject_name, days_ago, text in remarks:
        teacher_id = teacher_by_subject.get(subject_name)
        if teacher_id is None:
            continue
        existing = (
            session.query(RemarkStub)
            .filter(RemarkStub.student_id == student.id, RemarkStub.remark_text == text)
            .one_or_none()
        )
        if existing is not None:
            continue
        row = RemarkStub(student_id=student.id, teacher_id=teacher_id, remark_text=text)
        session.add(row)
        session.flush()
        # created_at has a server_default, so it must be overwritten AFTER the insert.
        row.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        created += 1
    if created:
        session.flush()
        counts["remark_stubs"] = counts.get("remark_stubs", 0) + created
    return created


def _differentiate_fees(session: Session, records: list[FeeRecord], children: list[User], counts: dict) -> None:
    """Mark the healthier child's fee PAID and leave the other overdue.

    An idempotent SET, not a get-or-create - unlike everything else in this script. The
    whole point is to force a known state: both children previously carried an identical
    4500-overdue row, so the fees card did not change at all on child switch.
    """
    by_student = {r.student_id: r for r in records}
    for child in children:
        record = by_student.get(child.id)
        if record is None:
            continue
        should_be_paid = FEE_PAID_STUDENT.lower() in (child.full_name or "").lower()
        if should_be_paid and record.status != "paid":
            record.amount_paid = record.amount_due
            record.status = "paid"
            counts["fee_records_marked_paid"] = counts.get("fee_records_marked_paid", 0) + 1
        elif not should_be_paid and record.status != "overdue":
            record.amount_paid = 0.0
            record.status = "overdue"
            counts["fee_records_marked_overdue"] = counts.get("fee_records_marked_overdue", 0) + 1
    session.flush()


def _rescore_risk_flags(session: Session, children: list[User], counts: dict) -> dict:
    """Clear the hand-written flags and regenerate them from Person A's real scorer.

    WHY NOT JUST EDIT THE REASONS: the three pre-existing flags carried reasons like
    "attendance rate 60% is below the 90% threshold" against a child who had ZERO
    attendance rows - a number nothing else in the app could corroborate. Since the
    parent portal now SHOWS `risk_flags.reasons` in its at-risk banner, a hand-written
    reason is a banner that contradicts the attendance card two rows below it.

    Resolving (not deleting) the old flags keeps the audit trail intact. The nightly
    scorer then rebuilds from the attendance and remarks seeded above, so what the
    banner says is what the rest of the page shows.

    Note the scorer SKIPS low-risk students entirely (no flag row), which is what makes
    the banner appear for Diya and vanish for Aarav.
    """
    from app.services.risk_scorer import score_student
    from scripts.run_nightly_risk_scoring import (
        _build_attendance_signal,
        _build_remark_signal,
        ATTENDANCE_LOOKBACK_DAYS,
        run_nightly_scoring,
    )

    # Resolve ONLY flags the scorer will no longer regenerate - i.e. students who now
    # score low. run_nightly_scoring skips low-risk students entirely (it never closes a
    # flag for someone who improved), so without this Aarav would keep a stale open flag
    # forever. Blanket-resolving every flag instead would churn: Diya's would be
    # resolved and recreated on every run, so this script would never be idempotent.
    since = date.today() - timedelta(days=ATTENDANCE_LOOKBACK_DAYS)
    for child in children:
        result = score_student(
            _build_attendance_signal(session, child.id, since),
            grades=None,
            remarks=_build_remark_signal(session, child.id),
        )
        if result.risk_level != "low":
            continue
        for flag in session.query(RiskFlag).filter(
            RiskFlag.student_id == child.id, RiskFlag.status == "open"
        ):
            flag.status = "resolved"
            flag.resolved_at = datetime.now(timezone.utc)
            counts["risk_flags_resolved"] = counts.get("risk_flags_resolved", 0) + 1
    session.commit()

    # Everyone still at risk gets their existing open flag UPDATED in place by the real
    # scorer, so reasons always match the attendance the portal displays.
    return run_nightly_scoring(session, SCHOOL_ID, ACADEMIC_YEAR)


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
    # Risk flags are NO LONGER hand-written here - see _rescore_risk_flags(), which runs
    # Person A's real nightly scorer against the attendance and remarks seeded below so
    # each flag's `reasons` match what the parent portal actually displays. The old
    # _get_or_create_risk_flag() invented a flag with a fixed reason string for every
    # child; keeping it alongside the scorer produced an endless churn (it recreated
    # Aarav's flag, the re-score resolved it, every single run).
    flags: list[RiskFlag] = []
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

    # Human doubt threads in 3-A - three answered, one left open for the live
    # verify-and-the-bot-learns beat. Aarav asks; 3-A's homeroom teacher answers.
    demo_student = next((c for c in children if (c.full_name or "").startswith("Aarav")), children[0])
    threads = _get_or_create_doubt_threads(session, grade_3a, demo_student, uploader, counts)

    # --- Parent-portal profiles: make the two children read differently ---
    attendance_patterns = {"Aarav": AARAV_ATTENDANCE_PATTERN, "Diya": DIYA_ATTENDANCE_PATTERN}
    remark_sets = {"Aarav": AARAV_REMARKS, "Diya": DIYA_REMARKS}
    for child in children:
        first_name = (child.full_name or "").split()[0]
        enrollment = (
            session.query(Enrollment)
            .filter(Enrollment.student_id == child.id, Enrollment.is_primary.is_(True))
            .first()
        )
        if enrollment is None:
            continue
        pattern = attendance_patterns.get(first_name)
        if pattern:
            _get_or_create_attendance(session, child, enrollment.class_id, pattern, counts)
        if first_name in remark_sets:
            _get_or_create_remarks(session, child, remark_sets[first_name], counts)

    _differentiate_fees(session, records, children, counts)
    # Must run LAST: it scores against the attendance and remarks seeded just above.
    scoring = _rescore_risk_flags(session, children, counts)

    return {
        "doubt_logs": doubt_logs,
        "scoring": scoring,
        "parent": parent, "children": children, "schedule": schedule,
        "records": records, "flags": flags, "class": school_class,
        "grade_3a": grade_3a, "grade_3b": grade_3b, "grade_3b_students": grade_3b_students,
        "grade_3b_slots": slots_created, "resources": resources,
        "threads": threads,
    }


def main() -> None:
    _warn_if_anchor_is_stale()
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
        print(f"Risk re-scoring (real nightly scorer): {data['scoring']}")
        print("\nParent-portal profiles:")
        # SAME WINDOW THE PORTAL AND THE SCORER USE. This used to query every
        # attendance row the student had ever accumulated, with no date filter at all,
        # while GET /parent/child/{id}/summary and the nightly scorer both look back
        # ATTENDANCE_LOOKBACK_DAYS. The numbers printed here under the heading
        # "Parent-portal profiles" therefore could not agree with the parent portal -
        # they counted rows the portal had already aged out. Anything printed here has
        # to be computed the way the screen computes it, or it is worse than no output.
        from scripts.run_nightly_risk_scoring import ATTENDANCE_LOOKBACK_DAYS as _LOOKBACK

        _since = date.today() - timedelta(days=_LOOKBACK)
        for child in children:
            att = (
                session.query(AttendanceRecord)
                .filter(AttendanceRecord.student_id == child.id, AttendanceRecord.date >= _since)
                .all()
            )
            present = sum(1 for a in att if a.status == "present")
            flag = (
                session.query(RiskFlag)
                .filter(RiskFlag.student_id == child.id, RiskFlag.status == "open")
                .one_or_none()
            )
            fee = session.query(FeeRecord).filter(FeeRecord.student_id == child.id).first()
            from app.models.risk import RemarkStub

            n_remarks = session.query(RemarkStub).filter(RemarkStub.student_id == child.id).count()
            pct = f"{100 * present / len(att):.0f}%" if att else "n/a"
            print(f"  {child.full_name:14} attendance {present}/{len(att)} ({pct})  remarks {n_remarks}  "
                  f"fee {fee.status if fee else '-':8} flag {flag.risk_level if flag else 'NONE (low risk)'}")
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

        open_thread = next(
            (t for t in data["threads"] if t.title == UNVERIFIED_DEMO_THREAD_TITLE), None
        )
        if open_thread is not None:
            print("\n" + "=" * 72)
            print("  THE LIVE DEMO THREAD - verify this one on stage")
            print(f"    thread id : {open_thread.id}   (Grade 3 - A, {data['grade_3a'].id})")
            print(f"    question  : {open_thread.title}")
            print(f"    state     : {'VERIFIED ALREADY - unverify it before demoing' if open_thread.resolved else 'open, reply ready'}")
            print("    beat      : teacher /teacher/doubts -> Mark verified")
            print("                student /student/doubt-bot -> ask the same question")
            print("                the answer now cites 'Verified answer - <teacher> - \"...\"'")
            print("    NOTE: nothing in the seeded documents mentions the three-star rule,")
            print("          so the bot genuinely cannot answer it until you verify.")
            print("=" * 72)

        print(
            "\nNotifications are NOT created by this script - they are a side effect of the\n"
            "real endpoints. To make the bell light up for this parent, call:\n"
            "  POST /admin/fees/reminders  {\"overdue_only\": true}   -> fee_reminder\n"
            "  POST /risk/flag             {...}                     -> early_warning\n"
            "Resources are seeded UNINDEXED - to embed them, call:\n"
            "  POST /bots/reindex          {}                        -> chunks written\n"
            "Seeded VERIFIED threads are flagged but NOT embedded (same reason - no Gemini\n"
            "dependency here). Re-verify one through the API to put it in the KB."
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
