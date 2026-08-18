"""Seeds "Shikshaa Public School" — a complete, demo-ready school.

WHY A THIRD SEED SCRIPT
-----------------------
`seed_demo_data.py` builds one grade-8 school for engineers to hit endpoints against.
`seed_riverside_fixtures.py` builds a narrow, date-pinned set of parent-portal/RAG fixtures on
top of an existing school. Neither produces what a *demo recording* needs: a whole primary
school, every screen populated, in one command.

WHAT IT BUILDS
--------------
  School      "Shikshaa Public School", academic year 2026-27
  Classes     Grades 1, 2, 3 x sections A and B = 6 classes
  Students    5 per class = 30, each with a real login
  Staff       1 principal, 1 admin, 8 teachers (6 homeroom + 2 floating)
  Parents     6, including one guardian with children in DIFFERENT grades
  Master data 3 subjects, 7 rooms (6 classrooms + 1 lab), teacher qualifications,
              one teacher unavailable all Friday so the solver has real work to do
  Timetable   solved by the REAL CP-SAT solver, not hand-written rows
  Academics   attendance history, remarks, gradebook marks, report cards, assignments,
              quizzes + attempts, syllabus plans + checkpoints, library loans
  RAG         3 resources per grade, really uploaded and really ingested into kb_chunks,
              plus a verified doubt answer in the corpus
  Ops         fee schedule + records (one overdue, one with a payment request),
              announcements (school-wide AND grade-scoped), exams + seating,
              one pending leave request
  Risk        flags produced by the REAL nightly scorer, not invented reasons

EVERY DERIVED THING COMES FROM THE REAL CODE PATH. The timetable is solved by
services/timetable_solver.py, risk flags by scripts/run_nightly_risk_scoring.py's own
`run_nightly_scoring`, report cards by services/report_card_service.py, the RAG corpus by
services/ingestion.py. Hand-inserting those rows would let the seed drift from what the app
actually produces, and a demo that shows fabricated output is worse than no demo.

NOT SEEDED, DELIBERATELY
------------------------
Face embeddings for CV attendance. They require real photographs — a script cannot fabricate a
face. Enrol a few yourself via POST /attendance/enroll before recording.

USAGE
-----
    cd backend
    venv/Scripts/python.exe -m scripts.seed_shikshaa            # dry run, prints the plan
    venv/Scripts/python.exe -m scripts.seed_shikshaa --apply
    venv/Scripts/python.exe -m scripts.seed_shikshaa --apply --skip-rag   # no Gemini calls

Idempotent: re-running matches on natural keys and updates rather than duplicating. Safe to run
again after a partial failure.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal

# --- Configuration -------------------------------------------------------------------

SCHOOL_NAME = "Shikshaa Public School"
ACADEMIC_YEAR = "2026-27"
DOMAIN = "shikshaa.in"
PASSWORD = "1234567890"
"""One shared password across every seeded account. Correct for demo fixtures on a
throwaway school - it means any role can be logged into on camera without a password
manager - and wrong for anything else. See the module docstring."""

GRADES = [1, 2, 3]
SECTIONS = ["A", "B"]
STUDENTS_PER_CLASS = 5

SUBJECTS = [
    # (name, code, periods_per_week, lab_required)
    ("Mathematics", "MATH", 5, False),
    ("English", "ENG", 5, False),
    ("Science", "SCI", 4, True),
]
LAB_ROOM_TYPE = "lab"

EXTRA_SUBJECTS = [
    # (name, code, periods_per_week, lab_required, [teacher indices qualified])
    #
    # Subjects that EXIST and have qualified staff but are deliberately NOT timetabled: they
    # are absent from SUBJECTS above, so the solver never generates periods for them.
    #
    # Arts is here because only one teacher is qualified for it. Adding it to SUBJECTS with a
    # 15-period week would demand 15 x 6 classes = 90 periods from a single teacher against a
    # 26-period cap, and CP-SAT would correctly prove the whole timetable infeasible - taking
    # Mathematics, English and Science down with it. Qualify a second Arts teacher and lower
    # the period count before promoting it into SUBJECTS.
    ("Arts", None, 15, False, [6]),
]

TEACHER_COUNT = 8
TEACHER_SUBJECTS: dict[int, list[str]] = {
    # Every subject has >= 4 qualified teachers, so the solver routes rather than
    # having exactly one legal assignment per requirement.
    1: ["Mathematics", "Science"],
    2: ["Mathematics", "English"],
    3: ["English", "Science"],
    4: ["Mathematics"],
    5: ["Science"],
    6: ["English"],
    7: ["Mathematics", "English"],
    8: ["Science", "English"],
}
TEACHER_NAMES = {
    1: "Anjali Menon",
    2: "Rahul Verma",
    3: "Fatima Sheikh",
    4: "Vikram Iyer",
    5: "Deepa Krishnan",
    6: "Sanjay Bose",
    7: "Nithya Raman",
    8: "Imran Qureshi",
}
MAX_PERIODS_PER_WEEK = 26
"""Under the 5x7=35 ceiling, so the cap is a real constraint the solver must respect
without making the instance trivially infeasible."""

UNAVAILABLE_TEACHER_INDEX = 1
UNAVAILABLE_DAY = 4  # Friday, 0 = Monday
PERIODS_PER_DAY = 7
DAYS_PER_WEEK = 5

STUDENT_NAMES = [
    "Aditi Rao", "Kabir Malhotra", "Ishita Nair", "Arnav Joshi", "Meera Pillai",
    "Rohan Kulkarni", "Sara Khan", "Dhruv Bhatia", "Ananya Ghosh", "Yash Patel",
    "Tara Menon", "Aryan Desai", "Riya Chopra", "Neel Kapoor", "Diya Sharma",
    "Kian Reddy", "Naina Bose", "Veer Saxena", "Zoya Ahmed", "Advik Rana",
    "Myra Sinha", "Reyansh Dutta", "Anika Varma", "Shaurya Mehta", "Kiara Jain",
    "Aarav Bhat", "Pari Chandra", "Vivaan Shetty", "Saanvi Kaul", "Ayaan Farooq",
]

ROOMS = [
    ("Room 1", 35, "classroom"),
    ("Room 2", 35, "classroom"),
    ("Room 3", 35, "classroom"),
    ("Room 4", 35, "classroom"),
    ("Room 5", 35, "classroom"),
    ("Room 6", 35, "classroom"),
    ("Science Lab", 30, LAB_ROOM_TYPE),
]

# Attendance profiles, chosen against services/risk_scorer.py's real arithmetic so the
# nightly job produces a genuine spread instead of every student looking identical.
# "at_risk" lands below the 90% threshold; "healthy" sits comfortably above it.
ATTENDANCE_WEEKS = 4
PROFILE_CRITICAL = "critical"
PROFILE_AT_RISK = "at_risk"
PROFILE_WOBBLY = "wobbly"
PROFILE_HEALTHY = "healthy"

CRITICAL_CLASS_INDEX = 4
"""Grade 3 - A. Exactly one student in the school is scored HIGH rather than medium, and this
is where they sit - the same class the doubt threads and the Doubt Bot demo use, and the class
of p6's second child, so the parent portal shows a genuinely urgent flag rather than a mild one.

