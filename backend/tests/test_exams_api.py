import uuid
from datetime import date, timedelta, time

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.exams import Exam, InvigilationAssignment, SeatingAssignment
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest
from app.models.subject import Subject
from app.models.timetable import Room, TimetableSlot
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
    _override_user("admin", user_id=seed["admin_user"].id)
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
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        "/admin/exams",
        json={
            "school_id": seed["school"].id, "subject_id": seed["subject"].id, "class_id": seed["class"].id,
            "academic_year": ACADEMIC_YEAR, "exam_date": str(EXAM_DATE), "start_time": "11:00:00", "end_time": "09:00:00",
        },
    )
    assert resp.status_code == 400


def test_create_exam_404_for_missing_subject(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        "/admin/exams",
        json={
            "school_id": seed["school"].id, "subject_id": 999999, "class_id": seed["class"].id,
            "academic_year": ACADEMIC_YEAR, "exam_date": str(EXAM_DATE), "start_time": "09:00:00", "end_time": "11:00:00",
        },
    )
    assert resp.status_code == 404


# --- POST /admin/exams/{id}/schedules: real feasibility proof ---


def test_generate_schedules_produces_feasible_seating_and_invigilation(client, db_session, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id)
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

    # Invigilation: busy_teacher and leave_teacher must NOT be assigned (real
    # TimetableSlot/LeaveRequest conflicts); both free teachers cover the 2 rooms.
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
    # Remove both genuinely-free teachers by also putting them on leave, leaving
    # zero eligible invigilators for either room.
    db_session.add_all(
        [
            LeaveRequest(teacher_id=seed["free_teacher"].id, start_date=EXAM_DATE, end_date=EXAM_DATE, reason="x", status="approved"),
            LeaveRequest(teacher_id=seed["free_teacher2"].id, start_date=EXAM_DATE, end_date=EXAM_DATE, reason="x", status="approved"),
        ]
    )
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        f"/admin/exams/{exam.id}/schedules",
        json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["unassigned_rooms"]) == {seed["room1"].id, seed["room2"].id}
    assert all(i["teacher_id"] is None for i in body["invigilators"])


