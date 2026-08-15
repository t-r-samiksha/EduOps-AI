import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException, status

from app.main import app
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import TeacherProfile, TeacherSubject, TeacherUnavailability
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

    subject = Subject(name="Math", school_id=school.id)
    db_session.add(subject)
    db_session.commit()
    db_session.refresh(subject)

    return {"school": school, "subject": subject}


@pytest.fixture()
def existing_teacher(db_session, seed):
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    teacher = User(
        supabase_id=uuid.uuid4(),
        email=f"t-{uuid.uuid4()}@example.com",
        full_name="Existing Teacher",
        role_id=teacher_role.id,
        school_id=seed["school"].id,
    )
    db_session.add(teacher)
    db_session.flush()
    db_session.add(TeacherProfile(teacher_id=teacher.id, max_periods_per_week=24))
    db_session.commit()
    db_session.refresh(teacher)
    return teacher


# --- RBAC --------------------------------------------------------------------


def test_create_teacher_returns_401_without_token(client):
    resp = client.post("/admin/teachers", json={"school_id": 1, "email": "a@b.com", "password": "x"})
    assert resp.status_code == 401


def test_create_teacher_returns_403_for_non_admin_role(client):
    _override_user("teacher")
    resp = client.post("/admin/teachers", json={"school_id": 1, "email": "a@b.com", "password": "x"})
    assert resp.status_code == 403


# --- Creation ------------------------------------------------------------------


def test_create_teacher_cold_start_with_real_supabase_call_mocked(client, seed):
    """The Supabase Admin API call itself is mocked here (standard practice for
    an external third-party dependency in a unit test) - CHECKPOINT 1 is the
    real, unmocked, live-server proof of this same endpoint."""
    _override_user("admin")
    fake_supabase_id = uuid.uuid4()
    with patch("app.routers.teachers.create_teacher_auth_account", return_value=fake_supabase_id) as mock_create:
        resp = client.post(
            "/admin/teachers",
            json={
                "school_id": seed["school"].id,
                "email": "new.teacher@example.com",
                "password": "Sup3rSecret!",
                "full_name": "New Teacher",
                "max_periods_per_week": 28,
                "subject_ids": [seed["subject"].id],
                "unavailability": [{"day_of_week": 4, "period_number": 5, "academic_year": "2026-27"}],
            },
        )
    mock_create.assert_called_once_with(email="new.teacher@example.com", password="Sup3rSecret!", full_name="New Teacher")
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new.teacher@example.com"
    assert body["max_periods_per_week"] == 28
    assert body["subject_ids"] == [seed["subject"].id]
    assert len(body["unavailability"]) == 1
    assert body["is_active"] is True


def test_create_teacher_returns_400_for_unknown_school_id_without_calling_supabase(client):
    _override_user("admin")
    with patch("app.routers.teachers.create_teacher_auth_account") as mock_create:
        resp = client.post("/admin/teachers", json={"school_id": 999999999, "email": "a@b.com", "password": "x"})
    assert resp.status_code == 400
    mock_create.assert_not_called()


def test_create_teacher_returns_400_for_unknown_subject_id_without_calling_supabase(client, seed):
    _override_user("admin")
    with patch("app.routers.teachers.create_teacher_auth_account") as mock_create:
        resp = client.post(
            "/admin/teachers",
            json={"school_id": seed["school"].id, "email": "a@b.com", "password": "x", "subject_ids": [999999999]},
        )
    assert resp.status_code == 400
    mock_create.assert_not_called()


def test_create_teacher_returns_409_for_email_already_used_locally_without_calling_supabase(client, seed, existing_teacher):
    _override_user("admin")
    with patch("app.routers.teachers.create_teacher_auth_account") as mock_create:
        resp = client.post(
            "/admin/teachers", json={"school_id": seed["school"].id, "email": existing_teacher.email, "password": "x"}
        )
    assert resp.status_code == 409
    mock_create.assert_not_called()