Needed because the arithmetic in services/risk_scorer.py does not reach `high` by accident:
score = attendance*0.50 + grades*0.35 + remarks*0.15 must exceed MEDIUM_RISK_MAX of 0.60.
An 'at_risk' student on ~65% attendance and ~41% grades scores about 0.39 - medium. Only a
genuinely struggling profile (~40% attendance, low-20s grades) crosses into high."""


@dataclass
class ClassSpec:
    grade: int
    section: str

    @property
    def name(self) -> str:
        return f"Grade {self.grade} - {self.section}"


CLASS_SPECS = [ClassSpec(g, s) for g in GRADES for s in SECTIONS]


def student_email(idx: int) -> str:
    return f"s{idx}@{DOMAIN}"


def teacher_email(idx: int) -> str:
    return f"t{idx}@{DOMAIN}"


def parent_email(idx: int) -> str:
    return f"p{idx}@{DOMAIN}"


ADMIN_EMAIL = f"admin@{DOMAIN}"
PRINCIPAL_EMAIL = f"principal@{DOMAIN}"


# --- Small helpers -------------------------------------------------------------------

def get_or_create(session: Session, model, defaults: dict | None = None, **natural_key):
    """Fetch by natural key or create. Returns (row, created)."""
    row = session.query(model).filter_by(**natural_key).one_or_none()
    if row is not None:
        return row, False
    row = model(**natural_key, **(defaults or {}))
    session.add(row)
    session.flush()
    return row, True


def note(counts: dict, key: str, n: int = 1) -> None:
    counts[key] = counts.get(key, 0) + n


def school_days_back(count: int, *, end: date) -> list[date]:
    """`count` weekdays ending at `end` inclusive, most recent last."""
    days: list[date] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


# --- Auth accounts -------------------------------------------------------------------

_AUTH_CACHE: dict[str, uuid.UUID] = {}


def _lookup_auth_id(email: str) -> uuid.UUID | None:
    """Find an existing Supabase Auth account by email.

    Same paging approach as seed_riverside_fixtures - the admin API has no
    get-user-by-email, so the list has to be walked. Results are cached because this
    script asks about ~46 addresses and each walk is a network round trip.
    """
    from app.services.supabase_admin import _new_client

    if email.lower() in _AUTH_CACHE:
        return _AUTH_CACHE[email.lower()]
    client = _new_client()
    page = 1
    while page <= 10:
        batch = client.auth.admin.list_users(page=page, per_page=1000)
        rows = batch if isinstance(batch, list) else getattr(batch, "users", [])
        if not rows:
            break
        for row in rows:
            addr = (row.email or "").lower()
            if addr:
                _AUTH_CACHE[addr] = uuid.UUID(str(row.id))
        page += 1
    return _AUTH_CACHE.get(email.lower())


def ensure_auth_account(*, email: str, full_name: str, role: str, counts: dict) -> uuid.UUID:
    """Create the Supabase Auth login, or adopt and re-password an existing one.

    GET-OR-CREATE, not create: a partially-completed earlier run leaves auth accounts behind,
    and failing on those would make this script un-rerunnable. Re-setting the password when
    adopting is what guarantees the printed credentials actually work, instead of silently
    depending on whatever an earlier run happened to use.
    """
    from app.services.supabase_admin import _new_client, create_auth_account

    existing = _lookup_auth_id(email)
    if existing is not None:
        _new_client().auth.admin.update_user_by_id(str(existing), {"password": PASSWORD})
        note(counts, "auth_adopted")
        return existing

    auth_id = create_auth_account(email=email, password=PASSWORD, full_name=full_name, role=role)
    _AUTH_CACHE[email.lower()] = auth_id
    note(counts, "auth_created")
    return auth_id


def ensure_user(session: Session, *, email: str, full_name: str, role: str,
                school_id: int, counts: dict, with_auth: bool = True):
    """The local `users` row, wired to a real login."""
    from app.models.role import Role
    from app.models.user import User

    role_row = session.query(Role).filter(Role.name == role).one()
    user = session.query(User).filter(User.email == email).one_or_none()

    auth_id = None
    if with_auth:
        auth_id = ensure_auth_account(email=email, full_name=full_name, role=role, counts=counts)

    if user is None:
        user = User(
            email=email,
            full_name=full_name,
            role_id=role_row.id,
            school_id=school_id,
            supabase_id=auth_id or uuid.uuid4(),
        )
        session.add(user)
        session.flush()
        note(counts, f"users_{role}")
    else:
        # Keep the local row pointed at the LIVE auth account. If an earlier run created the
        # login after the row, or the account was recreated, these drift and the person cannot
        # log in despite existing in both places.
        if auth_id is not None and user.supabase_id != auth_id:
            user.supabase_id = auth_id
        user.full_name = full_name
        user.school_id = school_id
        user.role_id = role_row.id
    return user


# --- Phase 1: school, master data, staff ---------------------------------------------

def seed_master_data(session: Session, counts: dict) -> dict:
    """School, subjects, rooms, staff, teacher qualifications, unavailability, classes."""
    from app.models.class_ import SchoolClass
    from app.models.school import School
    from app.models.subject import Subject
    from app.models.timetable import (
        Room,
        SubjectRoomRequirement,
        TeacherProfile,
        TeacherSubject,
        TeacherUnavailability,
    )

    school, created = get_or_create(session, School, name=SCHOOL_NAME)
    if created:
        note(counts, "school")
    print(f"  school: {SCHOOL_NAME} (id {school.id})")

    subjects: dict = {}
    for name, code, ppw, lab in SUBJECTS:
        subject, created = get_or_create(
            session, Subject, name=name, school_id=school.id,
            defaults={"code": code, "periods_per_week": ppw, "lab_required": lab},
        )
        subject.periods_per_week = ppw
        subject.lab_required = lab
        subject.code = code
        subjects[name] = subject
        if created:
            note(counts, "subjects")
        if lab:
            # Without this the solver's room-type constraint is never exercised.
            get_or_create(session, SubjectRoomRequirement, subject_id=subject.id,
                          defaults={"room_type": LAB_ROOM_TYPE})
    # Non-timetabled subjects: created and staffed, but never handed to the solver.
    for name, code, ppw, lab, teacher_indices in EXTRA_SUBJECTS:
        subject, created = get_or_create(
            session, Subject, name=name, school_id=school.id,
            defaults={"code": code, "periods_per_week": ppw, "lab_required": lab},
        )
        subjects[name] = subject
        if created:
            note(counts, "subjects")
    print(f"  subjects: {', '.join(n for n, *_ in [(k,) for k in subjects])}")

    rooms: list = []
    for name, capacity, room_type in ROOMS:
        room, created = get_or_create(session, Room, name=name, school_id=school.id,
                                      defaults={"capacity": capacity, "room_type": room_type})
        room.capacity = capacity
        room.room_type = room_type
        rooms.append(room)
        if created:
            note(counts, "rooms")
    labs = sum(1 for r in rooms if r.room_type == LAB_ROOM_TYPE)
    print(f"  rooms: {len(rooms)} ({labs} lab)")

    principal = ensure_user(session, email=PRINCIPAL_EMAIL, full_name="Lakshmi Subramanian",
                            role="principal", school_id=school.id, counts=counts)
    admin = ensure_user(session, email=ADMIN_EMAIL, full_name="Ravi Shankar",
                        role="admin", school_id=school.id, counts=counts)
    print(f"  principal: {PRINCIPAL_EMAIL} (id {principal.id})")
    print(f"  admin:     {ADMIN_EMAIL} (id {admin.id})")

    teachers: dict = {}
    for idx in range(1, TEACHER_COUNT + 1):
        teacher = ensure_user(session, email=teacher_email(idx), full_name=TEACHER_NAMES[idx],
                              role="teacher", school_id=school.id, counts=counts)
        teachers[idx] = teacher
        get_or_create(session, TeacherProfile, teacher_id=teacher.id,
                      defaults={"max_periods_per_week": MAX_PERIODS_PER_WEEK})
        for subject_name in TEACHER_SUBJECTS[idx]:
            get_or_create(session, TeacherSubject, teacher_id=teacher.id,
                          subject_id=subjects[subject_name].id)
    for name, _code, _ppw, _lab, teacher_indices in EXTRA_SUBJECTS:
        for idx in teacher_indices:
            get_or_create(session, TeacherSubject, teacher_id=teachers[idx].id,
                          subject_id=subjects[name].id)
            print(f"  {TEACHER_NAMES[idx]} also qualified for {name} (not timetabled)")

    print(f"  teachers: {TEACHER_COUNT}, qualified across {len(subjects)} subjects")

    # One teacher off all Friday, so the solver must route around a real human constraint
    # instead of every requirement having a trivially free slot.
    blocked = teachers[UNAVAILABLE_TEACHER_INDEX]
    for period in range(PERIODS_PER_DAY):
        get_or_create(session, TeacherUnavailability, teacher_id=blocked.id,
                      day_of_week=UNAVAILABLE_DAY, period_number=period,
                      academic_year=ACADEMIC_YEAR)
    print(f"  {TEACHER_NAMES[UNAVAILABLE_TEACHER_INDEX]} unavailable all Friday - real solver routing")

    # Classes. Each gets its own homeroom, and a DIFFERENT homeroom teacher, so "my classes"
    # resolves to something distinct per teacher.
    classes: list = []
    for i, spec in enumerate(CLASS_SPECS):
        school_class, created = get_or_create(
            session, SchoolClass, name=spec.name, academic_year=ACADEMIC_YEAR,
            school_id=school.id,
            defaults={
                "grade_level": spec.grade,
                "section": spec.section,
                "class_teacher_id": teachers[i + 1].id,
                "home_room_id": rooms[i].id,
            },
        )
        school_class.grade_level = spec.grade
        school_class.section = spec.section
        school_class.class_teacher_id = teachers[i + 1].id
        school_class.home_room_id = rooms[i].id
        classes.append(school_class)
        if created:
            note(counts, "classes")
    print(f"  classes: {', '.join(c.name for c in classes)}")

    return {"school": school, "subjects": subjects, "rooms": rooms, "teachers": teachers,
            "classes": classes, "principal": principal, "admin": admin}


# --- Phase 2: students, enrollments, parents -----------------------------------------

def seed_people(session: Session, base: dict, counts: dict) -> dict:
    """30 students across the 6 classes, plus parents - including one guardian whose two
    children are in DIFFERENT grades.

    That last detail is load-bearing for the demo: it is what makes the parent portal's child
    selector mean something, and what lets scoped announcements be shown rather than asserted
    (a Grade 3 notice must be visibly absent from the Grade 1 child's feed).
    """
    from app.models.enrollment import Enrollment

    school = base["school"]
    classes = base["classes"]

    students: list = []
    by_class: dict[int, list] = {}
    idx = 0
    for school_class in classes:
        roster = []
        for _ in range(STUDENTS_PER_CLASS):
            idx += 1
            student = ensure_user(session, email=student_email(idx),
                                 full_name=STUDENT_NAMES[idx - 1], role="student",
                                 school_id=school.id, counts=counts)
            get_or_create(session, Enrollment, student_id=student.id,
                          class_id=school_class.id, subject_id=None,
                          defaults={"is_primary": True})
            roster.append(student)
            students.append(student)
        by_class[school_class.id] = roster
        print(f"    {school_class.name}: {', '.join(s.full_name for s in roster)}")

    # Parents. p1..p5 each take one child from a different class; p6 is the multi-grade
    # guardian, deliberately given children in Grade 1 and Grade 3.
    from app.models.parent_student import ParentStudent

    # Roster index -> class: 0-4 = 1-A, 5-9 = 1-B, 10-14 = 2-A, 15-19 = 2-B,
    # 20-24 = 3-A, 25-29 = 3-B.
    parent_plan = [
        (1, "Sunita Rao", [students[0]]),          # 1-A
        (2, "Mahesh Malhotra", [students[1]]),     # 1-A, so 1-A has two linked guardians
        (3, "Leena Nair", [students[5]]),          # 1-B
        (4, "Farid Khan", [students[10]]),         # 2-A
        (5, "Gita Menon", [students[15]]),         # 2-B
        # THE MULTI-GRADE GUARDIAN: one child in Grade 1, one in Grade 3. This is what makes
        # the parent portal's child selector meaningful, and it is the account to sign in as
        # when showing that a Grade 3 announcement is ABSENT from the Grade 1 child's feed.
        (6, "Prakash Sharma", [students[4], students[20]]),  # 1-A and 3-A
    ]
    parents: list = []
    for pidx, name, children in parent_plan:
        parent = ensure_user(session, email=parent_email(pidx), full_name=name,
                             role="parent", school_id=school.id, counts=counts)
        for child in children:
            get_or_create(session, ParentStudent, parent_id=parent.id, student_id=child.id)
        parents.append(parent)
        kids = ", ".join(c.full_name for c in children)
        print(f"    {parent_email(pidx)} -> {kids}")

    return {"students": students, "by_class": by_class, "parents": parents}


# --- Phase 3: the timetable, solved for real -----------------------------------------

def seed_timetable(session: Session, base: dict, counts: dict) -> int:
    """Runs the REAL CP-SAT solver and persists its output.

    Not hand-written slots. The timetable is the single most impressive thing in this app and
    a demo of fabricated rows would be a lie - and worse, it would hide a genuinely broken
    solver. This mirrors what POST /timetable/generate does, including superseding any previous
    active generation for these classes rather than stacking on top of it.
    """
    from app.models.timetable import (
        Room,
        TeacherProfile,
        TeacherSubject,
        TeacherUnavailability,
        TimetableSlot,
    )
    from app.routers.timetable import _period_times
    from app.services.timetable_solver import (
        SolverRequirement,
        SolverRoom,
        SolverSubject,
        SolverTeacher,
        UnsolvableError,
        generate_timetable,
    )

    school = base["school"]
    classes = base["classes"]
    subjects = base["subjects"]
    rooms = base["rooms"]

    teacher_rows = list(base["teachers"].values())
    quals: dict[int, set[int]] = {}
    for row in session.query(TeacherSubject).filter(
        TeacherSubject.teacher_id.in_([t.id for t in teacher_rows])
    ):
        quals.setdefault(row.teacher_id, set()).add(row.subject_id)

    unavail: dict[int, set[tuple[int, int]]] = {}
    for row in session.query(TeacherUnavailability).filter(
        TeacherUnavailability.teacher_id.in_([t.id for t in teacher_rows]),
        TeacherUnavailability.academic_year == ACADEMIC_YEAR,
    ):
        unavail.setdefault(row.teacher_id, set()).add((row.day_of_week, row.period_number))

    caps = {
        p.teacher_id: p.max_periods_per_week
        for p in session.query(TeacherProfile).filter(
            TeacherProfile.teacher_id.in_([t.id for t in teacher_rows])
        )
    }

    solver_teachers = [
        SolverTeacher(
            id=t.id,
            subject_ids=frozenset(quals.get(t.id, set())),
            unavailable=frozenset(unavail.get(t.id, set())),
            max_periods_per_week=caps.get(t.id),
        )
        for t in teacher_rows
    ]
    solver_rooms = [SolverRoom(id=r.id, room_type=r.room_type) for r in rooms]
    solver_subjects = [
        SolverSubject(id=s.id, required_room_type=(LAB_ROOM_TYPE if s.lab_required else None))
        for s in subjects.values()
    ]
    requirements = [
        SolverRequirement(
            class_id=c.id,
            subject_id=subjects[name].id,
            periods_per_week=ppw,
            home_room_id=c.home_room_id,
        )
        for c in classes
        for name, _code, ppw, _lab in SUBJECTS
    ]

    total = sum(r.periods_per_week for r in requirements)
    print(f"  solving {len(requirements)} requirements ({total} periods) across "
          f"{len(classes)} classes, {len(solver_teachers)} teachers, {len(solver_rooms)} rooms")

    try:
        result = generate_timetable(
            teachers=solver_teachers,
            rooms=solver_rooms,
            subjects=solver_subjects,
            requirements=requirements,
            days=DAYS_PER_WEEK,
            periods_per_day=PERIODS_PER_DAY,
            time_limit_seconds=60.0,
        )
    except UnsolvableError as exc:
        print(f"  ! SOLVER PROVED INFEASIBLE: {exc}")
        print("    The config at the top of this script needs loosening - more teachers per "
              "subject, more rooms, or more periods per day.")
        raise

    class_ids = [c.id for c in classes]
    session.query(TimetableSlot).filter(
        TimetableSlot.class_id.in_(class_ids),
        TimetableSlot.academic_year == ACADEMIC_YEAR,
        TimetableSlot.is_active.is_(True),
    ).update({TimetableSlot.is_active: False}, synchronize_session=False)

    for slot in result.slots:
        start_time, end_time = _period_times(slot.period_number)
        session.add(
            TimetableSlot(
                day_of_week=slot.day_of_week,
                period_number=slot.period_number,
                start_time=start_time,
                end_time=end_time,
                subject_id=slot.subject_id,
                teacher_id=slot.teacher_id,
                class_id=slot.class_id,
                room_id=slot.room_id,
                academic_year=ACADEMIC_YEAR,
                is_active=True,
            )
        )
    session.flush()
    note(counts, "timetable_slots", len(result.slots))
    print(f"  solved: {len(result.slots)} slots persisted")
    return len(result.slots)


# --- Phase 4: attendance, remarks, gradebook -----------------------------------------

def _profile_for(index_in_class: int, class_index: int = -1) -> str:
    """One flagged and one wobbly student per class of 5; the rest healthy.

    Deliberate, not random: the risk demo needs a visible contrast between a flagged student and
    a healthy one in the SAME class, and a random spread cannot be relied on to produce it.
    The first student of CRITICAL_CLASS_INDEX is pushed all the way to high risk.
    """
    if index_in_class == 0:
        return PROFILE_CRITICAL if class_index == CRITICAL_CLASS_INDEX else PROFILE_AT_RISK
    if index_in_class == 1:
        return PROFILE_WOBBLY
    return PROFILE_HEALTHY


def _status_for(profile: str, day_index: int) -> str:
    """Attendance for one day, tuned against risk_scorer.py's 90% threshold."""
    if profile == PROFILE_CRITICAL:
        # ~40% present. Combined with low-20s grades this clears MEDIUM_RISK_MAX and the
        # scorer returns "high" - which is what puts urgent styling on screen.
        return "present" if day_index % 5 in (0, 1) else "absent"
    if profile == PROFILE_AT_RISK:
        # ~65% present - comfortably under the threshold, so the nightly job flags them.
        return "absent" if day_index % 3 == 0 else ("late" if day_index % 7 == 0 else "present")
    if profile == PROFILE_WOBBLY:
        # ~85% - under the threshold but less severe, giving medium alongside high.
        return "absent" if day_index % 7 == 0 else ("late" if day_index % 11 == 0 else "present")
    # ~97% - one absence across the window, so "healthy" is not suspiciously perfect.
    return "absent" if day_index == 3 else "present"


def seed_attendance(session: Session, base: dict, people: dict, counts: dict) -> int:
    """Real AttendanceRecord rows over the last few weeks, source="manual".

    Anchored on today rather than a pinned constant: unlike the Riverside fixtures, nothing here
    needs to line up with hand-written percentages in a checklist, so drift is not a hazard - and
    anchoring on today means the window always sits inside the scorer's 30-day lookback.
    """
    from app.models.attendance import AttendanceRecord

    days = school_days_back(ATTENDANCE_WEEKS * 5, end=date.today())
    written = 0
    for class_index, school_class in enumerate(base["classes"]):
        roster = people["by_class"][school_class.id]
        for i, student in enumerate(roster):
            profile = _profile_for(i, class_index)
            for d_index, day in enumerate(days):
                status = _status_for(profile, d_index)
                # SCOPED TO THIS SCRIPT'S OWN ROWS: source="manual" with no slot.
                #
                # Matching on (student, class, date) alone raised MultipleResultsFound as soon
                # as any REAL attendance existed - a CV capture writes a second row for the same
                # student and day, carrying source="cv" and a timetable_slot_id, and the
                # attendance_records unique constraint deliberately allows that (it includes
                # both columns). The seed must never adopt or overwrite a genuine CV row.
                row = (
                    session.query(AttendanceRecord)
                    .filter(
                        AttendanceRecord.student_id == student.id,
                        AttendanceRecord.class_id == school_class.id,
                        AttendanceRecord.date == day,
                        AttendanceRecord.source == "manual",
                        AttendanceRecord.timetable_slot_id.is_(None),
                    )
                    .one_or_none()
                )
                if row is None:
                    session.add(
                        AttendanceRecord(
                            student_id=student.id,
                            class_id=school_class.id,
                            date=day,
                            status=status,
                            source="manual",
                        )
                    )
                    written += 1
                else:
                    # Realign an existing row rather than skipping it, so a re-run converges on
                    # the intended pattern instead of preserving whatever was there.
                    row.status = status
    session.flush()
    note(counts, "attendance_records", written)
    print(f"  attendance: {written} records across {len(days)} school days "
          f"({days[0]} to {days[-1]})")
    return written


REMARKS_BY_PROFILE = {
    PROFILE_CRITICAL: [
        # WORDING MEASURED, NOT GUESSED. services/remark_sentiment.py scores these with VADER
        # and `risk = -avg_compound`, so the phrasing decides whether this student reaches
        # `high`. An earlier draft averaged only -0.12 because "unwilling to attempt work even
        # with one-to-one SUPPORT" scores POSITIVE (+0.40) and "parents have not responded" is
        # neutral - so the remark component contributed nothing and the flag stayed medium.
        # These three average about -0.86, which is what carries the score past
        # MEDIUM_RISK_MAX (0.60) on top of 40% attendance and 23% grades.
        ("Very worrying decline. Refuses to work, disruptive when pushed, and failing badly.", "behavioral"),
        ("Serious concern: hostile to staff, no work submitted at all, and hopelessly behind.", "behavioral"),
        ("I am deeply worried. She is miserable, isolated and failing every single subject.", "behavioral"),
    ],
    PROFILE_AT_RISK: [
        ("Missed three classes this fortnight and has not caught up on the worksheets.", "behavioral"),
        ("Quiet and disengaged in class; struggles to start independent work.", "academic"),
    ],
    PROFILE_WOBBLY: [
        ("Homework has been late twice this month, though the work itself is sound.", "academic"),
    ],
    PROFILE_HEALTHY: [
        ("Consistently prepared and helps classmates without being asked.", "appreciation"),
    ],
}


def seed_remarks(session: Session, base: dict, people: dict, counts: dict) -> int:
    """Teacher remarks with genuinely mixed sentiment.

    The sentiment matters, not just the text: services/remark_sentiment.py scores these and the
    result is 15% of the risk signal. Uniformly positive remarks would leave the scorer with no
    remark contribution to show.
    """
    from app.models.remark import Remark

    written = 0
    pruned = 0
    for class_index, school_class in enumerate(base["classes"]):
        author_id = school_class.class_teacher_id
        roster = people["by_class"][school_class.id]
        for i, student in enumerate(roster):
            wanted = REMARKS_BY_PROFILE[_profile_for(i, class_index)]
            keep = {text for text, _tag in wanted}
            # PRUNE BY PROVENANCE, not by matching against the current config's strings.
            #
            # Matching strings only prunes wording this script still knows about, so an earlier
            # DRAFT's remarks survive - which is exactly what happened: a retuned critical
            # profile left the old texts in place, the sentiment average landed between the two
            # sets (-0.51 instead of -0.86), and the flag stayed one notch below `high` with no
            # visible cause. Anything the class teacher authored for a seeded student that is not
            # in the current set is this script's own leftover, so it goes.
            #
            # Consequence worth knowing: a remark YOU type as the class teacher on camera is
            # removed by the next run of this script. That is the right trade for a demo school -
            # convergence matters more than preserving ad-hoc rows.
            stale = (
                session.query(Remark)
                .filter(Remark.student_id == student.id,
                        Remark.author_id == author_id,
                        Remark.content.notin_(sorted(keep)))
                .all()
            )
            for row in stale:
                session.delete(row)
                pruned += 1
            session.flush()
            for content, tag in wanted:
                existing = (
                    session.query(Remark)
                    .filter(Remark.student_id == student.id, Remark.content == content)
                    .one_or_none()
                )
                if existing is None:
                    session.add(
                        Remark(
                            school_id=base["school"].id,
                            author_id=author_id,
                            student_id=student.id,
                            class_id=school_class.id,
                            content=content,
                            sentiment_tag=tag,
                        )
                    )
                    written += 1
    session.flush()
    note(counts, "remarks", written)
    extra = f", {pruned} stale pruned" if pruned else ""
    print(f"  remarks: {written} written{extra} (sentiment feeds 15% of the risk score)")
    return written


def seed_gradebook(session: Session, base: dict, people: dict, counts: dict) -> int:
    """Marks for every student in every subject, so term averages and GPAs are real.

    Scores track the attendance profile, because a report card where the struggling student has
    the best marks reads as obviously synthetic.
    """
    from app.models.gradebook import GradebookEntry

    score_by_profile = {
        PROFILE_CRITICAL: [18, 24, 21],
        PROFILE_AT_RISK: [38, 44, 41],
        PROFILE_WOBBLY: [58, 63, 61],
        PROFILE_HEALTHY: [82, 88, 79],
    }
    assessments = [("assignment", 1.0), ("quiz", 1.0), ("midterm", 1.0)]

    written = 0
    for class_index, school_class in enumerate(base["classes"]):
        roster = people["by_class"][school_class.id]
        for i, student in enumerate(roster):
            base_scores = score_by_profile[_profile_for(i, class_index)]
            for s_index, (subject_name, _c, _p, _l) in enumerate(SUBJECTS):
                subject = base["subjects"][subject_name]
                for a_index, (kind, weight) in enumerate(assessments):
                    # Vary by subject and assessment so subject breakdowns differ per row
                    # instead of every subject showing an identical number.
                    score = min(99, max(5, base_scores[a_index] + (s_index * 4) - (a_index * 2)))
                    existing = (
                        session.query(GradebookEntry)
                        .filter(
                            GradebookEntry.student_id == student.id,
                            GradebookEntry.subject_id == subject.id,
                            GradebookEntry.term == "Term 1",
                            GradebookEntry.assessment_type == kind,
                            GradebookEntry.assessment_id.is_(None),
                        )
                        .one_or_none()
                    )
                    if existing is None:
                        session.add(
                            GradebookEntry(
                                school_id=base["school"].id,
                                student_id=student.id,
                                subject_id=subject.id,
                                class_id=school_class.id,
                                term="Term 1",
                                assessment_type=kind,
                                score=float(score),
                                max_score=100.0,
                                weight=weight,
                            )
                        )
                        written += 1
                    else:
                        existing.score = float(score)
    session.flush()
    note(counts, "gradebook_entries", written)
    print(f"  gradebook: {written} entries ({len(SUBJECTS)} subjects x "
          f"{len(assessments)} assessments x 30 students)")
    return written


# --- Phase 5: report cards -----------------------------------------------------------

def seed_report_cards(session: Session, people: dict, counts: dict) -> int:
    """Generated by the real service, not hand-built.

    services/report_card_service.py is what assembles grades + attendance + remarks into the
    snapshot, so calling it is the only way the seeded cards match what the Generate button
    produces. Only the two flagged students per class get one pre-generated - the demo generates
    the rest live on camera, and 30 pre-made cards would make that beat pointless.
    """
    from app.services.report_card_service import generate_single_report_card

    written = 0
    for roster in people["by_class"].values():
        for student in roster[:2]:  # the at-risk and wobbly students
            generate_single_report_card(session, student.id, "Term 1", ACADEMIC_YEAR)
            written += 1
    session.flush()
    note(counts, "report_cards", written)
    print(f"  report cards: {written} pre-generated (the rest are generated live in the demo)")
    return written


# --- Phase 6: classroom activity -----------------------------------------------------

def seed_classroom_activity(session: Session, base: dict, people: dict, counts: dict) -> None:
    """Assignments, quizzes with real questions and attempts, library loans, syllabus plans.

    Deadlines are spread across overdue / today / this week deliberately: the homework calendar
    groups by exactly those buckets, and a demo where every deadline lands in one bucket shows
    nothing.
    """
    from app.models.assignment import Assignment
    from app.models.classroom import Classroom
    from app.models.library import LibraryItem, LibraryLoan
    from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
    from app.models.syllabus import SyllabusCheckpoint, SyllabusPlan

    school = base["school"]
    now = datetime.now(timezone.utc)

    # --- Classrooms: one per class, for its homeroom teacher's main subject ----------
    for i, school_class in enumerate(base["classes"]):
        subject_name = SUBJECTS[i % len(SUBJECTS)][0]
        get_or_create(
            session, Classroom, class_id=school_class.id,
            subject_id=base["subjects"][subject_name].id,
            defaults={
                "school_id": school.id,
                "class_name": school_class.name,
                "teacher_id": school_class.class_teacher_id,
            },
        )
        note(counts, "classrooms")

    # --- Assignments: one overdue, one due today, one later, per class ---------------
    offsets = [
        (-3, "Fractions worksheet 2"),
        (0, "Reading comprehension: The Kite"),
        (4, "Science: plants and sunlight"),
    ]
    for i, school_class in enumerate(base["classes"]):
        for d_offset, title in offsets:
            subject = base["subjects"][SUBJECTS[i % len(SUBJECTS)][0]]
            existing = (
                session.query(Assignment)
                .filter(Assignment.class_id == school_class.id, Assignment.title == title)
                .one_or_none()
            )
            if existing is None:
                session.add(
                    Assignment(
                        school_id=school.id,
                        class_id=school_class.id,
                        subject_id=subject.id,
                        teacher_id=school_class.class_teacher_id,
                        title=title,
                        description="Complete all questions and show your working.",
                        deadline=now + timedelta(days=d_offset),
                        max_marks=20.0,
                    )
                )
                note(counts, "assignments")
    session.flush()

    # --- Quizzes: real questions, so one can actually be sat on camera --------------
    QUESTIONS = [
        ("What is 1/2 + 1/4?", "1/6", "3/4", "2/6", "1/8", "b"),
        ("Which of these is a proper fraction?", "5/3", "7/7", "2/5", "9/4", "c"),
        ("What is 3/5 of 20?", "12", "10", "15", "8", "a"),
    ]
    for i, school_class in enumerate(base["classes"]):
        subject = base["subjects"][SUBJECTS[i % len(SUBJECTS)][0]]
        quiz, created = get_or_create(
            session, Quiz, class_id=school_class.id, title=f"{school_class.name} - Fractions check",
            defaults={
                "school_id": school.id,
                "subject_id": subject.id,
                "teacher_id": school_class.class_teacher_id,
                "duration_minutes": 10,
                "available_from": now - timedelta(days=1),
                "available_until": now + timedelta(days=6),
            },
        )
        if created:
            note(counts, "quizzes")
            for q_index, (text, a, b, c, d, correct) in enumerate(QUESTIONS, start=1):
                session.add(
                    QuizQuestion(
                        quiz_id=quiz.id, question_text=text,
                        option_a=a, option_b=b, option_c=c, option_d=d,
                        correct_option=correct, marks=1.0, order_index=q_index,
                    )
                )
        session.flush()

        # One completed attempt per class, so results screens are not empty - but leave the
        # rest unattempted so a student can genuinely take one during the recording.
        roster = people["by_class"][school_class.id]
        get_or_create(
            session, QuizAttempt, quiz_id=quiz.id, student_id=roster[-1].id,
            defaults={
                "score": 2.0, "total_marks": 3.0, "status": "submitted",
                "started_at": now - timedelta(hours=3),
                "submitted_at": now - timedelta(hours=2, minutes=48),
            },
        )
        note(counts, "quiz_attempts")

    # --- Library ---------------------------------------------------------------------
    BOOKS = [
        ("Panchatantra Tales", "Vishnu Sharma", "Literature", "book", 4),
        ("Fun with Numbers", "R. Balakrishnan", "Mathematics", "book", 3),
        ("My Body, My Health", "Sunita Rao", "Science", "book", 3),
        ("Grade 3 Maths Past Papers 2025", None, "Mathematics", "past_paper", 5),
        ("Young Scientist Monthly", None, "Science", "journal", 2),
    ]
    items = []
    for title, author, category, kind, copies in BOOKS:
        item, created = get_or_create(
            session, LibraryItem, school_id=school.id, title=title,
            defaults={"author": author, "category": category, "type": kind,
                      "total_copies": copies, "available_copies": copies},
        )
        items.append(item)
        if created:
            note(counts, "library_items")
    session.flush()

    # A few live loans, one deliberately overdue so the overdue styling has something to show.
    loans = [
        (items[0], people["students"][0], -4),   # overdue
        (items[1], people["students"][6], 9),
        (items[3], people["students"][21], 12),
    ]
    for item, student, due_offset in loans:
        existing = (
            session.query(LibraryLoan)
            .filter(LibraryLoan.library_item_id == item.id,
                    LibraryLoan.student_id == student.id)
            .one_or_none()
        )
        if existing is None:
            session.add(
                LibraryLoan(
                    school_id=school.id, library_item_id=item.id, student_id=student.id,
                    issued_at=now - timedelta(days=14),
                    due_date=now + timedelta(days=due_offset),
                    status="active",
                )
            )
            item.available_copies = max(0, item.available_copies - 1)
            note(counts, "library_loans")
    session.flush()

    # --- Syllabus plans: one per class/subject, deliberately at different paces ------
    term_start = date.today() - timedelta(days=60)
    term_end = date.today() + timedelta(days=60)
    for i, school_class in enumerate(base["classes"]):
        for s_index, (subject_name, _c, _p, _l) in enumerate(SUBJECTS):
            subject = base["subjects"][subject_name]
            plan, created = get_or_create(
                session, SyllabusPlan, class_id=school_class.id, subject_id=subject.id,
                academic_year=ACADEMIC_YEAR,
                defaults={
                    "total_units": 12,
                    "term_start_date": term_start,
                    "term_end_date": term_end,
                    "created_by": school_class.class_teacher_id,
                },
            )
            if created:
                note(counts, "syllabus_plans")
            session.flush()
            # Halfway through the term. Logging fewer than 6 checkpoints puts a plan BEHIND,
            # more puts it AHEAD - so the drift column shows a real spread rather than one value.
            logged = {0: 3, 1: 6, 2: 8}[s_index]
            existing = (
                session.query(SyllabusCheckpoint)
                .filter(SyllabusCheckpoint.plan_id == plan.id).count()
            )
            for seq in range(existing + 1, logged + 1):
                session.add(
                    SyllabusCheckpoint(
                        plan_id=plan.id,
                        topic_label=f"Unit {seq}",
                        sequence_number=seq,
                        logged_by=school_class.class_teacher_id,
                    )
                )
                note(counts, "syllabus_checkpoints")
    session.flush()
    print(f"  classroom activity: {counts.get('assignments', 0)} assignments, "
          f"{counts.get('quizzes', 0)} quizzes, {counts.get('library_items', 0)} library items, "
          f"{counts.get('syllabus_plans', 0)} syllabus plans")


# --- Phase 7: fees, announcements, exams, leave --------------------------------------

def seed_operations(session: Session, base: dict, people: dict, counts: dict) -> None:
    """Fees, announcements (school-wide AND grade-scoped), exams with seating, a pending leave."""
    from app.models.announcement import Announcement
    from app.models.exams import Exam, SeatingAssignment
    from app.models.fees import FeeRecord, FeeSchedule
    from app.models.staffing import LeaveRequest

    school = base["school"]
    today = date.today()

    # --- Fees: one schedule already due, one upcoming -------------------------------
    schedules = []
    for fee_type, amount, due_offset in [("tuition", 12000.0, -6), ("transport", 3000.0, 20)]:
        schedule, created = get_or_create(
            session, FeeSchedule, school_id=school.id, academic_year=ACADEMIC_YEAR,
            fee_type=fee_type,
            defaults={"amount": amount, "due_date": today + timedelta(days=due_offset)},
        )
        schedules.append(schedule)
        if created:
            note(counts, "fee_schedules")
    session.flush()

    # Records for every student. The tuition one is past due, so a slice of them are genuinely
    # overdue rather than the state being faked with a status column.
    for schedule in schedules:
        for i, student in enumerate(people["students"]):
            record, created = get_or_create(
                session, FeeRecord, student_id=student.id, fee_schedule_id=schedule.id,
                defaults={
                    "amount_due": schedule.amount,
                    "due_date": schedule.due_date,
                    "amount_paid": 0.0,
                    "status": "pending",
                },
            )
            if created:
                note(counts, "fee_records")
            # Two thirds have paid the tuition; the rest are outstanding and past due.
            if schedule.fee_type == "tuition" and i % 3 != 0:
                record.amount_paid = record.amount_due
                record.status = "paid"
    session.flush()

    # --- Announcements: the scoped-delivery demo needs BOTH kinds -------------------
    admin = base["admin"]
    grade3_classes = [c for c in base["classes"] if c.grade_level == 3]
    announcements = [
        ("school", None, "Annual Day on 12 September",
         "Rehearsals begin next week. All classes will finish at 1pm on rehearsal days.",
         "general", "important"),
        ("class", grade3_classes[0].id, "Grade 3 science field trip",
         "We visit the Botanical Gardens on Friday. Please return the consent form by Wednesday.",
         "academic", "important"),
    ]
    for scope_type, class_id, title, body, category, priority in announcements:
        existing = (
            session.query(Announcement)
            .filter(Announcement.school_id == school.id, Announcement.title == title)
            .one_or_none()
        )
        if existing is None:
            session.add(
                Announcement(
                    school_id=school.id, author_id=admin.id, scope_type=scope_type,
                    scope_class_id=class_id, title=title, body=body,
                    category=category, priority=priority,
                )
            )
            note(counts, "announcements")
    session.flush()

    # --- Exams + seating -------------------------------------------------------------
    exam_room = next(r for r in base["rooms"] if r.room_type == LAB_ROOM_TYPE)
    # EVERY class, not a slice. An earlier version did the first three, which left Grade 3 - A -
    # the class the whole demo is built around - with an empty Exams tab on the homework calendar.
    for school_class in base["classes"]:
        subject = base["subjects"]["Mathematics"]
        exam, created = get_or_create(
            session, Exam, school_id=school.id, class_id=school_class.id,
            subject_id=subject.id, academic_year=ACADEMIC_YEAR,
            defaults={
                "exam_date": today + timedelta(days=9),
                "start_time": time(10, 0),
                "end_time": time(11, 30),
                "exam_type": "unit_test",
                "total_marks": 40,
            },
        )
        if created:
            note(counts, "exams")
        session.flush()
        for seat_no, student in enumerate(people["by_class"][school_class.id], start=1):
            get_or_create(
                session, SeatingAssignment, exam_id=exam.id, student_id=student.id,
                defaults={"room_id": exam_room.id, "seat_no": seat_no},
            )
            note(counts, "seating_assignments")

    # --- One pending leave request, for the substitute-suggestion beat --------------
    # Deliberately a FUTURE Monday: the staffing screen only proposes substitutes for upcoming
    # absences, so a past date would make the demo's payoff beat show nothing.
    days_ahead = (7 - today.weekday()) % 7 or 7
    leave_day = today + timedelta(days=days_ahead)
    blocked_teacher = base["teachers"][UNAVAILABLE_TEACHER_INDEX]
    existing = (
        session.query(LeaveRequest)
        .filter(LeaveRequest.teacher_id == blocked_teacher.id,
                LeaveRequest.start_date == leave_day)
        .one_or_none()
    )
    if existing is None:
        session.add(
            LeaveRequest(
                teacher_id=blocked_teacher.id,
                start_date=leave_day,
                end_date=leave_day,
                reason="Medical appointment",
                status="pending",
            )
        )
        note(counts, "leave_requests")
    session.flush()
    print(f"  operations: {counts.get('fee_records', 0)} fee records, "
          f"{counts.get('announcements', 0)} announcements, {counts.get('exams', 0)} exams, "
          f"1 pending leave on {leave_day}")


# --- Phase 8: the RAG corpus ---------------------------------------------------------

RESOURCE_TEXTS = {
    1: [
        ("Grade 1 Mathematics - Numbers to 100", "Mathematics", "Unit 1", """
Numbers to 100.
Counting forward: we count 1, 2, 3 up to 100. Counting backward starts at a bigger number
and goes down, for example 20, 19, 18.
Tens and ones: the number 34 has 3 tens and 4 ones. The number 70 has 7 tens and 0 ones.
Comparing numbers: 45 is greater than 39 because 4 tens is more than 3 tens.
When the tens are the same we compare the ones: 62 is less than 67.
Skip counting: counting in twos gives 2, 4, 6, 8, 10. Counting in fives gives 5, 10, 15, 20.
Counting in tens gives 10, 20, 30, 40, 50.
Adding to ten: 6 + 4 = 10, and 7 + 3 = 10. These are called number bonds to ten.
"""),
        ("Grade 1 English - Naming Words", "English", "Unit 1", """
Naming words, also called nouns.
A naming word tells us the name of a person, a place, an animal or a thing.
Person: teacher, sister, doctor, farmer.
Place: school, market, garden, hospital.
Animal: dog, elephant, parrot, cow.
Thing: chair, pencil, bottle, kite.
One and many: we add s to make many. One book becomes two books. One cup becomes six cups.
Some words change completely. One child becomes many children. One man becomes many men.
One mouse becomes many mice. One tooth becomes many teeth.
"""),
        ("Grade 1 Science - Living and Non-Living", "Science", "Unit 1", """
Living and non-living things.
Living things grow, need food and water, breathe, move on their own and produce young ones.
Plants and animals are living things.
Non-living things do not grow, do not need food and cannot move by themselves.
A stone, a chair and a bicycle are non-living things.
Plants need sunlight, water, air and soil to grow. A plant kept in a dark cupboard turns pale
and weak because it cannot make food without sunlight.
Animals need food, water, air and shelter.
"""),
    ],
    2: [
        ("Grade 2 Mathematics - Addition and Subtraction", "Mathematics", "Unit 2", """
Addition and subtraction up to 1000.
Adding with carrying: to add 47 and 38, first add the ones, 7 + 8 = 15. Write 5 in the ones
place and carry 1 to the tens. Then 4 + 3 + 1 = 8. The answer is 85.
Subtracting with borrowing: to subtract 19 from 52, the ones digit 2 is smaller than 9, so we
borrow one ten. 12 - 9 = 3, then 4 - 1 = 3. The answer is 33.
Checking an answer: addition and subtraction are opposite operations. If 85 - 38 = 47, then
47 + 38 must equal 85.
Word problems: read the question twice, decide whether things are being joined or taken away,
then write the number sentence before you calculate.
"""),
        ("Grade 2 English - Sentences and Punctuation", "English", "Unit 2", """
Sentences and punctuation.
A sentence begins with a capital letter and ends with a full stop, a question mark or an
exclamation mark.
A telling sentence ends with a full stop: The bus is late.
An asking sentence ends with a question mark: Where is my bag?
A strong feeling sentence ends with an exclamation mark: What a beautiful garden!
Commas separate items in a list: I bought apples, bananas, mangoes and grapes.
Every sentence needs a naming part and an action part. In "The dog barked loudly", the naming
part is the dog and the action part is barked loudly.
"""),
        ("Grade 2 Science - Plants Around Us", "Science", "Unit 2", """
Plants around us.
Parts of a plant: roots, stem, leaves, flowers and fruit.
Roots hold the plant in the soil and take up water and minerals.
The stem carries water from the roots to the leaves and holds the plant upright.
Leaves make food for the plant using sunlight, water and air. This is called photosynthesis.
Flowers make seeds, and seeds grow into new plants.
Types of plants: herbs are small with soft stems, like mint. Shrubs are bushy with many woody
stems, like rose. Trees are tall with one thick woody trunk, like mango and neem.
Some plants climb using support and are called climbers, like the money plant.
"""),
    ],
    3: [
        ("Grade 3 Mathematics - Fractions", "Mathematics", "Unit 3", """
Fractions.
A fraction shows equal parts of a whole. In the fraction 3/4, the number below the line is the
denominator and tells how many equal parts the whole is divided into. The number above the line
is the numerator and tells how many parts we are talking about.
Half means one of two equal parts and is written 1/2. A quarter means one of four equal parts
and is written 1/4. Three quarters is written 3/4.
Adding fractions with the same denominator: add only the numerators and keep the denominator.
So 1/5 + 2/5 = 3/5.
Adding a half and a quarter: first make the denominators the same. One half is the same as two
quarters, so 1/2 + 1/4 = 2/4 + 1/4 = 3/4.
Comparing fractions with the same denominator: the one with the bigger numerator is larger, so
5/8 is greater than 3/8.
A proper fraction has a numerator smaller than its denominator, like 2/5.
Finding a fraction of a number: 3/5 of 20 means divide 20 by 5 to get 4, then multiply by 3 to
get 12.
"""),
        ("Grade 3 English - Verbs and Tenses", "English", "Unit 3", """
Verbs and tenses.
A verb is an action word. Run, eat, write and think are all verbs.
The present tense tells what is happening now: She writes a letter.
The past tense tells what already happened: She wrote a letter yesterday.
The future tense tells what will happen: She will write a letter tomorrow.
Most verbs add ed for the past tense: walk becomes walked, jump becomes jumped.
Some verbs change completely: go becomes went, eat becomes ate, see becomes saw, come became
came, and take becomes took.
Helping verbs like is, am, are, was and were work with the main verb: They are playing outside.
"""),
        ("Grade 3 Science - Water and Its Forms", "Science", "Unit 3", """
Water and its forms.
Water exists in three forms: solid ice, liquid water and gas called water vapour.
Melting: ice becomes water when it is heated.
Freezing: water becomes ice when it is cooled below zero degrees.
Evaporation: water becomes water vapour when it is heated. Puddles dry up in the sun because
the water evaporates.
Condensation: water vapour becomes water again when it is cooled. Water droplets appear on the
outside of a cold glass because vapour in the air condenses on it.
The water cycle: the sun heats water in oceans and lakes, it evaporates and rises, it condenses
into clouds high up where the air is cold, and it falls back as rain. This repeats forever.
Saving water: close taps, fix leaks and reuse water where you can.
"""),
    ],
}


def _make_pdf(title: str, body: str) -> bytes:
    """A genuine, minimal, text-extractable one-page PDF.

    Hand-built rather than pulled from a library so this script adds no dependency. The text is
    real page content, not metadata, which is what matters: services/ingestion.py extracts and
    chunks it, so a PDF whose text was not extractable would produce an empty corpus and the
    Doubt Bot would have nothing to cite.
    """
    lines = [f"({title}) Tj", "T*", "T*"]
    for raw in body.strip().splitlines():
        text = raw.strip().replace("\\", "").replace("(", "[").replace(")", "]")
        if not text:
            lines.append("T*")
            continue
        # Wrap so long lines stay on the page rather than running off the right edge.
        while len(text) > 88:
            cut = text.rfind(" ", 0, 88) or 88
            lines.append(f"({text[:cut]}) Tj")
            lines.append("T*")
            text = text[cut:].lstrip()
        lines.append(f"({text}) Tj")
        lines.append("T*")

    stream = "BT\n/F1 11 Tf\n14 TL\n40 780 Td\n" + "\n".join(lines) + "\nET"
    stream_bytes = stream.encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream_bytes)).encode() + b" >>\nstream\n" + stream_bytes + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body_bytes in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body_bytes + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def seed_rag_corpus(session: Session, base: dict, counts: dict) -> int:
    """Uploads real PDFs and ingests them, so the Doubt Bot has a corpus that predates the demo.

    REALLY uploaded and REALLY embedded - this calls services/supabase_admin.upload_resource_file
    and services/ingestion.ingest_resource, the same functions POST /resources/upload uses. That
    means Gemini embedding calls and Supabase Storage writes. Grade-wide (class_id=None), which
    is the scope every RAG retrieval path filters on.
    """
    from app.models.resource import Resource
    from app.services.ingestion import ingest_resource
    from app.services.supabase_admin import upload_resource_file

    school = base["school"]
    uploader = base["teachers"][1]
    total_chunks = 0

    for grade, entries in RESOURCE_TEXTS.items():
        for title, subject_name, unit, text in entries:
            subject = base["subjects"][subject_name]
            existing = (
                session.query(Resource)
                .filter(Resource.school_id == school.id, Resource.title == title)
                .one_or_none()
            )
            if existing is not None and existing.indexed_at is not None:
                print(f"    already indexed: {title}")
                continue

            pdf = _make_pdf(title, text)
            slug = title.lower().replace(" ", "-").replace("/", "-")
            path = f"{school.id}/grade-{grade}/{slug}.pdf"
            stored = upload_resource_file(path=path, data=pdf, content_type="application/pdf")

            if existing is None:
                resource = Resource(
                    school_id=school.id,
                    grade_level=grade,
                    class_id=None,  # grade-wide: the scope bot retrieval actually uses
                    subject_id=subject.id,
                    title=title,
                    description=f"{subject_name} notes for Grade {grade}, {unit}.",
                    unit=unit,
                    file_url=stored,
                    mime_type="application/pdf",
                    file_size=len(pdf),
                    uploaded_by=uploader.id,
                )
                session.add(resource)
                session.flush()
                note(counts, "resources")
            else:
                resource = existing
                resource.file_url = stored
                resource.file_size = len(pdf)

            chunks = ingest_resource(session, resource.id)
            session.commit()  # commit per resource: embedding is slow and costs money, so a
                              # failure on document 7 must not discard the first six
            total_chunks += chunks
            note(counts, "kb_chunks", chunks)
            print(f"    ingested {title}: {chunks} chunks")

    print(f"  RAG corpus: {total_chunks} chunks across {sum(len(v) for v in RESOURCE_TEXTS.values())} documents")
    return total_chunks


