"""Tests for the read/correct/analyse half of the attendance router:
GET /attendance/register, POST /attendance/manual, GET /attendance/analytics and
GET /attendance/my-records.

The CV pipeline itself (enroll/mark/summary/review) is covered by
test_attendance_api.py - nothing here re-tests recognition.
"""

import uuid
from datetime import date, time, timedelta

import pytest

from app.main import app
from app.models.attendance import AttendanceRecord
from app.models.audit import AuditLogEntry
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

MONDAY = date(2026, 8, 10)
"""A real Monday - the register resolves periods by date.weekday(), so a
fixed weekday keeps these tests independent of when they run."""


def _override_user(role: str, user_id: int, school_id: int | None):
    def _fake_user():
        return CurrentUser(
            id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role, school_id=school_id
        )

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_user_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _user(db, role_name: str, school_id: int, name: str) -> User:
    role = db.query(Role).filter(Role.name == role_name).one()
    row = User(
        supabase_id=uuid.uuid4(),
        email=f"{name}-{uuid.uuid4()}@example.com",
        full_name=name,
        role_id=role.id,
        school_id=school_id,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def seed(db_session):
    """One class with 2 periods on Monday and 3 students, plus:
    - a homeroom teacher (class_teacher_id)
    - a subject teacher who only teaches period 2 and owns no class
    - a second school with its own class, for cross-tenant checks
    """
    school = School(name="Register Test School")
    other_school = School(name="Other School")
    db_session.add_all([school, other_school])
    db_session.flush()

    homeroom = _user(db_session, "teacher", school.id, "Homeroom Teacher")
    subject_teacher = _user(db_session, "teacher", school.id, "Subject Teacher")
    admin = _user(db_session, "admin", school.id, "Admin User")
    principal = _user(db_session, "principal", school.id, "Principal User")

    school_class = SchoolClass(
        name="Grade 8 - A",
        academic_year="2026-27",
        grade_level=8,
        section="A",
        school_id=school.id,
        class_teacher_id=homeroom.id,
    )
    other_class = SchoolClass(
        name="Grade 9 - B", academic_year="2026-27", grade_level=9, section="B", school_id=other_school.id
    )
    db_session.add_all([school_class, other_class])
    db_session.flush()

    math = Subject(name="Math", school_id=school.id)
    science = Subject(name="Science", school_id=school.id)
    room = Room(name="R1", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add_all([math, science, room])
    db_session.flush()

    students = [_user(db_session, "student", school.id, n) for n in ("Aarav", "Diya", "Kabir")]
    db_session.add_all(
        [Enrollment(student_id=s.id, class_id=school_class.id, is_primary=True) for s in students]
    )

    slot1 = TimetableSlot(
        day_of_week=0,
        period_number=1,
        start_time=time(8, 0),
        end_time=time(8, 45),
        subject_id=math.id,
        teacher_id=homeroom.id,
        class_id=school_class.id,
        room_id=room.id,
        academic_year="2026-27",
        is_active=True,
    )
    slot2 = TimetableSlot(
        day_of_week=0,
        period_number=2,
        start_time=time(8, 45),
        end_time=time(9, 30),
        subject_id=science.id,
        teacher_id=subject_teacher.id,
        class_id=school_class.id,
        room_id=room.id,
        academic_year="2026-27",
        is_active=True,
    )
    # Tuesday period - must never appear in a Monday register.
    slot_tuesday = TimetableSlot(
        day_of_week=1,
        period_number=1,
        start_time=time(8, 0),
        end_time=time(8, 45),
        subject_id=math.id,
        teacher_id=homeroom.id,
        class_id=school_class.id,
        room_id=room.id,
        academic_year="2026-27",
        is_active=True,
    )
    db_session.add_all([slot1, slot2, slot_tuesday])
    db_session.commit()
    for row in (slot1, slot2, slot_tuesday, school_class, other_class):
        db_session.refresh(row)

    return {
        "school": school,
        "other_school": other_school,
        "class": school_class,
        "other_class": other_class,
        "homeroom": homeroom,
        "subject_teacher": subject_teacher,
        "admin": admin,
        "principal": principal,
        "students": students,
        "slot1": slot1,
        "slot2": slot2,
        "slot_tuesday": slot_tuesday,
    }


def _as_admin(seed):
    _override_user("admin", seed["admin"].id, seed["school"].id)


# --- GET /attendance/register: RBAC -------------------------------------------


def test_register_requires_token(client, seed):
    resp = client.get("/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)})
    assert resp.status_code == 401


def test_register_forbidden_for_student(client, seed):
    _override_user("student", seed["students"][0].id, seed["school"].id)
    resp = client.get("/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)})
    assert resp.status_code == 403


def test_register_forbidden_for_parent(client, seed):
    _override_user("parent", 12345, seed["school"].id)
    resp = client.get("/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)})
    assert resp.status_code == 403


def test_register_404_for_class_in_another_school(client, seed):
    """Cross-tenant: an admin of school A must not read school B's register by
    guessing a class id."""
    _as_admin(seed)
    resp = client.get(
        "/attendance/register", params={"class_id": seed["other_class"].id, "date": str(MONDAY)}
    )
    assert resp.status_code == 404


def test_register_400_when_user_has_no_school(client, seed):
    _override_user("admin", seed["admin"].id, None)
    resp = client.get("/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)})
    assert resp.status_code == 400


def test_register_allows_homeroom_teacher(client, seed):
    _override_user("teacher", seed["homeroom"].id, seed["school"].id)
    resp = client.get("/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)})
    assert resp.status_code == 200


def test_register_allows_subject_teacher_who_owns_no_class(client, seed):
    """The widened teacher rule: whoever teaches a period to this class may read
    its register, even without being its class teacher."""
    _override_user("teacher", seed["subject_teacher"].id, seed["school"].id)
    resp = client.get("/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)})
    assert resp.status_code == 200


def test_register_forbidden_for_unrelated_teacher(client, seed, db_session):
    stranger = _user(db_session, "teacher", seed["school"].id, "Stranger")
    db_session.commit()
    _override_user("teacher", stranger.id, seed["school"].id)
    resp = client.get("/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)})
    assert resp.status_code == 403


def test_register_allows_principal(client, seed):
    _override_user("principal", seed["principal"].id, seed["school"].id)
    resp = client.get("/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)})
    assert resp.status_code == 200


# --- GET /attendance/register: shape -----------------------------------------


def test_register_returns_only_that_weekdays_periods(client, seed):
    _as_admin(seed)
    resp = client.get("/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)})
    assert resp.status_code == 200
    body = resp.json()
    assert [p["period_number"] for p in body["periods"]] == [1, 2]
    assert seed["slot_tuesday"].id not in [p["timetable_slot_id"] for p in body["periods"]]
    assert body["grade_level"] == 8
    assert body["section"] == "A"
    assert body["day_of_week"] == 0


def test_register_grid_is_students_x_periods(client, seed):
    _as_admin(seed)
    body = client.get(
        "/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)}
    ).json()
    assert len(body["students"]) == 3
    assert [s["name"] for s in body["students"]] == ["Aarav", "Diya", "Kabir"]
    for student in body["students"]:
        assert len(student["cells"]) == 2


def test_register_reports_unmarked_periods_when_nothing_recorded(client, seed):
    _as_admin(seed)
    body = client.get(
        "/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)}
    ).json()
    assert all(p["is_marked"] is False for p in body["periods"])
    assert body["totals"]["unmarked_periods"] == 2
    assert body["totals"]["marked_periods"] == 0
    assert body["totals"]["unmarked_cells"] == 6
    assert all(cell["status"] is None for s in body["students"] for cell in s["cells"])


def test_register_distinguishes_marked_from_all_absent(client, seed, db_session):
    """A period where everyone is absent is `is_marked: True` - only a period
    with no records at all is unmarked."""
    for student in seed["students"]:
        db_session.add(
            AttendanceRecord(
                student_id=student.id,
                class_id=seed["class"].id,
                timetable_slot_id=seed["slot1"].id,
                date=MONDAY,
                status="absent",
                source="manual",
            )
        )
    db_session.commit()

    _as_admin(seed)
    body = client.get(
        "/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)}
    ).json()
    periods = {p["period_number"]: p for p in body["periods"]}
    assert periods[1]["is_marked"] is True
    assert periods[1]["marked_count"] == 3
    assert periods[2]["is_marked"] is False
    assert body["totals"]["unmarked_periods"] == 1
    assert body["totals"]["absent_cells"] == 3


def test_register_surfaces_cv_confidence_and_review_flag(client, seed, db_session):
    db_session.add(
        AttendanceRecord(
            student_id=seed["students"][0].id,
            class_id=seed["class"].id,
            timetable_slot_id=seed["slot1"].id,
            date=MONDAY,
            status="present",
            source="cv",
            confidence_score=0.47,  # inside the 0.40-0.55 confidence review band
        )
    )
    db_session.add(
        AttendanceRecord(
            student_id=seed["students"][1].id,
            class_id=seed["class"].id,
            timetable_slot_id=seed["slot1"].id,
            date=MONDAY,
            status="present",
            source="cv",
            confidence_score=0.91,
        )
    )
    db_session.commit()

    _as_admin(seed)
    body = client.get(
        "/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)}
    ).json()
    by_name = {s["name"]: s for s in body["students"]}
    aarav_p1 = by_name["Aarav"]["cells"][0]
    diya_p1 = by_name["Diya"]["cells"][0]
    assert aarav_p1["needs_review"] is True
    assert aarav_p1["source"] == "cv"
    assert diya_p1["needs_review"] is False


def test_register_per_student_pct_ignores_unmarked_periods(client, seed, db_session):
    student = seed["students"][0]
    db_session.add(
        AttendanceRecord(
            student_id=student.id,
            class_id=seed["class"].id,
            timetable_slot_id=seed["slot1"].id,
            date=MONDAY,
            status="present",
            source="manual",
        )
    )
    db_session.commit()

    _as_admin(seed)
    body = client.get(
        "/attendance/register", params={"class_id": seed["class"].id, "date": str(MONDAY)}
    ).json()
    aarav = next(s for s in body["students"] if s["name"] == "Aarav")
    # 1 present of 1 marked period = 100%, not 50% of the two scheduled periods.
    assert aarav["present_pct"] == 100.0
    assert aarav["unmarked_count"] == 1


# --- POST /attendance/manual -------------------------------------------------


def _manual_body(seed, entries):
    return {"class_id": seed["class"].id, "date": str(MONDAY), "entries": entries}


def test_manual_creates_records(client, seed, db_session):
    _as_admin(seed)
    entries = [
        {"student_id": s.id, "timetable_slot_id": seed["slot1"].id, "status": "present"}
        for s in seed["students"]
    ]
    resp = client.post("/attendance/manual", json=_manual_body(seed, entries))
    assert resp.status_code == 200
    body = resp.json()
    assert (body["created"], body["updated"], body["unchanged"]) == (3, 0, 0)
    rows = (
        db_session.query(AttendanceRecord)
        .filter(AttendanceRecord.timetable_slot_id == seed["slot1"].id, AttendanceRecord.date == MONDAY)
        .all()
    )
    assert len(rows) == 3
    assert {r.source for r in rows} == {"manual"}
    assert all(r.reviewed_by == seed["admin"].id for r in rows)


def test_manual_updates_cv_record_in_place_without_duplicating(client, seed, db_session):
    """The double-count trap: the unique constraint includes `source`, so a
    naive insert would leave a cv row AND a manual row for the same period and
    double-count that student in /summary."""
    student = seed["students"][0]
    cv_row = AttendanceRecord(
        student_id=student.id,
        class_id=seed["class"].id,
        timetable_slot_id=seed["slot1"].id,
        date=MONDAY,
        status="present",
        source="cv",
        confidence_score=0.52,
    )
    db_session.add(cv_row)
    db_session.commit()
    cv_row_id = cv_row.id

    _as_admin(seed)
    resp = client.post(
        "/attendance/manual",
        json=_manual_body(
            seed, [{"student_id": student.id, "timetable_slot_id": seed["slot1"].id, "status": "absent"}]
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body["created"], body["updated"]) == (0, 1)

    rows = (
        db_session.query(AttendanceRecord)
        .filter(
            AttendanceRecord.student_id == student.id,
            AttendanceRecord.timetable_slot_id == seed["slot1"].id,
            AttendanceRecord.date == MONDAY,
        )
        .all()
    )
    assert len(rows) == 1, "manual marking must not add a second row alongside the cv row"
    assert rows[0].id == cv_row_id
    assert rows[0].status == "absent"
    # source stays 'cv' so provenance survives; reviewed_by is the human proof.
    assert rows[0].source == "cv"
    assert rows[0].reviewed_by == seed["admin"].id
    assert rows[0].reviewed_at is not None


def test_manual_reports_unchanged_and_writes_no_audit_row(client, seed, db_session):
    student = seed["students"][0]
    db_session.add(
        AttendanceRecord(
            student_id=student.id,
            class_id=seed["class"].id,
            timetable_slot_id=seed["slot1"].id,
            date=MONDAY,
            status="present",
            source="manual",
        )
    )
    db_session.commit()
    before = db_session.query(AuditLogEntry).filter(AuditLogEntry.action == "manual_mark").count()

    _as_admin(seed)
    resp = client.post(
        "/attendance/manual",
        json=_manual_body(
            seed, [{"student_id": student.id, "timetable_slot_id": seed["slot1"].id, "status": "present"}]
        ),
    )
    assert resp.json()["unchanged"] == 1
    after = db_session.query(AuditLogEntry).filter(AuditLogEntry.action == "manual_mark").count()
    assert after == before, "a no-op re-mark should not create an audit row"


def test_manual_writes_audit_log_with_before_and_after(client, seed, db_session):
    student = seed["students"][0]
    db_session.add(
        AttendanceRecord(
            student_id=student.id,
            class_id=seed["class"].id,
            timetable_slot_id=seed["slot1"].id,
            date=MONDAY,
            status="present",
            source="cv",
            confidence_score=0.5,
        )
    )
    db_session.commit()

    _as_admin(seed)
    client.post(
        "/attendance/manual",
        json=_manual_body(
            seed, [{"student_id": student.id, "timetable_slot_id": seed["slot1"].id, "status": "late"}]
        ),
    )
    entry = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.action == "manual_mark", AuditLogEntry.entity_type == "attendance_records")
        .order_by(AuditLogEntry.id.desc())
        .first()
    )
    assert entry is not None
    assert entry.detail["previous_status"] == "present"
    assert entry.detail["new_status"] == "late"
    assert entry.actor_id == seed["admin"].id


def test_manual_rejects_student_not_in_class(client, seed, db_session):
    outsider = _user(db_session, "student", seed["school"].id, "Outsider")
    db_session.commit()
    _as_admin(seed)
    resp = client.post(
        "/attendance/manual",
        json=_manual_body(
            seed, [{"student_id": outsider.id, "timetable_slot_id": seed["slot1"].id, "status": "present"}]
        ),
    )
    assert resp.status_code == 400
    assert "not enrolled" in resp.json()["detail"]


def test_manual_rejects_slot_from_another_class(client, seed, db_session):
    _as_admin(seed)
    other_slot = TimetableSlot(
        day_of_week=0,
        period_number=1,
        start_time=time(8, 0),
        end_time=time(8, 45),
        subject_id=db_session.query(Subject).filter(Subject.school_id == seed["school"].id).first().id,
        teacher_id=seed["homeroom"].id,
        class_id=seed["other_class"].id,
        room_id=db_session.query(Room).filter(Room.school_id == seed["school"].id).first().id,
        academic_year="2026-27",
        is_active=True,
    )
    db_session.add(other_slot)
    db_session.commit()

    resp = client.post(
        "/attendance/manual",
        json=_manual_body(
            seed,
            [{"student_id": seed["students"][0].id, "timetable_slot_id": other_slot.id, "status": "present"}],
        ),
    )
    assert resp.status_code == 400
    assert "not active periods" in resp.json()["detail"]


def test_manual_rejects_invalid_status(client, seed):
    _as_admin(seed)
    resp = client.post(
        "/attendance/manual",
        json=_manual_body(
            seed,
            [{"student_id": seed["students"][0].id, "timetable_slot_id": seed["slot1"].id, "status": "maybe"}],
        ),
    )
    assert resp.status_code == 400


def test_manual_last_entry_wins_for_duplicate_cells(client, seed, db_session):
    _as_admin(seed)
    student = seed["students"][0]
    resp = client.post(
        "/attendance/manual",
        json=_manual_body(
            seed,
            [
                {"student_id": student.id, "timetable_slot_id": seed["slot1"].id, "status": "present"},
                {"student_id": student.id, "timetable_slot_id": seed["slot1"].id, "status": "absent"},
            ],
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1
    row = (
        db_session.query(AttendanceRecord)
        .filter(AttendanceRecord.student_id == student.id, AttendanceRecord.date == MONDAY)
        .one()
    )
    assert row.status == "absent"


def test_manual_allowed_for_principal(client, seed):
    _override_user("principal", seed["principal"].id, seed["school"].id)
    resp = client.post(
        "/attendance/manual",
        json=_manual_body(
            seed,
            [{"student_id": seed["students"][0].id, "timetable_slot_id": seed["slot1"].id, "status": "present"}],
        ),
    )
    assert resp.status_code == 200


def test_manual_forbidden_for_student(client, seed):
    _override_user("student", seed["students"][0].id, seed["school"].id)
    resp = client.post(
        "/attendance/manual",
        json=_manual_body(
            seed,
            [{"student_id": seed["students"][0].id, "timetable_slot_id": seed["slot1"].id, "status": "present"}],
        ),
    )
    assert resp.status_code == 403


def test_manual_404_for_class_in_another_school(client, seed):
    _as_admin(seed)
    resp = client.post(
        "/attendance/manual",
        json={
            "class_id": seed["other_class"].id,
            "date": str(MONDAY),
            "entries": [
                {"student_id": seed["students"][0].id, "timetable_slot_id": seed["slot1"].id, "status": "present"}
            ],
        },
    )
    assert resp.status_code == 404


def test_manual_accepts_empty_entries(client, seed):
    _as_admin(seed)
    resp = client.post("/attendance/manual", json=_manual_body(seed, []))
    assert resp.status_code == 200
    assert resp.json() == {"created": 0, "updated": 0, "unchanged": 0, "records": []}


# --- GET /attendance/analytics -----------------------------------------------


@pytest.fixture()
def marked(seed, db_session):
    """Aarav present in both periods, Diya absent in P1/present in P2, Kabir
    absent in both - so P1 is 33% and P2 is 67%."""
    plan = [
        (seed["students"][0], seed["slot1"], "present"),
        (seed["students"][0], seed["slot2"], "present"),
        (seed["students"][1], seed["slot1"], "absent"),
        (seed["students"][1], seed["slot2"], "present"),
        (seed["students"][2], seed["slot1"], "absent"),
        (seed["students"][2], seed["slot2"], "absent"),
    ]
    for student, slot, status in plan:
        db_session.add(
            AttendanceRecord(
                student_id=student.id,
                class_id=seed["class"].id,
                timetable_slot_id=slot.id,
                date=MONDAY,
                status=status,
                source="manual",
            )
        )
    db_session.commit()
    return seed


def _analytics(client, seed, **params):
    return client.get(
        "/attendance/analytics",
        params={"from_date": str(MONDAY), "to_date": str(MONDAY), **params},
    )


def test_analytics_groups_by_period(client, marked):
    _as_admin(marked)
    body = _analytics(client, marked).json()
    by_period = {p["period_number"]: p for p in body["by_period"]}
    assert by_period[1]["present_pct"] == 33.3
    assert by_period[2]["present_pct"] == 66.7
    assert body["overall"]["total_records"] == 6
    assert body["overall"]["present_count"] == 3


def test_analytics_groups_by_day_class_and_subject(client, marked):
    _as_admin(marked)
    body = _analytics(client, marked).json()
    assert [d["date"] for d in body["by_day"]] == [str(MONDAY)]
    assert body["by_day"][0]["day_of_week"] == 0
    assert len(body["by_class"]) == 1
    assert body["by_class"][0]["section"] == "A"
    assert {s["subject_name"] for s in body["by_subject"]} == {"Math", "Science"}


def test_analytics_students_sorted_worst_first_with_trend(client, marked):
    _as_admin(marked)
    body = _analytics(client, marked).json()
    assert [s["name"] for s in body["students"]] == ["Kabir", "Diya", "Aarav"]
    assert body["students"][0]["present_pct"] == 0.0
    assert body["students"][-1]["present_pct"] == 100.0
    # Single-day window: both halves can't both have records, so no false trend.
    assert all(s["trend"] == "flat" for s in body["students"])


def test_analytics_below_pct_filters_to_defaulters(client, marked):
    _as_admin(marked)
    body = _analytics(client, marked, below_pct=75).json()
    assert [s["name"] for s in body["students"]] == ["Kabir", "Diya"]
    assert body["below_pct_count"] == 2


def test_analytics_period_filter_narrows_records(client, marked):
    _as_admin(marked)
    body = _analytics(client, marked, period_number=1).json()
    assert body["overall"]["total_records"] == 3
    assert [p["period_number"] for p in body["by_period"]] == [1]


def test_analytics_grade_and_section_filters(client, marked):
    _as_admin(marked)
    assert _analytics(client, marked, grade_level=8).json()["overall"]["total_records"] == 6
    assert _analytics(client, marked, grade_level=9).json()["overall"]["total_records"] == 0
    assert _analytics(client, marked, section="A").json()["overall"]["total_records"] == 6
    assert _analytics(client, marked, section="B").json()["overall"]["total_records"] == 0


def test_analytics_rejects_reversed_range(client, seed):
    _as_admin(seed)
    resp = client.get(
        "/attendance/analytics",
        params={"from_date": str(MONDAY), "to_date": str(MONDAY - timedelta(days=5))},
    )
    assert resp.status_code == 400


def test_analytics_scoped_to_teachers_own_classes(client, marked, db_session):
    stranger = _user(db_session, "teacher", marked["school"].id, "Stranger2")
    db_session.commit()
    _override_user("teacher", stranger.id, marked["school"].id)
    body = _analytics(client, marked).json()
    assert body["overall"]["total_records"] == 0
    assert body["students"] == []


def test_analytics_403_for_teacher_naming_someone_elses_class(client, marked, db_session):
    stranger = _user(db_session, "teacher", marked["school"].id, "Stranger3")
    db_session.commit()
    _override_user("teacher", stranger.id, marked["school"].id)
    resp = _analytics(client, marked, class_id=marked["class"].id)
    assert resp.status_code == 403


def test_analytics_404_for_class_in_another_school(client, marked):
    _as_admin(marked)
    resp = _analytics(client, marked, class_id=marked["other_class"].id)
    assert resp.status_code == 404


def test_analytics_forbidden_for_student_and_parent(client, marked):
    _override_user("student", marked["students"][0].id, marked["school"].id)
    assert _analytics(client, marked).status_code == 403
    _override_user("parent", 999, marked["school"].id)
    assert _analytics(client, marked).status_code == 403


# --- GET /attendance/my-records ----------------------------------------------


def _my_records(client, **params):
    return client.get(
        "/attendance/my-records",
        params={"from_date": str(MONDAY - timedelta(days=7)), "to_date": str(MONDAY), **params},
    )


def test_my_records_student_reads_self_and_ignores_student_id(client, marked):
    """A student passing someone else's student_id still gets their own data."""
    aarav, diya = marked["students"][0], marked["students"][1]
    _override_user("student", aarav.id, marked["school"].id)
    body = _my_records(client, student_id=diya.id).json()
    assert body["student_id"] == aarav.id
    assert body["student_name"] == "Aarav"
    assert body["summary"]["present_count"] == 2


def test_my_records_returns_periods_newest_day_first(client, marked, db_session):
    student = marked["students"][0]
    earlier = MONDAY - timedelta(days=7)
    db_session.add(
        AttendanceRecord(
            student_id=student.id,
            class_id=marked["class"].id,
            timetable_slot_id=marked["slot1"].id,
            date=earlier,
            status="absent",
            source="manual",
        )
    )
    db_session.commit()

    _override_user("student", student.id, marked["school"].id)
    body = _my_records(client).json()
    assert [d["date"] for d in body["days"]] == [str(MONDAY), str(earlier)]
    monday = body["days"][0]
    assert [p["period_number"] for p in monday["periods"]] == [1, 2]
    assert monday["periods"][0]["subject_name"] == "Math"
    assert monday["periods"][1]["subject_name"] == "Science"
    assert monday["present_pct"] == 100.0
    assert body["class_name"] == "Grade 8 - A"


def test_my_records_parent_must_name_a_child(client, marked):
    _override_user("parent", 4242, marked["school"].id)
    assert _my_records(client).status_code == 400


def test_my_records_parent_forbidden_for_unlinked_child(client, marked):
    _override_user("parent", 4242, marked["school"].id)
    resp = _my_records(client, student_id=marked["students"][0].id)
    assert resp.status_code == 403


def test_my_records_parent_reads_linked_child(client, marked, db_session):
    parent = _user(db_session, "parent", marked["school"].id, "Parent User")
    db_session.add(ParentStudent(parent_id=parent.id, student_id=marked["students"][0].id))
    db_session.commit()

    _override_user("parent", parent.id, marked["school"].id)
    body = _my_records(client, student_id=marked["students"][0].id).json()
    assert body["student_id"] == marked["students"][0].id
    assert body["summary"]["present_count"] == 2


def test_my_records_staff_requires_student_id(client, marked):
    _as_admin(marked)
    assert _my_records(client).status_code == 400


def test_my_records_admin_reads_any_student_in_own_school(client, marked):
    _as_admin(marked)
    body = _my_records(client, student_id=marked["students"][2].id).json()
    assert body["student_name"] == "Kabir"
    assert body["summary"]["absent_count"] == 2


def test_my_records_404_for_student_in_another_school(client, marked, db_session):
    outsider = _user(db_session, "student", marked["other_school"].id, "Outsider2")
    db_session.commit()
    _as_admin(marked)
    resp = _my_records(client, student_id=outsider.id)
    assert resp.status_code == 404


def test_my_records_teacher_limited_to_own_students(client, marked, db_session):
    stranger = _user(db_session, "teacher", marked["school"].id, "Stranger4")
    db_session.commit()
    _override_user("teacher", stranger.id, marked["school"].id)
    resp = _my_records(client, student_id=marked["students"][0].id)
    assert resp.status_code == 403

    _override_user("teacher", marked["homeroom"].id, marked["school"].id)
    assert _my_records(client, student_id=marked["students"][0].id).status_code == 200


def test_my_records_rejects_reversed_range(client, marked):
    _override_user("student", marked["students"][0].id, marked["school"].id)
    resp = client.get(
        "/attendance/my-records",
        params={"from_date": str(MONDAY), "to_date": str(MONDAY - timedelta(days=1))},
    )
    assert resp.status_code == 400


# --- PUT /attendance/{id}/review now includes principal ----------------------


def test_review_allows_principal(client, seed, db_session):
    record = AttendanceRecord(
        student_id=seed["students"][0].id,
        class_id=seed["class"].id,
        timetable_slot_id=seed["slot1"].id,
        date=MONDAY,
        status="present",
        source="cv",
        confidence_score=0.5,
    )
    db_session.add(record)
    db_session.commit()

    _override_user("principal", seed["principal"].id, seed["school"].id)
    resp = client.put(f"/attendance/{record.id}/review", json={"status": "absent"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "absent"
