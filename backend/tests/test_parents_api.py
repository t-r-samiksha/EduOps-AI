import uuid
from unittest.mock import patch

import pytest

from app.main import app
from app.models.parent_student import ParentStudent
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

    student_role = db_session.query(Role).filter(Role.name == "student").one()
    student1 = User(supabase_id=uuid.uuid4(), email=f"s1-{uuid.uuid4()}@example.com", role_id=student_role.id, school_id=school.id)
    student2 = User(supabase_id=uuid.uuid4(), email=f"s2-{uuid.uuid4()}@example.com", role_id=student_role.id, school_id=school.id)
    db_session.add_all([student1, student2])
    db_session.commit()
    db_session.refresh(student1)
    db_session.refresh(student2)
    return {"school": school, "student1": student1, "student2": student2}


@pytest.fixture()
def existing_parent(db_session, seed):
    parent_role = db_session.query(Role).filter(Role.name == "parent").one()
    parent = User(
        supabase_id=uuid.uuid4(), email=f"p-{uuid.uuid4()}@example.com", full_name="Existing Parent",
        role_id=parent_role.id, school_id=seed["school"].id,
    )
    db_session.add(parent)
    db_session.flush()
    db_session.add(ParentStudent(parent_id=parent.id, student_id=seed["student1"].id))
    db_session.commit()
    db_session.refresh(parent)
    return parent


def test_create_parent_returns_401_without_token(client):
    resp = client.post("/admin/parents", json={"school_id": 1, "email": "a@b.com", "password": "x"})
    assert resp.status_code == 401


def test_create_parent_returns_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/parents", json={"school_id": 1, "email": "a@b.com", "password": "x"})
    assert resp.status_code == 403


def test_create_parent_links_multiple_students(client, db_session, seed):
    _override_user("admin")
    fake_supabase_id = uuid.uuid4()
    with patch("app.routers.parents.create_auth_account", return_value=fake_supabase_id) as mock_create:
        resp = client.post(
            "/admin/parents",
            json={
                "school_id": seed["school"].id, "email": "guardian@example.com", "password": "Sup3rSecret!",
                "full_name": "Rajesh Sharma", "student_ids": [seed["student1"].id, seed["student2"].id],
            },
        )
    mock_create.assert_called_once_with(email="guardian@example.com", password="Sup3rSecret!", full_name="Rajesh Sharma", role="parent")
    assert resp.status_code == 201
    body = resp.json()
    assert set(body["student_ids"]) == {seed["student1"].id, seed["student2"].id}

    links = db_session.query(ParentStudent).filter(ParentStudent.parent_id == body["id"]).all()
    assert {l.student_id for l in links} == {seed["student1"].id, seed["student2"].id}


def test_create_parent_returns_400_for_unknown_student_id_without_calling_supabase(client, seed):
    _override_user("admin")
    with patch("app.routers.parents.create_auth_account") as mock_create:
        resp = client.post(
            "/admin/parents",
            json={"school_id": seed["school"].id, "email": "a@b.com", "password": "x", "student_ids": [999999999]},
        )
    assert resp.status_code == 400
    mock_create.assert_not_called()


def test_create_parent_returns_400_for_a_non_student_id(client, db_session, seed):
    """A real user id that exists but isn't a student (e.g. a teacher) must be
    rejected the same as an unknown id - student_ids means real students."""
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    teacher = User(supabase_id=uuid.uuid4(), email=f"t-{uuid.uuid4()}@example.com", role_id=teacher_role.id, school_id=seed["school"].id)
    db_session.add(teacher)
    db_session.commit()
    db_session.refresh(teacher)

    _override_user("admin")
    with patch("app.routers.parents.create_auth_account") as mock_create:
        resp = client.post(
            "/admin/parents",
            json={"school_id": seed["school"].id, "email": "a@b.com", "password": "x", "student_ids": [teacher.id]},
        )
    assert resp.status_code == 400
    mock_create.assert_not_called()


def test_create_parent_stores_phone(client, seed):
    _override_user("admin")
    with patch("app.routers.parents.create_auth_account", return_value=uuid.uuid4()):
        resp = client.post(
            "/admin/parents",
            json={
                "school_id": seed["school"].id, "email": "withphone@example.com", "password": "Sup3rSecret!",
                "full_name": "Rajesh Sharma", "phone": "9876543210",
            },
        )
    assert resp.status_code == 201
    assert resp.json()["phone"] == "9876543210"


def test_create_parent_allows_omitting_phone(client, seed):
    _override_user("admin")
    with patch("app.routers.parents.create_auth_account", return_value=uuid.uuid4()):
        resp = client.post(
            "/admin/parents", json={"school_id": seed["school"].id, "email": "nophone@example.com", "password": "Sup3rSecret!"}
        )
    assert resp.status_code == 201
    assert resp.json()["phone"] is None


