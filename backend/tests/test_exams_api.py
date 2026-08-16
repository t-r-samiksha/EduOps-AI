import uuid
from datetime import date, timedelta, time

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.exams import Exam, ExamRoomAssignment, InvigilationAssignment, SeatingAssignment
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest
from app.models.subject import Subject
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int = 999, school_id: int | None = None):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role, school_id=school_id)

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_user_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _make_user(db_session, role_row, prefix, school):
    email = f"{prefix}-{uuid.uuid4()}@example.com"
    user = User(supabase_id=uuid.uuid4(), email=email, full_name=prefix, role_id=role_row.id, school_id=school.id)
    db_session.add(user)
    db_session.flush()
    return user


EXAM_DATE = date.today() + timedelta(days=14)


@pytest.fixture()
def seed(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()

    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    busy_teacher = _make_user(db_session, teacher_role, "busy-teacher", school)
    leave_teacher = _make_user(db_session, teacher_role, "leave-teacher", school)
    free_teacher = _make_user(db_session, teacher_role, "free-teacher", school)
    free_teacher2 = _make_user(db_session, teacher_role, "free-teacher-2", school)
    student1 = _make_user(db_session, student_role, "s1", school)
    student2 = _make_user(db_session, student_role, "s2", school)

    subject = Subject(name="Math", school_id=school.id)
    db_session.add(subject)
    db_session.flush()

    room1 = Room(name="R1", capacity=1, room_type="classroom", school_id=school.id)
    room2 = Room(name="R2", capacity=1, room_type="classroom", school_id=school.id)
    db_session.add_all([room1, room2])
    db_session.flush()

    school_class = SchoolClass(name="8A", academic_year=ACADEMIC_YEAR, school_id=school.id)
    db_session.add(school_class)
    db_session.flush()

    db_session.add_all(
        [
            Enrollment(student_id=student1.id, class_id=school_class.id, subject_id=None, is_primary=True),
            Enrollment(student_id=student2.id, class_id=school_class.id, subject_id=None, is_primary=True),
        ]
    )

    exam_weekday = EXAM_DATE.weekday()
    exam_start, exam_end = time(9, 0), time(11, 0)

    # busy_teacher is genuinely teaching an overlapping slot at the exam's exact
    # day-of-week/time - must be excluded from invigilation.
    db_session.add(
        TimetableSlot(
            day_of_week=exam_weekday, period_number=0, start_time=time(9, 30), end_time=time(10, 15),
            subject_id=subject.id, teacher_id=busy_teacher.id, class_id=school_class.id, room_id=room1.id,
            academic_year=ACADEMIC_YEAR, is_active=True,
        )
    )
    # leave_teacher is on approved leave covering the exam date.
    db_session.add(
        LeaveRequest(
            teacher_id=leave_teacher.id, start_date=EXAM_DATE - timedelta(days=1), end_date=EXAM_DATE + timedelta(days=1),
            reason="planned leave", status="approved",
        )
    )
    db_session.commit()

    return {
        "school": school, "class": school_class, "subject": subject, "room1": room1, "room2": room2,
        "admin_user": admin_user, "busy_teacher": busy_teacher, "leave_teacher": leave_teacher,
        "free_teacher": free_teacher, "free_teacher2": free_teacher2,
        "student1": student1, "student2": student2, "exam_weekday": exam_weekday, "exam_start": exam_start, "exam_end": exam_end,
    }


@pytest.fixture()
def exam(db_session, seed):
    e = Exam(
        school_id=seed["school"].id, subject_id=seed["subject"].id, class_id=seed["class"].id, academic_year=ACADEMIC_YEAR,
        exam_date=EXAM_DATE, start_time=seed["exam_start"], end_time=seed["exam_end"], total_marks=100,
    )
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    return e


# --- RBAC ---


def test_create_exam_401_without_token(client):
    resp = client.post("/admin/exams", json={})
    assert resp.status_code == 401


def test_create_exam_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/exams", json={})
    assert resp.status_code == 403


def test_generate_schedules_401_without_token(client):
    resp = client.post("/admin/exams/1/schedules", json={"rooms": []})
    assert resp.status_code == 401


def test_generate_schedules_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/exams/1/schedules", json={"rooms": []})
    assert resp.status_code == 403


def test_seating_401_without_token(client):
    resp = client.get("/admin/exams/seating")
    assert resp.status_code == 401


def test_seating_403_for_parent_role(client):
    _override_user("parent")
    resp = client.get("/admin/exams/seating")
    assert resp.status_code == 403


def test_invigilations_me_401_without_token(client):
    resp = client.get("/admin/exams/invigilations/me")
    assert resp.status_code == 401


def test_invigilations_me_403_for_student_role(client):
    _override_user("student")
    resp = client.get("/admin/exams/invigilations/me")
    assert resp.status_code == 403


# --- POST /admin/exams ---


def test_create_exam_succeeds(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        "/admin/exams",
        json={
            "school_id": seed["school"].id, "subject_id": seed["subject"].id, "class_id": seed["class"].id,
            "academic_year": ACADEMIC_YEAR, "exam_date": str(EXAM_DATE), "start_time": "09:00:00", "end_time": "11:00:00", "total_marks": 100,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["total_marks"] == 100


def test_create_exam_rejects_bad_times(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        "/admin/exams",
        json={
            "school_id": seed["school"].id, "subject_id": seed["subject"].id, "class_id": seed["class"].id,
            "academic_year": ACADEMIC_YEAR, "exam_date": str(EXAM_DATE), "start_time": "11:00:00", "end_time": "09:00:00",
        },
    )
    assert resp.status_code == 400


def test_create_exam_404_for_missing_subject(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        "/admin/exams",
        json={
            "school_id": seed["school"].id, "subject_id": 999999, "class_id": seed["class"].id,
            "academic_year": ACADEMIC_YEAR, "exam_date": str(EXAM_DATE), "start_time": "09:00:00", "end_time": "11:00:00",
        },
    )
    assert resp.status_code == 404


def test_create_exam_returns_clean_400_for_unknown_school_id(client, seed):
    """Regression test: subject_id/class_id were validated but school_id wasn't -
    a bogus school_id used to reach the INSERT and raise an unhandled
    IntegrityError (see the reliability audit's finding). Overrides the caller's
    own school_id to the same bogus value too - otherwise this session's added
    cross-tenant check (body.school_id != user.school_id) would reject it with a
    403 before ever reaching the "does this school exist" check this test targets."""
    _override_user("admin", user_id=seed["admin_user"].id, school_id=999999999)
    resp = client.post(
        "/admin/exams",
        json={
            "school_id": 999999999, "subject_id": seed["subject"].id, "class_id": seed["class"].id,
            "academic_year": ACADEMIC_YEAR, "exam_date": str(EXAM_DATE), "start_time": "09:00:00", "end_time": "11:00:00",
        },
    )
    assert resp.status_code == 400


# --- Cross-tenant scoping (regression: found live against real data during this
# session's own walkthrough - an admin from one school could see, and could have
# overwritten, another school's real exam) ---


@pytest.fixture()
def other_school_exam(db_session):
    other_school = School(name="Other School")
    db_session.add(other_school)
    db_session.flush()
    other_class = SchoolClass(name="9Z", academic_year=ACADEMIC_YEAR, school_id=other_school.id)
    db_session.add(other_class)
    db_session.flush()
    other_subject = Subject(name="Other Subject", school_id=other_school.id)
    db_session.add(other_subject)
    db_session.flush()
    e = Exam(
        school_id=other_school.id, subject_id=other_subject.id, class_id=other_class.id, academic_year=ACADEMIC_YEAR,
        exam_date=EXAM_DATE, start_time=time(9, 0), end_time=time(11, 0),
    )
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    return {"school": other_school, "class": other_class, "subject": other_subject, "exam": e}


def test_create_exam_403_for_a_different_school(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        "/admin/exams",
        json={
            "school_id": 999999999, "subject_id": seed["subject"].id, "class_id": seed["class"].id,
            "academic_year": ACADEMIC_YEAR, "exam_date": str(EXAM_DATE), "start_time": "09:00:00", "end_time": "11:00:00",
        },
    )
    assert resp.status_code == 403


def test_list_exams_does_not_leak_another_schools_exams(client, seed, exam, other_school_exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams")
    ids = {i["id"] for i in resp.json()["items"]}
    assert exam.id in ids
    assert other_school_exam["exam"].id not in ids


def test_generate_schedules_404_for_another_schools_exam(client, seed, other_school_exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(f"/admin/exams/{other_school_exam['exam'].id}/schedules", json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}]})
    assert resp.status_code == 404


def test_room_suggestions_404_for_another_schools_exam(client, seed, other_school_exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get(f"/admin/exams/{other_school_exam['exam'].id}/room-suggestions")
    assert resp.status_code == 404


def test_seating_does_not_leak_another_schools_seating(client, db_session, seed, generated_exam, other_school_exam):
    other_student = _make_user(db_session, db_session.query(Role).filter(Role.name == "student").one(), "other-student", other_school_exam["school"])
    db_session.add(SeatingAssignment(exam_id=other_school_exam["exam"].id, student_id=other_student.id, room_id=seed["room1"].id, seat_no=1))
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams/seating")
    ids = {i["student_id"] for i in resp.json()["items"]}
    assert other_student.id not in ids


# --- POST /admin/exams/{id}/schedules: 3-tier invigilator priority, end to end ---


def test_regular_period_teacher_for_this_class_is_preferred_over_unrelated_free_teachers(client, db_session, seed, exam):
    """Grade 1-B English exam, and there's a Social Studies period for that exact
    class at that exact slot - that Social Studies teacher should be picked over
    free_teacher/free_teacher2, who have no connection to this class at all."""
    social_studies = Subject(name="Social Studies", school_id=seed["school"].id)
    db_session.add(social_studies)
    db_session.flush()
    regular_teacher = _make_user(db_session, db_session.query(Role).filter(Role.name == "teacher").one(), "regular-period-teacher", seed["school"])
    db_session.add(
        TimetableSlot(
            day_of_week=seed["exam_weekday"], period_number=0, start_time=seed["exam_start"], end_time=seed["exam_end"],
            subject_id=social_studies.id, teacher_id=regular_teacher.id, class_id=seed["class"].id, room_id=seed["room2"].id,
            academic_year=ACADEMIC_YEAR, is_active=True,
        )
    )
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(f"/admin/exams/{exam.id}/schedules", json={"rooms": [{"room_id": seed["room1"].id, "capacity": 2}]})
    assert resp.status_code == 200
    assert resp.json()["invigilators"][0]["teacher_id"] == regular_teacher.id


def test_subject_teacher_used_as_last_resort_when_no_one_else_is_eligible(client, db_session, seed, exam):
    """With free_teacher/free_teacher2/leave_teacher all unavailable, busy_teacher
    (this exam's own subject's regular teacher for this class) is the only one
    left - correctly used rather than leaving the room unassigned."""
    db_session.add_all(
        [
            LeaveRequest(teacher_id=seed["free_teacher"].id, start_date=EXAM_DATE, end_date=EXAM_DATE, reason="x", status="approved"),
            LeaveRequest(teacher_id=seed["free_teacher2"].id, start_date=EXAM_DATE, end_date=EXAM_DATE, reason="x", status="approved"),
        ]
    )
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(f"/admin/exams/{exam.id}/schedules", json={"rooms": [{"room_id": seed["room1"].id, "capacity": 2}]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["invigilators"][0]["teacher_id"] == seed["busy_teacher"].id
    assert body["unassigned_rooms"] == []


# --- POST /admin/exams/{id}/schedules: real feasibility proof ---


def test_generate_schedules_produces_feasible_seating_and_invigilation(client, db_session, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        f"/admin/exams/{exam.id}/schedules",
        json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "generated"

    # Seating: both students seated, no double-booking.
    assert {s["student_id"] for s in body["seating"]} == {seed["student1"].id, seed["student2"].id}
    seat_keys = [(s["room_id"], s["seat_no"]) for s in body["seating"]]
    assert len(seat_keys) == len(set(seat_keys))

    # Invigilation: leave_teacher must NOT be assigned (real LeaveRequest
    # conflict). busy_teacher's only "conflict" is teaching this exact class this
    # exact subject at this exact slot - not a real conflict anymore (that period
    # IS the exam), but they ARE this exam's own subject teacher, so they're
    # last-resort and still correctly skipped while both free teachers exist.
    assigned_teacher_ids = {i["teacher_id"] for i in body["invigilators"] if i["teacher_id"] is not None}
    assert seed["busy_teacher"].id not in assigned_teacher_ids
    assert seed["leave_teacher"].id not in assigned_teacher_ids
    assert assigned_teacher_ids == {seed["free_teacher"].id, seed["free_teacher2"].id}
    assert body["unassigned_rooms"] == []

    # Persisted rows match the response.
    persisted_seats = db_session.query(SeatingAssignment).filter(SeatingAssignment.exam_id == exam.id).all()
    assert len(persisted_seats) == 2
    persisted_invigilations = db_session.query(InvigilationAssignment).filter(InvigilationAssignment.exam_id == exam.id).all()
    assert all(inv.status == "assigned" for inv in persisted_invigilations)


def test_generate_schedules_honestly_reports_unassigned_room_when_no_teachers_available(client, db_session, seed, exam):
    # Remove both genuinely-free teachers by also putting them on leave. Also put
    # busy_teacher on leave: their only "conflict" is teaching this exact class/
    # subject at this exact slot, which the 3-tier priority now exempts from
    # "busy" and would otherwise make them a last-resort candidate - this test's
    # intent is genuinely zero eligible invigilators, so exclude them for real.
    db_session.add_all(
        [
            LeaveRequest(teacher_id=seed["free_teacher"].id, start_date=EXAM_DATE, end_date=EXAM_DATE, reason="x", status="approved"),
            LeaveRequest(teacher_id=seed["free_teacher2"].id, start_date=EXAM_DATE, end_date=EXAM_DATE, reason="x", status="approved"),
            LeaveRequest(teacher_id=seed["busy_teacher"].id, start_date=EXAM_DATE, end_date=EXAM_DATE, reason="x", status="approved"),
        ]
    )
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        f"/admin/exams/{exam.id}/schedules",
        json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["unassigned_rooms"]) == {seed["room1"].id, seed["room2"].id}
    assert all(i["teacher_id"] is None for i in body["invigilators"])


def test_generate_schedules_rejects_insufficient_capacity(client, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(f"/admin/exams/{exam.id}/schedules", json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}]})
    assert resp.status_code == 422  # 2 students, only 1 seat


def test_generate_schedules_404_for_missing_exam(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post("/admin/exams/999999/schedules", json={"rooms": [{"room_id": seed["room1"].id, "capacity": 5}]})
    assert resp.status_code == 404


def test_generate_schedules_rejects_empty_rooms(client, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(f"/admin/exams/{exam.id}/schedules", json={"rooms": []})
    assert resp.status_code == 400


def test_regenerating_schedules_supersedes_not_duplicates(client, db_session, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    body = {"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}]}
    client.post(f"/admin/exams/{exam.id}/schedules", json=body)
    client.post(f"/admin/exams/{exam.id}/schedules", json=body)

    seats = db_session.query(SeatingAssignment).filter(SeatingAssignment.exam_id == exam.id).all()
    assert len(seats) == 2  # not 4


# --- GET /admin/exams/seating: student scoping ---


@pytest.fixture()
def generated_exam(client, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    client.post(
        f"/admin/exams/{exam.id}/schedules",
        json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}]},
    )
    return exam


def test_student_sees_only_their_own_seat(client, seed, generated_exam):
    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams/seating", params={"exam_id": generated_exam.id})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["student_id"] == seed["student1"].id


def test_student_cannot_see_another_students_seat_via_student_id_param(client, seed, generated_exam):
    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams/seating", params={"exam_id": generated_exam.id, "student_id": seed["student2"].id})
    # student_id param is ignored for the student role - still only their own seat.
    items = resp.json()["items"]
    assert all(i["student_id"] == seed["student1"].id for i in items)
    assert not any(i["student_id"] == seed["student2"].id for i in items)


def test_admin_can_see_any_students_seat(client, seed, generated_exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams/seating", params={"exam_id": generated_exam.id, "student_id": seed["student2"].id})
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["student_id"] == seed["student2"].id


def test_teacher_can_view_seating_for_an_exam(client, seed, generated_exam):
    _override_user("teacher", user_id=seed["free_teacher"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams/seating", params={"exam_id": generated_exam.id})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


def test_seating_includes_exam_details_and_invigilator_name(client, seed, generated_exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams/seating", params={"exam_id": generated_exam.id})
    items = resp.json()["items"]
    assert len(items) == 2
    for item in items:
        assert item["subject_id"] == seed["subject"].id
        assert item["subject_name"] == seed["subject"].name
        assert item["class_id"] == seed["class"].id
        assert item["class_name"] == seed["class"].name
        assert item["exam_date"] == str(EXAM_DATE)
        # generated_exam splits 2 students across 2 separate 1-seat rooms, each
        # with its own invigilator - every row's own room must have one assigned.
        assert item["invigilator_teacher_id"] is not None
        assert item["invigilator_name"]


def test_seating_invigilator_name_is_null_when_a_room_has_no_invigilator(client, db_session, seed, exam):
    # Only one eligible teacher for two rooms - the second room's invigilator is
    # genuinely null, and that must come through honestly here too.
    db_session.add_all(
        [
            LeaveRequest(teacher_id=seed["free_teacher2"].id, start_date=EXAM_DATE, end_date=EXAM_DATE, reason="x", status="approved"),
            LeaveRequest(teacher_id=seed["busy_teacher"].id, start_date=EXAM_DATE, end_date=EXAM_DATE, reason="x", status="approved"),
        ]
    )
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    client.post(
        f"/admin/exams/{exam.id}/schedules",
        json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}]},
    )
    resp = client.get("/admin/exams/seating", params={"exam_id": exam.id})
    items = resp.json()["items"]
    assert len(items) == 2
    null_invigilator_items = [i for i in items if i["invigilator_teacher_id"] is None]
    assert len(null_invigilator_items) == 1
    assert null_invigilator_items[0]["invigilator_name"] is None


# --- GET /admin/exams/invigilations/me ---


def test_invigilator_sees_only_their_own_duties(client, db_session, seed, generated_exam):
    # Whichever teacher actually got assigned (free_teacher, deterministically -
    # busy/leave teachers are excluded) should see exactly their own duty.
    assignment = db_session.query(InvigilationAssignment).filter(InvigilationAssignment.exam_id == generated_exam.id).first()
    assert assignment is not None

    _override_user("teacher", user_id=assignment.teacher_id, school_id=seed["school"].id)
    resp = client.get("/admin/exams/invigilations/me")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert all(d["exam_id"] == generated_exam.id for d in body)
    assert body[0]["class_name"] == seed["class"].name


def test_teacher_with_no_duties_sees_empty_list(client, seed, generated_exam):
    # busy_teacher was excluded from invigilation (their timetable slot conflicts).
    _override_user("teacher", user_id=seed["busy_teacher"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams/invigilations/me")
    assert resp.status_code == 200
    assert all(d["exam_id"] != generated_exam.id for d in resp.json())


# --- GET /admin/exams: list ---


def test_list_exams_401_without_token(client):
    resp = client.get("/admin/exams")
    assert resp.status_code == 401


def test_list_exams_403_for_parent_role(client):
    _override_user("parent")
    resp = client.get("/admin/exams")
    assert resp.status_code == 403


def test_list_exams_returns_created_exam(client, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams")
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert exam.id in ids  # own fixture id present, not a global-count assertion

    item = next(i for i in body["items"] if i["id"] == exam.id)
    assert item["subject_id"] == seed["subject"].id
    assert item["class_id"] == seed["class"].id
    assert item["academic_year"] == ACADEMIC_YEAR
    assert item["exam_date"] == str(EXAM_DATE)


def test_list_exams_filters_by_class_subject_academic_year(client, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)

    resp = client.get("/admin/exams", params={"class_id": seed["class"].id})
    assert exam.id in {i["id"] for i in resp.json()["items"]}

    resp = client.get("/admin/exams", params={"class_id": 999999})
    assert exam.id not in {i["id"] for i in resp.json()["items"]}

    resp = client.get("/admin/exams", params={"subject_id": seed["subject"].id})
    assert exam.id in {i["id"] for i in resp.json()["items"]}

    resp = client.get("/admin/exams", params={"academic_year": "2099-00"})
    assert exam.id not in {i["id"] for i in resp.json()["items"]}


def test_list_exams_paginates(client, db_session, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    exam_ids = []
    for i in range(3):
        e = Exam(
            school_id=seed["school"].id, subject_id=seed["subject"].id, class_id=seed["class"].id,
            academic_year=ACADEMIC_YEAR, exam_date=EXAM_DATE + timedelta(days=i),
            start_time=seed["exam_start"], end_time=seed["exam_end"],
        )
        db_session.add(e)
        db_session.flush()
        exam_ids.append(e.id)
    db_session.commit()

    resp = client.get("/admin/exams", params={"class_id": seed["class"].id, "page": 1, "page_size": 2})
    body = resp.json()
    assert resp.status_code == 200
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    assert body["total"] >= 3

    seen_ids = set()
    page = 1
    while len(seen_ids) < body["total"] and page <= body["total"]:
        page_resp = client.get("/admin/exams", params={"class_id": seed["class"].id, "page": page, "page_size": 2})
        items = page_resp.json()["items"]
        if not items:
            break
        seen_ids.update(i["id"] for i in items)
        page += 1
    assert set(exam_ids) <= seen_ids


def test_list_exams_rejects_invalid_pagination(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams", params={"page": 0})
    assert resp.status_code == 400
    resp = client.get("/admin/exams", params={"page_size": 0})
    assert resp.status_code == 400


def test_student_sees_only_their_own_class_exams(client, db_session, seed, exam):
    other_class = SchoolClass(name="8B", academic_year=ACADEMIC_YEAR, school_id=seed["school"].id)
    db_session.add(other_class)
    db_session.flush()
    other_exam = Exam(
        school_id=seed["school"].id, subject_id=seed["subject"].id, class_id=other_class.id,
        academic_year=ACADEMIC_YEAR, exam_date=EXAM_DATE, start_time=seed["exam_start"], end_time=seed["exam_end"],
    )
    db_session.add(other_exam)
    db_session.commit()

    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams")
    assert resp.status_code == 200
    ids = {i["id"] for i in resp.json()["items"]}
    assert exam.id in ids  # their own class's exam
    assert other_exam.id not in ids  # a different class's exam


def test_student_with_no_enrollment_sees_empty_list(client, db_session, seed, exam):
    unenrolled = _make_user(db_session, db_session.query(Role).filter(Role.name == "student").one(), "unenrolled", seed["school"])
    db_session.commit()

    _override_user("student", user_id=unenrolled.id, school_id=seed["school"].id)
    resp = client.get("/admin/exams")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# --- exam_type ---


def test_create_exam_accepts_a_valid_exam_type(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        "/admin/exams",
        json={
            "school_id": seed["school"].id, "subject_id": seed["subject"].id, "class_id": seed["class"].id,
            "academic_year": ACADEMIC_YEAR, "exam_type": "mid_term", "exam_date": str(EXAM_DATE),
            "start_time": "09:00:00", "end_time": "11:00:00",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["exam_type"] == "mid_term"


def test_create_exam_rejects_an_unknown_exam_type(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        "/admin/exams",
        json={
            "school_id": seed["school"].id, "subject_id": seed["subject"].id, "class_id": seed["class"].id,
            "academic_year": ACADEMIC_YEAR, "exam_type": "pop_quiz", "exam_date": str(EXAM_DATE),
            "start_time": "09:00:00", "end_time": "11:00:00",
        },
    )
    assert resp.status_code == 400


def test_create_exam_allows_omitting_exam_type(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        "/admin/exams",
        json={
            "school_id": seed["school"].id, "subject_id": seed["subject"].id, "class_id": seed["class"].id,
            "academic_year": ACADEMIC_YEAR, "exam_date": str(EXAM_DATE), "start_time": "09:00:00", "end_time": "11:00:00",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["exam_type"] is None


# --- POST /admin/exams/bulk-by-grade ---


@pytest.fixture()
def grade_seed(db_session, seed):
    """A second Grade-8 section alongside seed["class"] (renamed 8A implicitly via
    grade_level) so bulk-by-grade has more than one section to fan out across."""
    seed["class"].grade_level = 8
    class_b = SchoolClass(name="8B", academic_year=ACADEMIC_YEAR, grade_level=8, school_id=seed["school"].id, is_active=True)
    db_session.add(class_b)
    db_session.commit()
    db_session.refresh(class_b)
    return {**seed, "class_b": class_b}


def test_bulk_create_makes_one_exam_per_active_section_in_the_grade(client, grade_seed):
    _override_user("admin", user_id=grade_seed["admin_user"].id, school_id=grade_seed["school"].id)
    resp = client.post(
        "/admin/exams/bulk-by-grade",
        json={
            "school_id": grade_seed["school"].id, "subject_id": grade_seed["subject"].id, "grade_level": 8,
            "academic_year": ACADEMIC_YEAR, "exam_type": "unit_test", "exam_date": str(EXAM_DATE),
            "start_time": "09:00:00", "end_time": "11:00:00",
        },
    )
    assert resp.status_code == 200
    created = resp.json()["created"]
    class_ids = {e["class_id"] for e in created}
    assert class_ids == {grade_seed["class"].id, grade_seed["class_b"].id}
    assert all(e["exam_type"] == "unit_test" for e in created)


def test_bulk_create_404_when_grade_has_no_active_class(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        "/admin/exams/bulk-by-grade",
        json={
            "school_id": seed["school"].id, "subject_id": seed["subject"].id, "grade_level": 99,
            "academic_year": ACADEMIC_YEAR, "exam_date": str(EXAM_DATE), "start_time": "09:00:00", "end_time": "11:00:00",
        },
    )
    assert resp.status_code == 404


def test_bulk_create_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/exams/bulk-by-grade", json={})
    assert resp.status_code == 403


# --- GET /admin/exams/{id}/room-suggestions ---


def test_room_suggestions_prefers_smallest_single_room_that_fits(client, db_session, seed, exam):
    big_room = Room(name="Hall", capacity=50, room_type="classroom", school_id=seed["school"].id)
    db_session.add(big_room)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get(f"/admin/exams/{exam.id}/room-suggestions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["headcount"] == 2  # student1 + student2
    room_ids = {r["room_id"] for r in body["available_rooms"]}
    assert {seed["room1"].id, seed["room2"].id, big_room.id} <= room_ids
    # room1/room2 both have capacity 1 (too small for headcount=2); big_room (50) is
    # the only single room that fits everyone, and it's the smallest such room.
    assert body["suggested_room_ids"] == [big_room.id]


def test_room_suggestions_excludes_a_room_already_booked_for_an_overlapping_exam(client, db_session, seed, exam):
    other_class = SchoolClass(name="8C", academic_year=ACADEMIC_YEAR, school_id=seed["school"].id)
    db_session.add(other_class)
    db_session.flush()
    other_exam = Exam(
        school_id=seed["school"].id, subject_id=seed["subject"].id, class_id=other_class.id, academic_year=ACADEMIC_YEAR,
        exam_date=EXAM_DATE, start_time=seed["exam_start"], end_time=seed["exam_end"],
    )
    db_session.add(other_exam)
    db_session.flush()
    db_session.add(ExamRoomAssignment(exam_id=other_exam.id, room_id=seed["room1"].id, capacity=1))
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get(f"/admin/exams/{exam.id}/room-suggestions")
    available_ids = {r["room_id"] for r in resp.json()["available_rooms"]}
    assert seed["room1"].id not in available_ids
    assert seed["room2"].id in available_ids


def test_room_suggestions_404_for_unknown_exam(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams/999999/room-suggestions")
    assert resp.status_code == 404


# --- dry_run / HITL preview ---


def test_generate_schedules_dry_run_persists_nothing(client, db_session, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        f"/admin/exams/{exam.id}/schedules",
        json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}], "dry_run": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "preview"
    assert {s["student_id"] for s in body["seating"]} == {seed["student1"].id, seed["student2"].id}

    assert db_session.query(SeatingAssignment).filter(SeatingAssignment.exam_id == exam.id).count() == 0
    assert db_session.query(InvigilationAssignment).filter(InvigilationAssignment.exam_id == exam.id).count() == 0


def test_generate_schedules_confirm_after_dry_run_persists_the_same_result(client, db_session, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    body = {"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}]}

    preview = client.post(f"/admin/exams/{exam.id}/schedules", json={**body, "dry_run": True}).json()
    confirm = client.post(f"/admin/exams/{exam.id}/schedules", json={**body, "dry_run": False}).json()

    assert confirm["status"] == "generated"
    assert confirm["seating"] == preview["seating"]
    assert confirm["invigilators"] == preview["invigilators"]
    assert db_session.query(SeatingAssignment).filter(SeatingAssignment.exam_id == exam.id).count() == 2


def test_generate_schedules_defaults_to_persisting_when_dry_run_omitted(client, db_session, seed, exam):
    """Backward compatibility: every caller that predates dry_run (including every
    other test in this file) must keep getting the old immediate-persist behavior."""
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        f"/admin/exams/{exam.id}/schedules",
        json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}]},
    )
    assert resp.json()["status"] == "generated"
    assert db_session.query(SeatingAssignment).filter(SeatingAssignment.exam_id == exam.id).count() == 2


# --- GET /admin/exams/seating: student sees the full room, not just their own seat ---


def test_student_sees_every_seat_in_their_own_room_not_just_their_own(client, db_session, seed, exam):
    # Both students seated in the SAME single room this time (capacity 2).
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    client.post(f"/admin/exams/{exam.id}/schedules", json={"rooms": [{"room_id": seed["room1"].id, "capacity": 2}]})

    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams/seating", params={"exam_id": exam.id})
    items = resp.json()["items"]
    assert {i["student_id"] for i in items} == {seed["student1"].id, seed["student2"].id}


def test_student_does_not_see_a_different_rooms_occupants(client, db_session, seed, exam):
    # Back to 2 separate 1-seat rooms - student1 and student2 end up in different
    # rooms, so student1 must see only their own seat (no other room to leak).
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    client.post(
        f"/admin/exams/{exam.id}/schedules",
        json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}]},
    )

    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams/seating", params={"exam_id": exam.id})
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["student_id"] == seed["student1"].id


def test_teacher_sees_only_exams_for_classes_they_actually_teach(client, seed, exam):
    # busy_teacher has a real active TimetableSlot for (seed["class"], seed["subject"])
    # per the seed fixture - the exam's own (class_id, subject_id) pair.
    _override_user("teacher", user_id=seed["busy_teacher"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams")
    assert resp.status_code == 200
    assert exam.id in {i["id"] for i in resp.json()["items"]}

    # free_teacher has no TimetableSlot at all in the seed - shouldn't see it.
    _override_user("teacher", user_id=seed["free_teacher"].id, school_id=seed["school"].id)
    resp = client.get("/admin/exams")
    assert resp.status_code == 200
    assert exam.id not in {i["id"] for i in resp.json()["items"]}
