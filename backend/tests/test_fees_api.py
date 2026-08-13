import uuid
from datetime import date, timedelta

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.fees import FeeRecord, FeeReminder, FeeSchedule
from app.models.role import Role
from app.models.school import School
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


@pytest.fixture()
def seed(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()

    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    admin_user = _make_user(db_session, admin_role, "admin", school)
    student = _make_user(db_session, student_role, "student", school)

    school_class = SchoolClass(name="8A", academic_year=ACADEMIC_YEAR, school_id=school.id)
    db_session.add(school_class)
    db_session.commit()

    return {"school": school, "class": school_class, "admin_user": admin_user, "student": student}


# --- RBAC ---


def test_create_schedule_401_without_token(client):
    resp = client.post("/admin/fees/schedules", json={})
    assert resp.status_code == 401


def test_create_schedule_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/fees/schedules", json={})
    assert resp.status_code == 403


def test_list_schedules_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/admin/fees/schedules")
    assert resp.status_code == 403


def test_reminders_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/fees/reminders", json={})
    assert resp.status_code == 403


def test_status_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/admin/fees/status")
    assert resp.status_code == 403


def test_payment_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/fees/records/1/payment", json={"amount": 100})
    assert resp.status_code == 403


# --- POST/GET /admin/fees/schedules ---


def test_create_and_list_schedule(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        "/admin/fees/schedules",
        json={"school_id": seed["school"].id, "class_id": seed["class"].id, "academic_year": ACADEMIC_YEAR, "fee_type": "tuition", "amount": 15000, "due_date": "2026-09-01"},
    )
    assert resp.status_code == 200
    schedule_id = resp.json()["id"]

    resp2 = client.get("/admin/fees/schedules", params={"school_id": seed["school"].id, "academic_year": ACADEMIC_YEAR})
    assert resp2.status_code == 200
    assert any(s["id"] == schedule_id for s in resp2.json())


def test_create_schedule_rejects_nonpositive_amount(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        "/admin/fees/schedules",
        json={"school_id": seed["school"].id, "academic_year": ACADEMIC_YEAR, "fee_type": "tuition", "amount": 0, "due_date": "2026-09-01"},
    )
    assert resp.status_code == 400


def test_create_schedule_404_for_missing_class(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        "/admin/fees/schedules",
        json={"school_id": seed["school"].id, "class_id": 999999, "academic_year": ACADEMIC_YEAR, "fee_type": "tuition", "amount": 100, "due_date": "2026-09-01"},
    )
    assert resp.status_code == 404


# --- POST /admin/fees/reminders ---


@pytest.fixture()
def overdue_record(db_session, seed):
    schedule = FeeSchedule(school_id=seed["school"].id, class_id=seed["class"].id, academic_year=ACADEMIC_YEAR, fee_type="tuition", amount=15000.0, due_date=date.today() - timedelta(days=8))
    db_session.add(schedule)
    db_session.flush()
    record = FeeRecord(student_id=seed["student"].id, fee_schedule_id=schedule.id, amount_due=15000.0, amount_paid=0.0, status="overdue", due_date=schedule.due_date)
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


def test_trigger_reminders_creates_reminder_for_overdue_record(client, db_session, seed, overdue_record):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/admin/fees/reminders", json={"class_id": seed["class"].id, "overdue_only": True})
    assert resp.status_code == 200
    assert resp.json()["sent_count"] == 1

    reminder = db_session.query(FeeReminder).filter(FeeReminder.fee_record_id == overdue_record.id).one()
    assert reminder.sent_at is None
    assert "7 days overdue" in reminder.cadence_reason


def test_trigger_reminders_does_not_resend_same_tier(client, seed, overdue_record):
    _override_user("admin", user_id=seed["admin_user"].id)
    client.post("/admin/fees/reminders", json={"class_id": seed["class"].id, "overdue_only": True})
    resp2 = client.post("/admin/fees/reminders", json={"class_id": seed["class"].id, "overdue_only": True})
    assert resp2.json()["sent_count"] == 0


# --- GET /admin/fees/status ---


def test_fee_status_filters_by_class_and_status(client, db_session, seed, overdue_record):
    resp = client.get("/admin/fees/status")  # no override yet -> should 401
    assert resp.status_code == 401

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/fees/status", params={"class_id": seed["class"].id, "status": "overdue"})
    items = resp.json()["items"]
    match = next(i for i in items if i["fee_record_id"] == overdue_record.id)
    assert match["student_id"] == seed["student"].id
    assert match["status"] == "overdue"


# --- POST /admin/fees/records/{id}/payment ---


def test_partial_payment_sets_status_partial(client, db_session, seed, overdue_record):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/fees/records/{overdue_record.id}/payment", json={"amount": 5000})
    assert resp.status_code == 200
    body = resp.json()
    assert body["amount_paid"] == 5000
    assert body["status"] == "partial"


def test_full_payment_sets_status_paid(client, db_session, seed, overdue_record):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/fees/records/{overdue_record.id}/payment", json={"amount": 15000})
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"


def test_payment_rejects_nonpositive_amount(client, seed, overdue_record):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/fees/records/{overdue_record.id}/payment", json={"amount": 0})
    assert resp.status_code == 400


def test_payment_404_for_missing_record(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/admin/fees/records/999999/payment", json={"amount": 100})
    assert resp.status_code == 404