def test_create_parent_with_no_students_succeeds(client, seed):
    _override_user("principal")
    with patch("app.routers.parents.create_auth_account", return_value=uuid.uuid4()):
        resp = client.post(
            "/admin/parents", json={"school_id": seed["school"].id, "email": "noStudents@example.com", "password": "Sup3rSecret!"}
        )
    assert resp.status_code == 201
    assert resp.json()["student_ids"] == []


# --- GET /admin/parents (list) --------------------------------------------------


def test_list_parents_returns_401_without_token(client):
    resp = client.get("/admin/parents", params={"school_id": 1})
    assert resp.status_code == 401


def test_list_parents_returns_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/admin/parents", params={"school_id": 1})
    assert resp.status_code == 403


def test_list_parents_returns_only_active_by_default(client, db_session, seed, existing_parent):
    inactive = User(
        supabase_id=uuid.uuid4(), email=f"inactive-{uuid.uuid4()}@example.com",
        role_id=existing_parent.role_id, school_id=seed["school"].id, is_active=False,
    )
    db_session.add(inactive)
    db_session.commit()

    _override_user("admin")
    resp = client.get("/admin/parents", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert existing_parent.id in ids
    assert inactive.id not in ids

    resp_all = client.get("/admin/parents", params={"school_id": seed["school"].id, "include_inactive": True})
    assert inactive.id in {p["id"] for p in resp_all.json()}


def test_list_parents_reflects_real_linked_children(client, seed, existing_parent):
    _override_user("admin")
    resp = client.get("/admin/parents", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    row = next(p for p in resp.json() if p["id"] == existing_parent.id)
    assert row["student_ids"] == [seed["student1"].id]


# --- GET /admin/parents/{id} -----------------------------------------------------


def test_get_parent_returns_404_for_unknown_id(client):
    _override_user("admin")
    resp = client.get("/admin/parents/999999999")
    assert resp.status_code == 404


def test_get_parent_returns_404_for_non_parent_user(client, seed):
    _override_user("admin")
    resp = client.get(f"/admin/parents/{seed['student1'].id}")
    assert resp.status_code == 404


# --- PUT /admin/parents/{id} ------------------------------------------------------


def test_update_parent_full_name(client, existing_parent):
    _override_user("admin")
    resp = client.put(f"/admin/parents/{existing_parent.id}", json={"full_name": "Renamed Parent"})
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Renamed Parent"


def test_update_parent_phone(client, existing_parent):
    _override_user("admin")
    resp = client.put(f"/admin/parents/{existing_parent.id}", json={"phone": "9123456789"})
    assert resp.status_code == 200
    assert resp.json()["phone"] == "9123456789"
    # full_name untouched by a phone-only partial update
    assert resp.json()["full_name"] == "Existing Parent"


def test_update_parent_returns_404_for_unknown_id(client):
    _override_user("admin")
    resp = client.put("/admin/parents/999999999", json={"full_name": "X"})
    assert resp.status_code == 404


# --- POST/DELETE /admin/parents/{id}/children -------------------------------------


def test_add_parent_child_is_idempotent(client, db_session, seed, existing_parent):
    """existing_parent already has student1 linked (see fixture) - adding
    student2 should add exactly one new link, and re-adding student1 must
    never create a duplicate row."""
    _override_user("admin")
    resp = client.post(f"/admin/parents/{existing_parent.id}/children", params={"student_id": seed["student2"].id})
    assert resp.status_code == 201
    assert set(resp.json()["student_ids"]) == {seed["student1"].id, seed["student2"].id}

    resp2 = client.post(f"/admin/parents/{existing_parent.id}/children", params={"student_id": seed["student1"].id})
    assert resp2.status_code == 201
    links = db_session.query(ParentStudent).filter(
        ParentStudent.parent_id == existing_parent.id, ParentStudent.student_id == seed["student1"].id
    ).all()
    assert len(links) == 1


def test_add_parent_child_returns_400_for_unknown_student(client, existing_parent):
    _override_user("admin")
    resp = client.post(f"/admin/parents/{existing_parent.id}/children", params={"student_id": 999999999})
    assert resp.status_code == 400


def test_remove_parent_child(client, existing_parent, seed):
    _override_user("admin")
    resp = client.delete(f"/admin/parents/{existing_parent.id}/children/{seed['student1'].id}")
    assert resp.status_code == 200
    assert resp.json()["student_ids"] == []


# --- PUT /admin/parents/{id}/deactivate + reactivate ------------------------------


def test_deactivate_and_reactivate_parent(client, existing_parent):
    _override_user("admin")
    resp = client.put(f"/admin/parents/{existing_parent.id}/deactivate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    resp2 = client.put(f"/admin/parents/{existing_parent.id}/reactivate")
    assert resp2.status_code == 200
    assert resp2.json()["is_active"] is True