def test_create_teacher_propagates_409_when_supabase_says_already_registered(client, seed):
    """Simulates: no local row exists yet, but a real Supabase Auth account with
    this email already does (e.g. created some other way) - the local
    pre-check can't catch this, so the propagated error from
    create_teacher_auth_account itself must surface cleanly."""
    _override_user("admin")
    with patch(
        "app.routers.teachers.create_teacher_auth_account",
        side_effect=HTTPException(status.HTTP_409_CONFLICT, "already registered"),
    ):
        resp = client.post("/admin/teachers", json={"school_id": seed["school"].id, "email": "dup@example.com", "password": "x"})
    assert resp.status_code == 409


# --- Subjects sub-resource: idempotent add/remove ---------------------------------


def test_add_teacher_subject_is_idempotent(client, seed, existing_teacher, db_session):
    _override_user("admin")
    resp1 = client.post(f"/admin/teachers/{existing_teacher.id}/subjects", params={"subject_id": seed["subject"].id})
    assert resp1.status_code == 201
    resp2 = client.post(f"/admin/teachers/{existing_teacher.id}/subjects", params={"subject_id": seed["subject"].id})
    assert resp2.status_code == 201

    count = (
        db_session.query(TeacherSubject)
        .filter(TeacherSubject.teacher_id == existing_teacher.id, TeacherSubject.subject_id == seed["subject"].id)
        .count()
    )
    assert count == 1


def test_add_teacher_subject_returns_400_for_unknown_subject(client, existing_teacher):
    _override_user("admin")
    resp = client.post(f"/admin/teachers/{existing_teacher.id}/subjects", params={"subject_id": 999999999})
    assert resp.status_code == 400


def test_remove_teacher_subject(client, seed, existing_teacher, db_session):
    _override_user("admin")
    client.post(f"/admin/teachers/{existing_teacher.id}/subjects", params={"subject_id": seed["subject"].id})
    resp = client.delete(f"/admin/teachers/{existing_teacher.id}/subjects/{seed['subject'].id}")
    assert resp.status_code == 200
    assert resp.json()["subject_ids"] == []


# --- Unavailability sub-resource: idempotent add/remove -----------------------------


def test_add_teacher_unavailability_is_idempotent(client, existing_teacher, db_session):
    _override_user("principal")
    body = {"day_of_week": 4, "period_number": 5, "academic_year": "2026-27"}
    client.post(f"/admin/teachers/{existing_teacher.id}/unavailability", json=body)
    client.post(f"/admin/teachers/{existing_teacher.id}/unavailability", json=body)

    count = db_session.query(TeacherUnavailability).filter(TeacherUnavailability.teacher_id == existing_teacher.id).count()
    assert count == 1


def test_remove_teacher_unavailability(client, existing_teacher, db_session):
    _override_user("admin")
    body = {"day_of_week": 4, "period_number": 5, "academic_year": "2026-27"}
    added = client.post(f"/admin/teachers/{existing_teacher.id}/unavailability", json=body).json()
    slot_id = added["unavailability"][0]["id"]

    resp = client.delete(f"/admin/teachers/{existing_teacher.id}/unavailability/{slot_id}")
    assert resp.status_code == 200
    assert resp.json()["unavailability"] == []


# --- Update / deactivate --------------------------------------------------------


def test_update_teacher_scalar_fields(client, existing_teacher):
    _override_user("admin")
    resp = client.put(f"/admin/teachers/{existing_teacher.id}", json={"full_name": "Renamed", "max_periods_per_week": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert body["full_name"] == "Renamed"
    assert body["max_periods_per_week"] == 20


def test_deactivate_teacher_excludes_from_reference_lookup(client, seed, existing_teacher):
    _override_user("admin")
    before = client.get("/reference/lookup", params={"school_id": seed["school"].id}).json()
    assert existing_teacher.id in {t["id"] for t in before["teachers"]}

    client.put(f"/admin/teachers/{existing_teacher.id}/deactivate")

    after = client.get("/reference/lookup", params={"school_id": seed["school"].id}).json()
    assert existing_teacher.id not in {t["id"] for t in after["teachers"]}


def test_get_teacher_returns_404_for_non_teacher_user(client, db_session, seed):
    """A student/parent id must not be reachable through the teacher-specific endpoints."""
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    student = User(supabase_id=uuid.uuid4(), email=f"s-{uuid.uuid4()}@example.com", role_id=student_role.id, school_id=seed["school"].id)
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)

    _override_user("admin")
    resp = client.get(f"/admin/teachers/{student.id}")
    assert resp.status_code == 404