def test_generate_schedules_rejects_insufficient_capacity(client, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/exams/{exam.id}/schedules", json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}]})
    assert resp.status_code == 422  # 2 students, only 1 seat


def test_generate_schedules_404_for_missing_exam(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/admin/exams/999999/schedules", json={"rooms": [{"room_id": seed["room1"].id, "capacity": 5}]})
    assert resp.status_code == 404


def test_generate_schedules_rejects_empty_rooms(client, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/exams/{exam.id}/schedules", json={"rooms": []})
    assert resp.status_code == 400


def test_regenerating_schedules_supersedes_not_duplicates(client, db_session, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id)
    body = {"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}]}
    client.post(f"/admin/exams/{exam.id}/schedules", json=body)
    client.post(f"/admin/exams/{exam.id}/schedules", json=body)

    seats = db_session.query(SeatingAssignment).filter(SeatingAssignment.exam_id == exam.id).all()
    assert len(seats) == 2  # not 4


# --- GET /admin/exams/seating: student scoping ---


@pytest.fixture()
def generated_exam(client, seed, exam):
    _override_user("admin", user_id=seed["admin_user"].id)
    client.post(
        f"/admin/exams/{exam.id}/schedules",
        json={"rooms": [{"room_id": seed["room1"].id, "capacity": 1}, {"room_id": seed["room2"].id, "capacity": 1}]},
    )
    return exam


def test_student_sees_only_their_own_seat(client, seed, generated_exam):
    _override_user("student", user_id=seed["student1"].id)
    resp = client.get("/admin/exams/seating", params={"exam_id": generated_exam.id})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["student_id"] == seed["student1"].id


def test_student_cannot_see_another_students_seat_via_student_id_param(client, seed, generated_exam):
    _override_user("student", user_id=seed["student1"].id)
    resp = client.get("/admin/exams/seating", params={"exam_id": generated_exam.id, "student_id": seed["student2"].id})
    # student_id param is ignored for the student role - still only their own seat.
    items = resp.json()["items"]
    assert all(i["student_id"] == seed["student1"].id for i in items)
    assert not any(i["student_id"] == seed["student2"].id for i in items)


def test_admin_can_see_any_students_seat(client, seed, generated_exam):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/exams/seating", params={"exam_id": generated_exam.id, "student_id": seed["student2"].id})
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["student_id"] == seed["student2"].id


def test_teacher_can_view_seating_for_an_exam(client, seed, generated_exam):
    _override_user("teacher", user_id=seed["free_teacher"].id)
    resp = client.get("/admin/exams/seating", params={"exam_id": generated_exam.id})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


# --- GET /admin/exams/invigilations/me ---


def test_invigilator_sees_only_their_own_duties(client, db_session, seed, generated_exam):
    # Whichever teacher actually got assigned (free_teacher, deterministically -
    # busy/leave teachers are excluded) should see exactly their own duty.
    assignment = db_session.query(InvigilationAssignment).filter(InvigilationAssignment.exam_id == generated_exam.id).first()
    assert assignment is not None

    _override_user("teacher", user_id=assignment.teacher_id)
    resp = client.get("/admin/exams/invigilations/me")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert all(d["exam_id"] == generated_exam.id for d in body)
    assert body[0]["class_name"] == seed["class"].name


def test_teacher_with_no_duties_sees_empty_list(client, seed, generated_exam):
    # busy_teacher was excluded from invigilation (their timetable slot conflicts).
    _override_user("teacher", user_id=seed["busy_teacher"].id)
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
    _override_user("admin", user_id=seed["admin_user"].id)
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
    _override_user("admin", user_id=seed["admin_user"].id)

    resp = client.get("/admin/exams", params={"class_id": seed["class"].id})
    assert exam.id in {i["id"] for i in resp.json()["items"]}

    resp = client.get("/admin/exams", params={"class_id": 999999})
    assert exam.id not in {i["id"] for i in resp.json()["items"]}

    resp = client.get("/admin/exams", params={"subject_id": seed["subject"].id})
    assert exam.id in {i["id"] for i in resp.json()["items"]}

    resp = client.get("/admin/exams", params={"academic_year": "2099-00"})
    assert exam.id not in {i["id"] for i in resp.json()["items"]}


def test_list_exams_paginates(client, db_session, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
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
    _override_user("admin", user_id=seed["admin_user"].id)
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

    _override_user("student", user_id=seed["student1"].id)
    resp = client.get("/admin/exams")
    assert resp.status_code == 200
    ids = {i["id"] for i in resp.json()["items"]}
    assert exam.id in ids  # their own class's exam
    assert other_exam.id not in ids  # a different class's exam


def test_student_with_no_enrollment_sees_empty_list(client, db_session, seed, exam):
    unenrolled = _make_user(db_session, db_session.query(Role).filter(Role.name == "student").one(), "unenrolled", seed["school"])
    db_session.commit()

    _override_user("student", user_id=unenrolled.id)
    resp = client.get("/admin/exams")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_teacher_sees_only_exams_for_classes_they_actually_teach(client, seed, exam):
    # busy_teacher has a real active TimetableSlot for (seed["class"], seed["subject"])
    # per the seed fixture - the exam's own (class_id, subject_id) pair.
    _override_user("teacher", user_id=seed["busy_teacher"].id)
    resp = client.get("/admin/exams")
    assert resp.status_code == 200
    assert exam.id in {i["id"] for i in resp.json()["items"]}

    # free_teacher has no TimetableSlot at all in the seed - shouldn't see it.
    _override_user("teacher", user_id=seed["free_teacher"].id)
    resp = client.get("/admin/exams")
    assert resp.status_code == 200
    assert exam.id not in {i["id"] for i in resp.json()["items"]}