# --- Phase 9: doubt threads ----------------------------------------------------------

def seed_doubts(session: Session, base: dict, people: dict, counts: dict, *, skip_rag: bool) -> None:
    """A few open doubts, plus one VERIFIED answer that really enters the corpus.

    The verified one goes through services/ingestion.ingest_verified_doubt_answer - the same call
    PUT /threads/{id}/verify makes - so the demo's claim that a verified answer joins the
    grade-wide knowledge base is demonstrably true rather than asserted.
    """
    from app.models.doubt import DoubtThread, ThreadReply

    school = base["school"]
    grade3a = next(c for c in base["classes"] if c.grade_level == 3 and c.section == "A")
    roster = people["by_class"][grade3a.id]
    teacher_id = grade3a.class_teacher_id

    threads = [
        ("Why do we flip the second fraction when dividing?",
         "I can do the steps but I do not understand why it works.",
         roster[2], None),
        ("How do I know if a fraction is proper?",
         "Is 7/7 a proper fraction or not? My friend says it is.",
         roster[3], None),
        ("What makes water disappear from a puddle?",
         "The puddle outside our class dried up by lunch and I want to know where it went.",
         roster[4],
         "The water evaporated. The sun heats the water in the puddle and it turns into water "
         "vapour, which is water in gas form, and rises into the air. It has not disappeared - "
         "it is now part of the air around us, and it will fall again as rain when it cools and "
         "condenses. That whole journey is called the water cycle."),
    ]

    for title, body, author, verified_answer in threads:
        thread, created = get_or_create(
            session, DoubtThread, school_id=school.id, class_id=grade3a.id, title=title,
            defaults={
                "subject_id": base["subjects"]["Science" if "water" in title.lower() else "Mathematics"].id,
                "author_id": author.id,
                "body": body,
            },
        )
        if created:
            note(counts, "doubt_threads")
        session.flush()

        if verified_answer is None:
            continue

        reply = (
            session.query(ThreadReply)
            .filter(ThreadReply.thread_id == thread.id, ThreadReply.author_id == teacher_id)
            .one_or_none()
        )
        if reply is None:
            reply = ThreadReply(thread_id=thread.id, author_id=teacher_id, body=verified_answer)
            session.add(reply)
            session.flush()
            note(counts, "thread_replies")

        if thread.verified_reply_id == reply.id:
            continue
        thread.verified_reply_id = reply.id
        if skip_rag:
            print("    verified answer marked, ingestion skipped (--skip-rag)")
            continue
        from app.services.ingestion import ingest_verified_doubt_answer

        written = ingest_verified_doubt_answer(session, thread.id)
        session.commit()
        note(counts, "kb_chunks", written)
        print(f"    verified answer ingested: {written} chunk(s) into the Grade 3 corpus")

    session.flush()
    print(f"  doubts: {counts.get('doubt_threads', 0)} threads, 1 with a verified answer")


