import uuid
from datetime import date, time

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest, StaffingForecast, Substitution
from app.models.subject import Subject
from app.models.timetable import Room, TeacherSubject, TeacherUnavailability, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int = 999):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role)

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_user_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _make_user(db_session, role_row, email_prefix, school):
    email = f"{email_prefix}-{uuid.uuid4()}@example.com"
    user = User(supabase_id=uuid.uuid4(), email=email, full_name=email_prefix, role_id=role_row.id, school_id=school.id)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def seed(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    principal_role = db_session.query(Role).filter(Role.name == "principal").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    principal_user = _make_user(db_session, principal_role, "principal", school)
    original_teacher = _make_user(db_session, teacher_role, "original", school)
    good_sub = _make_user(db_session, teacher_role, "good-sub", school)
    busy_sub = _make_user(db_session, teacher_role, "busy-sub", school)
    unqualified_teacher = _make_user(db_session, teacher_role, "unqualified", school)
    unavailable_sub = _make_user(db_session, teacher_role, "unavailable-sub", school)

    subject = Subject(name="Math", school_id=school.id)
    other_subject = Subject(name="Science", school_id=school.id)
    db_session.add_all([subject, other_subject])
    db_session.flush()

    room = Room(name="R1", capacity=30, room_type="classroom", school_id=school.id)
    other_room = Room(name="R2", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add_all([room, other_room])
    db_session.flush()

    school_class = SchoolClass(name="Grade 8 - A", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=original_teacher.id)
    other_class = SchoolClass(name="Grade 9 - B", academic_year=ACADEMIC_YEAR, school_id=school.id)
    db_session.add_all([school_class, other_class])
    db_session.flush()

    db_session.add_all(
        [
            TeacherSubject(teacher_id=original_teacher.id, subject_id=subject.id),
            TeacherSubject(teacher_id=good_sub.id, subject_id=subject.id),
            TeacherSubject(teacher_id=busy_sub.id, subject_id=subject.id),
            TeacherSubject(teacher_id=unavailable_sub.id, subject_id=subject.id),
            # unqualified_teacher deliberately has no TeacherSubject row for Math.
        ]
    )

    # Monday, period 0 - the slot that will need covering.
    day_of_week, period_number = 0, 0
    slot = TimetableSlot(
        day_of_week=day_of_week,
        period_number=period_number,
        start_time=time(8, 0),
        end_time=time(8, 45),
        subject_id=subject.id,
        teacher_id=original_teacher.id,
        class_id=school_class.id,
        room_id=room.id,
        academic_year=ACADEMIC_YEAR,
        is_active=True,
    )
    db_session.add(slot)

    # busy_sub already teaches something else at the exact same day/period.
    busy_slot = TimetableSlot(
        day_of_week=day_of_week,
        period_number=period_number,
        start_time=time(8, 0),
        end_time=time(8, 45),
        subject_id=other_subject.id,
        teacher_id=busy_sub.id,
        class_id=other_class.id,
        room_id=other_room.id,
        academic_year=ACADEMIC_YEAR,
        is_active=True,
    )
    db_session.add(busy_slot)

    db_session.add(
        TeacherUnavailability(
            teacher_id=unavailable_sub.id, day_of_week=day_of_week, period_number=period_number, academic_year=ACADEMIC_YEAR
        )
    )

    students = []
    for i in range(3):
        student = _make_user(db_session, student_role, f"student{i}", school)
        students.append(student)

    db_session.add_all(
        [Enrollment(student_id=s.id, class_id=school_class.id, subject_id=None, is_primary=True) for s in students]
    )

    db_session.commit()
    db_session.refresh(slot)

    return {
        "school": school,
        "class": school_class,
        "subject": subject,
        "slot": slot,
        "admin_user": admin_user,
        "principal_user": principal_user,
        "original_teacher": original_teacher,
        "good_sub": good_sub,
        "busy_sub": busy_sub,
        "unqualified_teacher": unqualified_teacher,
        "unavailable_sub": unavailable_sub,
        "students": students,
    }


# --- RBAC: 401 no token, 403 wrong role ---


def test_request_leave_401_without_token(client):
    resp = client.post("/staff/request_leave", json={"start_date": "2026-08-10", "end_date": "2026-08-10", "reason": "sick"})
    assert resp.status_code == 401


def test_request_leave_403_for_student_role(client):
    _override_user("student")
    resp = client.post("/staff/request_leave", json={"start_date": "2026-08-10", "end_date": "2026-08-10", "reason": "sick"})
    assert resp.status_code == 403


def test_approve_leave_401_without_token(client):
    resp = client.put("/staff/approve_leave", json={"leave_request_id": 1, "decision": "approved"})
    assert resp.status_code == 401


def test_approve_leave_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.put("/staff/approve_leave", json={"leave_request_id": 1, "decision": "approved"})
    assert resp.status_code == 403


def test_suggest_401_without_token(client):
    resp = client.post("/substitution/suggest", json={"leave_request_id": 1})
    assert resp.status_code == 401


def test_suggest_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/substitution/suggest", json={"leave_request_id": 1})
    assert resp.status_code == 403


def test_confirm_401_without_token(client):
    resp = client.put("/substitution/1/confirm", json={})
    assert resp.status_code == 401


def test_confirm_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.put("/substitution/1/confirm", json={})
    assert resp.status_code == 403


def test_leave_requests_401_without_token(client):
    resp = client.get("/staff/leave_requests")
    assert resp.status_code == 401


def test_forecast_401_without_token(client):
    resp = client.get("/admin/staffing/forecast", params={"school_id": 1, "week_start": "2026-08-10"})
    assert resp.status_code == 401


def test_forecast_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/admin/staffing/forecast", params={"school_id": 1, "week_start": "2026-08-10"})
    assert resp.status_code == 403


def test_substitute_suggestions_401_without_token(client):
    resp = client.get(
        "/admin/staffing/substitute-suggestions",
        params={"teacher_id": 1, "date": "2026-08-10", "academic_year": ACADEMIC_YEAR},
    )
    assert resp.status_code == 401


def test_substitute_suggestions_403_for_student_role(client):
    _override_user("student")
    resp = client.get(
        "/admin/staffing/substitute-suggestions",
        params={"teacher_id": 1, "date": "2026-08-10", "academic_year": ACADEMIC_YEAR},
    )
    assert resp.status_code == 403


# --- End-to-end: request -> approve -> suggestion -> confirm ---


def test_full_leave_to_confirmed_substitution_flow(client, seed):
    _override_user("teacher", user_id=seed["original_teacher"].id)
    resp = client.post(
        "/staff/request_leave",
        json={"start_date": "2026-08-10", "end_date": "2026-08-10", "reason": "Feeling unwell"},
    )
    assert resp.status_code == 200
    leave = resp.json()
    assert leave["status"] == "pending"
    assert leave["teacher_id"] == seed["original_teacher"].id

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(
        "/staff/approve_leave",
        json={"leave_request_id": leave["id"], "decision": "approved", "academic_year": ACADEMIC_YEAR},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["leave_request"]["status"] == "approved"
    assert len(body["substitutions"]) == 1
    sub = body["substitutions"][0]
    assert sub["timetable_slot_id"] == seed["slot"].id
    assert sub["original_teacher_id"] == seed["original_teacher"].id
    # good_sub is the only qualified+free+available+not-on-leave candidate.
    assert sub["substitute_teacher_id"] == seed["good_sub"].id
    assert sub["status"] == "suggested"
    assert {c["teacher_id"] for c in sub["candidates"]} == {seed["good_sub"].id}

    resp = client.put(f"/substitution/{sub['id']}/confirm", json={})
    assert resp.status_code == 200
    confirm_body = resp.json()
    assert confirm_body["conflicts"] == []
    assert confirm_body["substitution"]["status"] == "confirmed"
    assert confirm_body["substitution"]["substitute_teacher_id"] == seed["good_sub"].id
    # Alert-ready detail, per the integration point requirement.
    assert confirm_body["class_id"] == seed["class"].id
    assert confirm_body["class_name"] == seed["class"].name
    assert confirm_body["subject_name"] == seed["subject"].name
    assert confirm_body["substitute_teacher_name"] == seed["good_sub"].full_name
    assert set(confirm_body["affected_student_ids"]) == {s.id for s in seed["students"]}


def test_approve_leave_excludes_busy_unqualified_and_unavailable_candidates(client, seed):
    _override_user("teacher", user_id=seed["original_teacher"].id)
    resp = client.post(
        "/staff/request_leave", json={"start_date": "2026-08-10", "end_date": "2026-08-10", "reason": "sick"}
    )
    leave_id = resp.json()["id"]

    _override_user("principal", user_id=seed["principal_user"].id)
    resp = client.put(
        "/staff/approve_leave", json={"leave_request_id": leave_id, "decision": "approved", "academic_year": ACADEMIC_YEAR}
    )
    assert resp.status_code == 200
    candidates = resp.json()["substitutions"][0]["candidates"]
    candidate_ids = {c["teacher_id"] for c in candidates}
    assert seed["busy_sub"].id not in candidate_ids
    assert seed["unqualified_teacher"].id not in candidate_ids
    assert seed["unavailable_sub"].id not in candidate_ids
    assert seed["original_teacher"].id not in candidate_ids


def test_reject_leave_creates_no_substitutions(client, seed):
    _override_user("teacher", user_id=seed["original_teacher"].id)
    resp = client.post(
        "/staff/request_leave", json={"start_date": "2026-08-10", "end_date": "2026-08-10", "reason": "sick"}
    )
    leave_id = resp.json()["id"]

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put("/staff/approve_leave", json={"leave_request_id": leave_id, "decision": "rejected"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["leave_request"]["status"] == "rejected"
    assert body["substitutions"] == []


def test_confirm_flags_conflicts_without_applying_override(client, db_session, seed):
    _override_user("teacher", user_id=seed["original_teacher"].id)
    resp = client.post(
        "/staff/request_leave", json={"start_date": "2026-08-10", "end_date": "2026-08-10", "reason": "sick"}
    )
    leave_id = resp.json()["id"]

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(
        "/staff/approve_leave", json={"leave_request_id": leave_id, "decision": "approved", "academic_year": ACADEMIC_YEAR}
    )
    sub_id = resp.json()["substitutions"][0]["id"]

    # Override with a teacher who is busy at that exact slot.
    resp = client.put(f"/substitution/{sub_id}/confirm", json={"substitute_teacher_id": seed["busy_sub"].id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["substitution"] is None
    assert any(c["type"] == "already_busy" for c in body["conflicts"])

    # Not applied - status must still be "suggested" in the DB.
    row = db_session.query(Substitution).filter(Substitution.id == sub_id).one()
    assert row.status == "suggested"


def test_confirm_returns_404_for_missing_substitution(client, seed):
    _override_user("admin")
    resp = client.put("/substitution/999999/confirm", json={})
    assert resp.status_code == 404


# --- POST /substitution/suggest ---


def test_suggest_preview_mode_does_not_persist(client, seed):
    _override_user("admin")
    resp = client.post(
        "/substitution/suggest",
        json={
            "teacher_id": seed["original_teacher"].id,
            "start_date": "2026-08-10",
            "end_date": "2026-08-10",
            "academic_year": ACADEMIC_YEAR,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["substitutions"]) == 1
    assert body["substitutions"][0]["id"] is None
    assert body["substitutions"][0]["leave_request_id"] is None
    assert body["substitutions"][0]["substitute_teacher_id"] == seed["good_sub"].id


def test_suggest_requires_leave_request_id_or_full_date_range(client, seed):
    _override_user("admin")
    resp = client.post("/substitution/suggest", json={"teacher_id": seed["original_teacher"].id})
    assert resp.status_code == 400


# --- GET /staff/leave_requests: role scoping ---


def test_leave_requests_teacher_only_sees_own(client, seed):
    _override_user("teacher", user_id=seed["original_teacher"].id)
    client.post("/staff/request_leave", json={"start_date": "2026-08-10", "end_date": "2026-08-10", "reason": "sick"})

    _override_user("teacher", user_id=seed["good_sub"].id)
    client.post("/staff/request_leave", json={"start_date": "2026-08-11", "end_date": "2026-08-11", "reason": "family"})

    _override_user("teacher", user_id=seed["original_teacher"].id)
    resp = client.get("/staff/leave_requests")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["teacher_id"] == seed["original_teacher"].id


def test_leave_requests_admin_sees_all_and_can_filter_by_status(client, seed):
    # Admin/principal have no school-scoping on this endpoint - consistent with
    # /timetable/active and /attendance/summary, which don't scope by school either
    # (a known simplification for this single-school demo). So "sees all" means the
    # live DB's full leave_requests table, not just this test's own rows - assert a
    # superset, and use teacher_id to scope down for the exact-match checks.
    _override_user("teacher", user_id=seed["original_teacher"].id)
    r1 = client.post("/staff/request_leave", json={"start_date": "2026-08-10", "end_date": "2026-08-10", "reason": "sick"})
    _override_user("teacher", user_id=seed["good_sub"].id)
    r2 = client.post("/staff/request_leave", json={"start_date": "2026-08-11", "end_date": "2026-08-11", "reason": "family"})

    _override_user("admin", user_id=seed["admin_user"].id)
    client.put("/staff/approve_leave", json={"leave_request_id": r1.json()["id"], "decision": "approved", "academic_year": ACADEMIC_YEAR})

    resp = client.get("/staff/leave_requests")
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert {r1.json()["id"], r2.json()["id"]} <= ids

    resp = client.get("/staff/leave_requests", params={"status": "approved", "teacher_id": seed["original_teacher"].id})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == r1.json()["id"]


def test_leave_requests_403_for_student_role(client):
    _override_user("student")
    resp = client.get("/staff/leave_requests")
    assert resp.status_code == 403


# --- GET /admin/staffing/forecast ---


def test_forecast_returns_seven_days_and_persists(client, db_session, seed):
    past_friday = date(2026, 8, 7)
    db_session.add(
        LeaveRequest(teacher_id=seed["original_teacher"].id, start_date=past_friday, end_date=past_friday, reason="hist", status="approved")
    )
    db_session.commit()

    _override_user("principal")
    resp = client.get(
        "/admin/staffing/forecast", params={"school_id": seed["school"].id, "week_start": "2026-08-10"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["school_id"] == seed["school"].id
    assert len(body["forecast"]) == 7
    for day in body["forecast"]:
        assert day["risk_level"] in ("low", "medium", "high")
        assert day["predicted_absences"] >= 0

    persisted = db_session.query(StaffingForecast).filter(StaffingForecast.school_id == seed["school"].id).all()
    assert len(persisted) == 7


# --- GET /admin/staffing/substitute-suggestions ---


def test_substitute_suggestions_for_specific_date(client, seed):
    _override_user("admin")
    resp = client.get(
        "/admin/staffing/substitute-suggestions",
        params={"teacher_id": seed["original_teacher"].id, "date": "2026-08-10", "academic_year": ACADEMIC_YEAR},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["absent_teacher_id"] == seed["original_teacher"].id
    assert len(body["slots"]) == 1
    assert body["slots"][0]["timetable_slot_id"] == seed["slot"].id
    assert body["slots"][0]["suggestions"][0]["teacher_id"] == seed["good_sub"].id


def test_substitute_suggestions_empty_slots_for_day_teacher_does_not_teach(client, seed):
    _override_user("admin")
    resp = client.get(
        "/admin/staffing/substitute-suggestions",
        params={"teacher_id": seed["original_teacher"].id, "date": "2026-08-11", "academic_year": ACADEMIC_YEAR},
    )
    assert resp.status_code == 200
    assert resp.json()["slots"] == []
