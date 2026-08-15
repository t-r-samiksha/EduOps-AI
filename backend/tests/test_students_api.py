import uuid
from unittest.mock import patch

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user


def _override_user(role: str, user_id: int = 999):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role)

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_user_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def seed(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()
    school_class = SchoolClass(name="Grade 5 - A", academic_year="2026-27", grade_level=5, section="A", school_id=school.id)
    class_b = SchoolClass(name="Grade 5 - B", academic_year="2026-27", grade_level=5, section="B", school_id=school.id)
    db_session.add_all([school_class, class_b])
    db_session.commit()
    db_session.refresh(school_class)
    db_session.refresh(class_b)
    return {"school": school, "class": school_class, "class_b": class_b}


@pytest.fixture()
def existing_student(db_session, seed):
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    student = User(
        supabase_id=uuid.uuid4(), email=f"s-{uuid.uuid4()}@example.com", full_name="Existing Student",
        role_id=student_role.id, school_id=seed["school"].id,
    )
    db_session.add(student)
    db_session.flush()
    db_session.add(Enrollment(student_id=student.id, class_id=seed["class"].id, subject_id=None, is_primary=True))
    db_session.commit()
    db_session.refresh(student)
    return student


def test_create_student_returns_401_without_token(client):
    resp = client.post("/admin/students", json={"school_id": 1, "email": "a@b.com", "password": "x"})
    assert resp.status_code == 401


def test_create_student_returns_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/students", json={"school_id": 1, "email": "a@b.com", "password": "x"})
    assert resp.status_code == 403


def test_create_student_with_class_enrolls_immediately(client, db_session, seed):
    _override_user("admin")
    fake_supabase_id = uuid.uuid4()
    with patch("app.routers.students.create_auth_account", return_value=fake_supabase_id) as mock_create:
        resp = client.post(
            "/admin/students",
            json={
                "school_id": seed["school"].id, "email": "priya@example.com", "password": "Sup3rSecret!",
                "full_name": "Priya Sharma", "class_id": seed["class"].id,
            },
        )
    mock_create.assert_called_once_with(email="priya@example.com", password="Sup3rSecret!", full_name="Priya Sharma", role="student")
    assert resp.status_code == 201
    body = resp.json()
    assert body["class_id"] == seed["class"].id
    assert body["school_id"] == seed["school"].id

    enrollment = db_session.query(Enrollment).filter(Enrollment.student_id == body["id"]).one()
    assert enrollment.class_id == seed["class"].id
    assert enrollment.is_primary is True


def test_create_student_without_class_id_leaves_unenrolled(client, seed):
    _override_user("admin")
    with patch("app.routers.students.create_auth_account", return_value=uuid.uuid4()):
        resp = client.post(
            "/admin/students", json={"school_id": seed["school"].id, "email": "noclass@example.com", "password": "Sup3rSecret!"}
        )
    assert resp.status_code == 201
    assert resp.json()["class_id"] is None


def test_create_student_returns_400_for_unknown_school_id_without_calling_supabase(client):
    _override_user("admin")
    with patch("app.routers.students.create_auth_account") as mock_create:
        resp = client.post("/admin/students", json={"school_id": 999999999, "email": "a@b.com", "password": "x"})
    assert resp.status_code == 400
    mock_create.assert_not_called()


def test_create_student_returns_400_for_unknown_class_id_without_calling_supabase(client, seed):
    _override_user("admin")
    with patch("app.routers.students.create_auth_account") as mock_create:
        resp = client.post(
            "/admin/students",
            json={"school_id": seed["school"].id, "email": "a@b.com", "password": "x", "class_id": 999999999},
        )
    assert resp.status_code == 400
    mock_create.assert_not_called()


def test_create_student_returns_409_for_duplicate_email_without_calling_supabase(client, db_session, seed):
    with patch("app.routers.students.create_auth_account", return_value=uuid.uuid4()):
        _override_user("admin")
        client.post("/admin/students", json={"school_id": seed["school"].id, "email": "dup@example.com", "password": "Sup3rSecret!"})

    with patch("app.routers.students.create_auth_account") as mock_create:
        resp = client.post("/admin/students", json={"school_id": seed["school"].id, "email": "dup@example.com", "password": "Sup3rSecret!"})
    assert resp.status_code == 409
    mock_create.assert_not_called()


# --- GET /admin/students (list) ------------------------------------------------


def test_list_students_returns_401_without_token(client):
    resp = client.get("/admin/students", params={"school_id": 1})
    assert resp.status_code == 401


def test_list_students_returns_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/admin/students", params={"school_id": 1})
    assert resp.status_code == 403


def test_list_students_returns_only_active_by_default(client, db_session, seed, existing_student):
    other = User(
        supabase_id=uuid.uuid4(), email=f"inactive-{uuid.uuid4()}@example.com",
        role_id=existing_student.role_id, school_id=seed["school"].id, is_active=False,
    )
    db_session.add(other)
    db_session.commit()

    _override_user("admin")
    resp = client.get("/admin/students", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    ids = {s["id"] for s in resp.json()}
    assert existing_student.id in ids
    assert other.id not in ids

    resp_all = client.get("/admin/students", params={"school_id": seed["school"].id, "include_inactive": True})
    ids_all = {s["id"] for s in resp_all.json()}
    assert other.id in ids_all


def test_list_students_reflects_real_class_id(client, seed, existing_student):
    _override_user("admin")
    resp = client.get("/admin/students", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    row = next(s for s in resp.json() if s["id"] == existing_student.id)
    assert row["class_id"] == seed["class"].id


# --- GET /admin/students/{id} ---------------------------------------------------


def test_get_student_returns_404_for_unknown_id(client):
    _override_user("admin")
    resp = client.get("/admin/students/999999999")
    assert resp.status_code == 404


def test_get_student_returns_404_for_non_student_user(client, db_session, seed):
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    teacher = User(supabase_id=uuid.uuid4(), email=f"t-{uuid.uuid4()}@example.com", role_id=teacher_role.id, school_id=seed["school"].id)
    db_session.add(teacher)
    db_session.commit()
    db_session.refresh(teacher)

    _override_user("admin")
    resp = client.get(f"/admin/students/{teacher.id}")
    assert resp.status_code == 404


# --- PUT /admin/students/{id} ---------------------------------------------------


def test_update_student_full_name(client, existing_student):
    _override_user("admin")
    resp = client.put(f"/admin/students/{existing_student.id}", json={"full_name": "Renamed Student"})
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Renamed Student"


def test_update_student_class_id_swaps_primary_enrollment(client, db_session, seed, existing_student):
    """Regression coverage for the real gap this endpoint closes: changing a
    student's class must REMOVE the old primary enrollment, not just add a
    second one alongside it (which would break `.one_or_none()` callers
    elsewhere, e.g. the timetable's own-class resolution)."""
    _override_user("admin")
    resp = client.put(f"/admin/students/{existing_student.id}", json={"class_id": seed["class_b"].id})
    assert resp.status_code == 200
    assert resp.json()["class_id"] == seed["class_b"].id

    enrollments = db_session.query(Enrollment).filter(
        Enrollment.student_id == existing_student.id, Enrollment.is_primary.is_(True), Enrollment.subject_id.is_(None)
    ).all()
    assert len(enrollments) == 1
    assert enrollments[0].class_id == seed["class_b"].id


def test_update_student_returns_400_for_unknown_class_id(client, existing_student):
    _override_user("admin")
    resp = client.put(f"/admin/students/{existing_student.id}", json={"class_id": 999999999})
    assert resp.status_code == 400


def test_update_student_returns_404_for_unknown_id(client):
    _override_user("admin")
    resp = client.put("/admin/students/999999999", json={"full_name": "X"})
    assert resp.status_code == 404


# --- PUT /admin/students/{id}/deactivate + reactivate ---------------------------


def test_deactivate_and_reactivate_student(client, existing_student):
    _override_user("admin")
    resp = client.put(f"/admin/students/{existing_student.id}/deactivate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    resp2 = client.put(f"/admin/students/{existing_student.id}/reactivate")
    assert resp2.status_code == 200
    assert resp2.json()["is_active"] is True


def test_deactivate_student_excludes_from_reference_lookup(client, seed, existing_student):
    _override_user("admin")
    client.put(f"/admin/students/{existing_student.id}/deactivate")

    resp = client.get("/reference/lookup", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    ids = {s["id"] for s in resp.json()["students"]}
    assert existing_student.id not in ids