# --- Phase 10: risk flags, by the real scorer ----------------------------------------

def score_risk(session: Session, base: dict, counts: dict) -> dict:
    """Runs the actual nightly job.

    Not hand-written flags. run_nightly_scoring reads the attendance and remarks seeded above,
    scores them through services/risk_scorer.py and writes the reasons itself - so the reason
    strings on screen are the model's own output, and the demo's claim about the weighting is
    checkable rather than decorative.
    """
    from scripts.run_nightly_risk_scoring import run_nightly_scoring

    result = run_nightly_scoring(session, base["school"].id, ACADEMIC_YEAR)
    session.commit()
    for key, value in result.items():
        note(counts, f"risk_{key}", value if isinstance(value, int) else 0)
    print(f"  risk scoring: {result}")
    return result


# --- Summary -------------------------------------------------------------------------

def print_summary(session: Session, base: dict, people: dict, counts: dict) -> None:
    from sqlalchemy import text

    school = base["school"]
    print()
    print("=" * 78)
    print(f"  {SCHOOL_NAME}  (school_id {school.id})")
    print("=" * 78)

    print("\n  LOGINS - one shared password for every account below")
    print(f"  password: {PASSWORD}")
    print()
    print(f"    principal   {PRINCIPAL_EMAIL}")
    print(f"    admin       {ADMIN_EMAIL}")
    print(f"    teachers    t1..t{TEACHER_COUNT}@{DOMAIN}")
    for idx in range(1, TEACHER_COUNT + 1):
        homeroom = next((c.name for c in base["classes"]
                         if c.class_teacher_id == base["teachers"][idx].id), "floating")
        subjects = "/".join(TEACHER_SUBJECTS[idx])
        print(f"                  t{idx}: {TEACHER_NAMES[idx]:<18} {subjects:<24} {homeroom}")
    print(f"    students    s1..s{len(people['students'])}@{DOMAIN}")
    for school_class in base["classes"]:
        roster = people["by_class"][school_class.id]
        emails = ", ".join(s.email.split("@")[0] for s in roster)
        print(f"                  {school_class.name}: {emails}")
    print(f"    parents     p1..p6@{DOMAIN}")
    print(f"                  p6 has children in TWO grades - use this one for the")
    print(f"                  child selector and scoped-announcement beats")

    print("\n  WHO TO USE FOR THE RISK DEMO")
    rows = session.execute(text("""
        select u.full_name, u.email, c.name, rf.risk_level, round(rf.score::numeric, 2)
        from risk_flags rf
        join users u on u.id = rf.student_id
        left join enrollments e on e.student_id = u.id and e.is_primary
        left join classes c on c.id = e.class_id
        where u.school_id = :sid and rf.status <> 'resolved'
        order by rf.score desc limit 6
    """), {"sid": school.id}).fetchall()
    if rows:
        for name, email, class_name, level, score in rows:
            print(f"    {level:<7} {score}  {name:<18} {email:<22} {class_name}")
    else:
        print("    (no open flags - check that attendance seeded and scoring ran)")

    print("\n  ROW COUNTS")
    checks = [
        ("users", "select count(*) from users where school_id=:sid"),
        ("classes", "select count(*) from classes where school_id=:sid"),
        ("timetable slots", "select count(*) from timetable_slots t join classes c on c.id=t.class_id where c.school_id=:sid and t.is_active"),
        ("attendance records", "select count(*) from attendance_records a join classes c on c.id=a.class_id where c.school_id=:sid"),
        ("remarks", "select count(*) from remarks where school_id=:sid"),
        ("gradebook entries", "select count(*) from gradebook_entries where school_id=:sid"),
        ("report cards", "select count(*) from report_cards where school_id=:sid"),
        ("assignments", "select count(*) from assignments where school_id=:sid"),
        ("quizzes", "select count(*) from quizzes where school_id=:sid"),
        ("resources", "select count(*) from resources where school_id=:sid"),
        ("kb chunks (bot corpus)", "select count(*) from kb_chunks where school_id=:sid"),
        ("doubt threads", "select count(*) from doubt_threads where school_id=:sid"),
        ("open risk flags", "select count(*) from risk_flags rf join users u on u.id=rf.student_id where u.school_id=:sid and rf.status<>'resolved'"),
        ("fee records", "select count(*) from fee_records fr join users u on u.id=fr.student_id where u.school_id=:sid"),
        ("announcements", "select count(*) from announcements where school_id=:sid"),
        ("exams", "select count(*) from exams where school_id=:sid"),
        ("library loans", "select count(*) from library_loans where school_id=:sid"),
        ("syllabus plans", "select count(*) from syllabus_plans sp join classes c on c.id=sp.class_id where c.school_id=:sid"),
        ("pending leave requests", "select count(*) from leave_requests lr join users u on u.id=lr.teacher_id where u.school_id=:sid and lr.status='pending'"),
    ]
    for label, sql in checks:
        n = session.execute(text(sql), {"sid": school.id}).scalar()
        flag = "" if n else "   <-- EMPTY"
        print(f"    {label:<24} {n}{flag}")

    print("\n  STILL TO DO BEFORE RECORDING")
    print("    1. Enrol a few faces for CV attendance - this script cannot fabricate them:")
    print("       POST /attendance/enroll with photos of 3-4 Grade 3 - A students")
    print("    2. Nothing else. Every other screen has data.")
    print()


