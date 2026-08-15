import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException, status

from app.main import app
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user


def _override_user(role: str, user_id: int = 999, school_id: int | None = None):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role, school_id=school_id)

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_user_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_me_returns_school_id_for_a_school_linked_admin(client):
    """GET /auth/me now carries school_id - the onboarding wizard's only real
    way to know which school the logged-in admin manages (CurrentUser didn't
    carry this at all before)."""
    _override_user("admin", user_id=42, school_id=7)
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["school_id"] == 7
    assert body["role"] == "admin"
    assert body["user_id"] == 42


def _signup_body(**overrides):
    body = {
        "full_name": "New Admin",
        "email": f"newadmin-{uuid.uuid4()}@example.com",
        "password": "Sup3rSecret!",
        "school_name": "Brand New School",
    }
    body.update(overrides)
    return body


# --- Success path ----------------------------------------------------------------


def test_signup_creates_real_school_and_user(client, db_session):
    body = _signup_body()
    fake_supabase_id = uuid.uuid4()

    with (
        patch("app.routers.auth.create_admin_auth_account", return_value=fake_supabase_id) as mock_create,
        patch("app.routers.auth.sign_in_and_get_access_token", return_value="fake-access-token") as mock_signin,
    ):
        resp = client.post("/auth/signup", json=body)

    mock_create.assert_called_once_with(email=body["email"], password=body["password"], full_name=body["full_name"])
    mock_signin.assert_called_once_with(email=body["email"], password=body["password"])

    assert resp.status_code == 201
    result = resp.json()
    assert result["access_token"] == "fake-access-token"
    assert result["email"] == body["email"]
    assert result["school_name"] == body["school_name"]

    school = db_session.query(School).filter(School.id == result["school_id"]).one()
    assert school.name == body["school_name"]

    user = db_session.query(User).filter(User.id == result["user_id"]).one()
    assert user.email == body["email"]
    assert user.full_name == body["full_name"]
    assert user.supabase_id == fake_supabase_id
    assert user.school_id == school.id

    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    assert user.role_id == admin_role.id


# --- Validation --------------------------------------------------------------------


def test_signup_rejects_empty_full_name(client):
    with patch("app.routers.auth.create_admin_auth_account") as mock_create:
        resp = client.post("/auth/signup", json=_signup_body(full_name="   "))
    assert resp.status_code == 400
    mock_create.assert_not_called()


def test_signup_rejects_empty_school_name(client):
    with patch("app.routers.auth.create_admin_auth_account") as mock_create:
        resp = client.post("/auth/signup", json=_signup_body(school_name=""))
    assert resp.status_code == 400
    mock_create.assert_not_called()


def test_signup_rejects_short_password(client):
    with patch("app.routers.auth.create_admin_auth_account") as mock_create:
        resp = client.post("/auth/signup", json=_signup_body(password="short"))
    assert resp.status_code == 400
    mock_create.assert_not_called()


# --- Duplicate email ---------------------------------------------------------------


def test_signup_returns_409_for_email_already_registered_locally(client, db_session):
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    existing = User(supabase_id=uuid.uuid4(), email="already-here@example.com", role_id=teacher_role.id)
    db_session.add(existing)
    db_session.commit()

    with patch("app.routers.auth.create_admin_auth_account") as mock_create:
        resp = client.post("/auth/signup", json=_signup_body(email="already-here@example.com"))

    assert resp.status_code == 409
    mock_create.assert_not_called()


def test_signup_propagates_409_when_supabase_says_already_registered(client):
    """Simulates: no local row exists yet, but a real Supabase Auth account
    with this email already does - the local pre-check can't catch this."""
    with patch(
        "app.routers.auth.create_admin_auth_account",
        side_effect=HTTPException(status.HTTP_409_CONFLICT, "already registered"),
    ):
        resp = client.post("/auth/signup", json=_signup_body())
    assert resp.status_code == 409


# --- Rollback: local creation fails AFTER the real auth account already exists -------


def test_signup_rolls_back_local_state_when_school_creation_fails_after_auth_succeeds(client, db_session):
    """Forces the local School/User creation to fail AFTER the (mocked)
    Supabase Auth account has already been "created" - proving the real
    accepted-edge-case behavior: the local half-created state cleanly rolls
    back rather than leaving an orphaned School or User row, even though the
    external Supabase account itself can't be un-created by our own
    transaction (that's the one real, documented, unavoidable gap)."""
    body = _signup_body()
    fake_supabase_id = uuid.uuid4()
    with (
        patch("app.routers.auth.create_admin_auth_account", return_value=fake_supabase_id) as mock_create,
        patch("app.routers.auth.School", side_effect=RuntimeError("simulated local failure")),
    ):
        resp = client.post("/auth/signup", json=body)

    mock_create.assert_called_once()  # the real auth account WAS created before the failure
    assert resp.status_code == 500

    assert db_session.query(School).filter(School.name == body["school_name"]).one_or_none() is None
    assert db_session.query(User).filter(User.email == body["email"]).one_or_none() is None
