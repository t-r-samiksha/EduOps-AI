import uuid

import pytest

from app.main import app
from app.models.audit import AuditLogEntry
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


def _make_user(db_session, role_row, prefix, school):
    email = f"{prefix}-{uuid.uuid4()}@example.com"
    user = User(supabase_id=uuid.uuid4(), email=email, full_name=prefix, role_id=role_row.id, school_id=school.id)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def seed(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    admin_user = _make_user(db_session, admin_role, "admin", school)
    actor = _make_user(db_session, admin_role, "actor", school)
    db_session.commit()
    return {"admin_user": admin_user, "actor": actor}


@pytest.fixture()
def entries(db_session, seed):
    # Explicit, distinguishable created_at values - PostgreSQL's now() returns the
    # *transaction* start time, so rows inserted in the same commit (as these are)
    # would otherwise get identical timestamps, making "newest first" ordering
    # unspecified between them.
    from datetime import datetime, timedelta, timezone

    base = datetime.now(timezone.utc)
    e1 = AuditLogEntry(actor_id=seed["actor"].id, action="resolve", entity_type="risk_flags", entity_id=555, created_at=base)
    e2 = AuditLogEntry(
        actor_id=seed["actor"].id, action="acknowledge", entity_type="risk_flags", entity_id=555,
        created_at=base + timedelta(seconds=1),
    )
    e3 = AuditLogEntry(actor_id=seed["actor"].id, action="update", entity_type="timetable_slots", entity_id=777, created_at=base)
    db_session.add_all([e1, e2, e3])
    db_session.commit()
    for e in (e1, e2, e3):
        db_session.refresh(e)
    return {"e1": e1, "e2": e2, "e3": e3}


# --- RBAC ---


def test_by_user_401_without_token(client):
    resp = client.get("/audit/by_user/1")
    assert resp.status_code == 401


def test_by_user_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/audit/by_user/1")
    assert resp.status_code == 403


def test_by_object_401_without_token(client):
    resp = client.get("/audit/by_object/risk_flags/1")
    assert resp.status_code == 401


def test_by_object_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/audit/by_object/risk_flags/1")
    assert resp.status_code == 403


# --- GET /audit/by_user/{user_id} ---


def test_by_user_returns_all_actions_by_that_actor(client, seed, entries):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get(f"/audit/by_user/{seed['actor'].id}")
    assert resp.status_code == 200
    ids = {i["id"] for i in resp.json()["items"]}
    assert {entries["e1"].id, entries["e2"].id, entries["e3"].id} <= ids


def test_by_user_does_not_include_other_actors_entries(client, seed, entries):
    # admin_user never acted in this fixture - only `actor` did (entries e1/e2/e3) -
    # so admin_user's own by_user feed must not contain any of them.
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get(f"/audit/by_user/{seed['admin_user'].id}")
    assert resp.status_code == 200
    ids = {i["id"] for i in resp.json()["items"]}
    assert {entries["e1"].id, entries["e2"].id, entries["e3"].id}.isdisjoint(ids)
    for item in resp.json()["items"]:
        assert item["actor_id"] == seed["admin_user"].id


# --- GET /audit/by_object/{object_type}/{object_id} ---


def test_by_object_returns_all_actions_on_that_entity(client, seed, entries):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/audit/by_object/risk_flags/555")
    assert resp.status_code == 200
    ids = {i["id"] for i in resp.json()["items"]}
    assert entries["e1"].id in ids
    assert entries["e2"].id in ids
    assert entries["e3"].id not in ids  # different entity_type/entity_id


def test_by_object_scopes_by_both_type_and_id(client, seed, entries):
    _override_user("admin", user_id=seed["admin_user"].id)
    # Same entity_id (555) but a different entity_type - must not match.
    resp = client.get("/audit/by_object/documents/555")
    ids = {i["id"] for i in resp.json()["items"]}
    assert entries["e1"].id not in ids
    assert entries["e2"].id not in ids


def test_by_object_returns_entries_newest_first(client, seed, entries):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/audit/by_object/risk_flags/555")
    items = [i for i in resp.json()["items"] if i["id"] in (entries["e1"].id, entries["e2"].id)]
    assert items[0]["id"] == entries["e2"].id  # created second, so newest