# --- Entry point ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true",
                        help="Actually write. Without this, prints the plan and exits.")
    parser.add_argument("--skip-rag", action="store_true",
                        help="Skip resource upload and embedding (no Gemini calls, no Storage "
                             "writes). Everything else still seeds; the Doubt Bot will have no "
                             "corpus.")
    parser.add_argument("--skip-timetable", action="store_true",
                        help="Skip the solver. Useful when re-running only to top up academics.")
    args = parser.parse_args()

    if not args.apply:
        print(f"DRY RUN - nothing will be written. Plan for {SCHOOL_NAME}:")
        print(f"  {len(CLASS_SPECS)} classes: {', '.join(c.name for c in CLASS_SPECS)}")
        print(f"  {len(CLASS_SPECS) * STUDENTS_PER_CLASS} students, {TEACHER_COUNT} teachers, "
              f"6 parents, 1 principal, 1 admin")
        print(f"  {len(CLASS_SPECS) * sum(s[2] for s in SUBJECTS)} timetable periods to solve")
        print(f"  {sum(len(v) for v in RESOURCE_TEXTS.values())} resources to upload and embed"
              + (" (SKIPPED)" if args.skip_rag else ""))
        print(f"  ~{len(CLASS_SPECS) * STUDENTS_PER_CLASS + TEACHER_COUNT + 8} Supabase Auth "
              "accounts to create or adopt")
        print(f"\n  shared password: {PASSWORD}")
        print("\nRe-run with --apply to execute.")
        return

    session = SessionLocal()
    counts: dict = {}
    try:
        print("\n[1/9] school, subjects, rooms, staff, classes")
        base = seed_master_data(session, counts)
        session.commit()

        print("\n[2/9] students, enrollments, parents")
        people = seed_people(session, base, counts)
        session.commit()

        if args.skip_timetable:
            print("\n[3/9] timetable - SKIPPED")
        else:
            print("\n[3/9] timetable (real CP-SAT solver)")
            seed_timetable(session, base, counts)
            session.commit()

        print("\n[4/9] attendance history")
        seed_attendance(session, base, people, counts)
        session.commit()

        print("\n[5/9] remarks and gradebook")
        seed_remarks(session, base, people, counts)
        seed_gradebook(session, base, people, counts)
        session.commit()

        print("\n[6/9] report cards (real service)")
        seed_report_cards(session, people, counts)
        session.commit()

        print("\n[7/9] classroom activity, fees, announcements, exams, leave")
        seed_classroom_activity(session, base, people, counts)
        session.commit()
        seed_operations(session, base, people, counts)
        session.commit()

        if args.skip_rag:
            print("\n[8/9] RAG corpus - SKIPPED (--skip-rag)")
        else:
            print("\n[8/9] RAG corpus (real upload + real embeddings)")
            seed_rag_corpus(session, base, counts)
        seed_doubts(session, base, people, counts, skip_rag=args.skip_rag)
        session.commit()

        if args.skip_rag:
            print("      Doubt Bot history - SKIPPED (--skip-rag): Top Doubts will be empty")
        else:
            seed_doubt_bot_history(session, base, people, counts)

        print("\n[9/9] risk scoring (real nightly job)")
        score_risk(session, base, counts)

    except Exception:
        session.rollback()
        print("\n!! FAILED - rolled back the current phase. Earlier phases are already "
              "committed, so re-running is safe and will resume.", file=sys.stderr)
        raise
    else:
        print_summary(session, base, people, counts)
    finally:
        session.close()



# --- Phase 11: Doubt Bot history, so "Top Doubts" has something to cluster ------------

DOUBT_BOT_HISTORY = [
    # (class name, subject name, question). Grouped into concept clusters ON PURPOSE, and
    # deliberately spread ACROSS SECTIONS within a grade: services/doubt_insights.py badges a
    # cluster with the sections it spans, and that badge is the whole point of the widget -
    # "both my Grade 3 sections are stuck on the same thing" is the insight. Questions confined
    # to one section would cluster fine and say nothing interesting.
    #
    # Every question is answerable from the resources this script seeds, so the bot returns a
    # real cited answer rather than "I couldn't find anything about that in your class notes".

    # Cluster: water disappearing / evaporation (Grade 3, both sections)
    ("Grade 3 - A", "Science", "Why does the water in a puddle disappear when the sun comes out?"),
    ("Grade 3 - B", "Science", "Where does water go when it evaporates?"),
    ("Grade 3 - A", "Science", "How can water turn into vapour without boiling it?"),
    ("Grade 3 - B", "Science", "Why do wet clothes dry faster in the sun?"),

    # Cluster: condensation (Grade 3, both sections)
    ("Grade 3 - A", "Science", "Why do water drops appear on the outside of a cold glass?"),
    ("Grade 3 - B", "Science", "Where do the droplets on a cold bottle come from?"),
    ("Grade 3 - A", "Science", "Is condensation just the opposite of evaporation?"),

    # Cluster: the water cycle (Grade 3, both sections)
    ("Grade 3 - B", "Science", "How do clouds form high up in the sky?"),
    ("Grade 3 - A", "Science", "Why does it rain?"),
    ("Grade 3 - B", "Science", "What are the steps of the water cycle?"),

    # Cluster: fractions (Grade 3) - so a MATHS teacher's widget populates too, and so the
    # demo's own Doubt Bot beat sits alongside questions students already asked.
    ("Grade 3 - A", "Mathematics", "Why do we have to make the denominators the same before adding fractions?"),
    ("Grade 3 - B", "Mathematics", "How do I add one half and one quarter?"),
    ("Grade 3 - A", "Mathematics", "Which is bigger, five eighths or three eighths?"),

    # Cluster: counting and place value (Grade 1, both sections)
    ("Grade 1 - A", "Mathematics", "How do I know if a number is bigger when both have the same tens?"),
    ("Grade 1 - B", "Mathematics", "What does it mean when we say 34 has 3 tens and 4 ones?"),
    ("Grade 1 - A", "Mathematics", "Why do we skip count in twos and fives?"),
    ("Grade 1 - B", "Mathematics", "What are number bonds to ten?"),

    # Cluster: living and non-living (Grade 1, both sections)
    ("Grade 1 - A", "Science", "How do I tell if something is living or non-living?"),
    ("Grade 1 - B", "Science", "Is a seed living even though it does not move?"),
    ("Grade 1 - A", "Science", "Why do plants need sunlight to grow?"),

    # Cluster: naming words (Grade 1)
    ("Grade 1 - B", "English", "Why does one child become children and not childs?"),
    ("Grade 1 - A", "English", "How do I make a naming word mean many?"),

    # Cluster: photosynthesis (Grade 2, both sections)
    ("Grade 2 - A", "Science", "How do leaves make food for the plant?"),
    ("Grade 2 - B", "Science", "Why does a plant kept in a dark cupboard turn pale?"),
    ("Grade 2 - A", "Science", "What do the roots actually do for a plant?"),
    ("Grade 2 - B", "Science", "What is the difference between a shrub and a tree?"),

    # Cluster: carrying and borrowing (Grade 2, both sections)
    ("Grade 2 - A", "Mathematics", "Why do we carry the one when the ones add up past ten?"),
    ("Grade 2 - B", "Mathematics", "How do I borrow a ten when the top digit is smaller?"),
    ("Grade 2 - A", "Mathematics", "How can I check my subtraction is right?"),

    # Cluster: punctuation (Grade 2, both sections) - so the ENGLISH teacher's widget fills
    ("Grade 2 - A", "English", "When do I use a question mark instead of a full stop?"),
    ("Grade 2 - B", "English", "Where do the commas go when I list things?"),
    ("Grade 2 - A", "English", "What is the naming part and the action part of a sentence?"),

    # Cluster: tenses (Grade 3, both sections) - English for Grade 3
    ("Grade 3 - A", "English", "How do I change a verb into the past tense?"),
    ("Grade 3 - B", "English", "Why is the past of go went and not goed?"),
    ("Grade 3 - A", "English", "What are helping verbs?"),
]


def seed_doubt_bot_history(session: Session, base: dict, people: dict, counts: dict) -> int:
    """Replays real Doubt Bot conversations, mirroring POST /bots/student/ask exactly.

    WHY MIRROR THE HANDLER instead of inserting rows: Top Doubts clusters on
    `query_embedding` and infers a subject from the chunks actually retrieved. A hand-written
    row with a null or fake embedding is silently unusable - `top_doubts` drops it from
    `usable` and falls back to an unlabelled recent-questions list, so the widget looks
    populated-but-broken rather than empty. Embedding for real also means the clusters that
    appear are the ones the algorithm genuinely finds.

    Costs one embedding plus one LLM call per question, so it is skipped by --skip-rag.
    """
    from app.models.knowledge import ChatbotLog
    from app.models.school import School
    from app.routers.bots import _build_context, student_bot_system_prompt
    from app.services.llm import embed_query, generate
    from app.services.retrieval import DEFAULT_TOP_K, infer_subject_id, search_chunks

    school = base["school"]
    by_name = {c.name: c for c in base["classes"]}
    written = 0
    now = datetime.now(timezone.utc)

    for i, (class_name, subject_name, query) in enumerate(DOUBT_BOT_HISTORY):
        school_class = by_name[class_name]
        roster = people["by_class"][school_class.id]
        # Rotate the asker so the questions are not all attributed to one child.
        student = roster[i % len(roster)]

        existing = (
            session.query(ChatbotLog)
            .filter(ChatbotLog.user_id == student.id, ChatbotLog.query == query)
            .one_or_none()
        )
        if existing is not None:
            continue

        try:
            subject = base["subjects"][subject_name]
            query_embedding = embed_query(query)
            chunks = search_chunks(
                session,
                query_embedding=query_embedding,
                school_id=school.id,
                grade_level=school_class.grade_level,
                # Scoped to the subject we KNOW the question belongs to. The live endpoint
                # passes None because the UI cannot ask a child to classify their own
                # question, and then infers the subject from whatever came back - which
                # mislabelled every Grade 3 fractions question as Science, so the maths
                # teacher's Top Doubts was empty while the science teacher's showed maths.
                # Here the subject is known, and POST /bots/student/ask accepts one, so this
                # is the same code path a client that supplies subject_id takes.
                subject_id=subject.id,
                top_k=DEFAULT_TOP_K,
            )
            if chunks:
                answer = generate(
                    student_bot_system_prompt(
                        school_name=school.name, grade_level=school_class.grade_level
                    ),
                    f"CONTEXT:\n{_build_context(chunks)}\n\nSTUDENT'S QUESTION: {query}",
                )
            else:
                answer = (
                    "I couldn't find anything about that in your class notes yet. "
                    "Ask your teacher, or try asking about a topic you've covered in class."
                )
        except Exception as exc:  # noqa: BLE001 - reported, and the rest still seed
            print(f"    ! skipped {query[:44]!r}: {str(exc)[:70]}")
            continue

        session.add(
            ChatbotLog(
                user_id=student.id,
                bot_type="student",
                query=query,
                response=answer,
                kb_chunks_used={"chunk_ids": [c.chunk_id for c in chunks]},
                query_embedding=query_embedding,
                class_id=school_class.id,
                # Known subject first, inference only as a fallback - the reverse of the
                # live handler, for the reason given above.
                subject_id=subject.id or infer_subject_id(chunks),
                # Spread over the last five days so the widget's 7-day window holds them all
                # and they do not all share one timestamp.
                created_at=now - timedelta(days=i % 5, hours=(i * 3) % 24),
            )
        )
        session.commit()
        written += 1
        cited = len(chunks)
        print(f"    logged ({cited} chunk{'s' if cited != 1 else ''} cited) {class_name}: {query[:52]}")

    note(counts, "chatbot_logs", written)
    print(f"  Doubt Bot history: {written} conversations logged")
    return written

if __name__ == "__main__":
    main()
