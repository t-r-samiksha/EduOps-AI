"""Each of Person A's dispatch points actually reaches the right inbox.

These are deliberately about the WIRING, not about notify.py itself (that's
tests/test_notify.py) - each test drives the real endpoint and asserts a
Notification landed for the audience that endpoint already knew about.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.fees import FeeRecord, FeeSchedule
from app.models.notification import Notification
from app.models.parent_student import ParentStudent
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user, require_role

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int, school_id: int | None = None):
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


def _notifications_for(db_session, user_id, source_type=None):
    query = db_session.query(Notification).filter(Notification.user_id == user_id)
    if source_type is not None:
        query = query.filter(Notification.source_type == source_type)
    return query.all()


@pytest.fixture()
def seed(db_session):
    school = School(name="Dispatch Wiring School")
    db_session.add(school)
    db_session.flush()

    roles = {n: db_session.query(Role).filter(Role.name == n).one() for n in ("teacher", "student", "parent", "admin")}

    admin = _make_user(db_session, roles["admin"], "admin", school)
    homeroom = _make_user(db_session, roles["teacher"], "homeroom", school)
    substitute = _make_user(db_session, roles["teacher"], "substitute", school)

    school_class = SchoolClass(
        name="Grade 8 - A", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=homeroom.id
    )
    db_session.add(school_class)
    db_session.flush()

    student = _make_user(db_session, roles["student"], "student", school)
    db_session.add(Enrollment(student_id=student.id, class_id=school_class.id, subject_id=None, is_primary=True))

    parent_one = _make_user(db_session, roles["parent"], "parent-one", school)
    parent_two = _make_user(db_session, roles["parent"], "parent-two", school)
    db_session.add_all(
        [
            ParentStudent(parent_id=parent_one.id, student_id=student.id),
            ParentStudent(parent_id=parent_two.id, student_id=student.id),
        ]
    )
    db_session.commit()

    return {
        "school": school, "admin": admin, "homeroom": homeroom, "substitute": substitute,
        "class": school_class, "student": student, "parent_one": parent_one, "parent_two": parent_two,
    }


# --- risk.py: POST /risk/flag -> early_warning ---


def test_flag_creation_notifies_both_parents_and_homeroom_teacher(client, db_session, seed):
    _override_user("admin", seed["admin"].id, seed["school"].id)
    resp = client.post(
        "/risk/flag",
        json={"student_id": seed["student"].id, "risk_level": "high", "reasons": ["missed 3 assignments"]},
    )
    assert resp.status_code == 200

    for recipient in ("parent_one", "parent_two", "homeroom"):
        rows = _notifications_for(db_session, seed[recipient].id, "early_warning")
        assert len(rows) == 1, recipient
        assert rows[0].source_id == resp.json()["id"]
        assert rows[0].priority == "urgent"
        assert "missed 3 assignments" in rows[0].body


def test_flag_creation_does_not_notify_unrelated_users(client, db_session, seed):
    _override_user("admin", seed["admin"].id, seed["school"].id)
    client.post(
        "/risk/flag",
        json={"student_id": seed["student"].id, "risk_level": "medium", "reasons": ["late twice"]},
    )
    assert _notifications_for(db_session, seed["substitute"].id) == []


def test_flag_creation_priority_reflects_risk_level(client, db_session, seed):
    _override_user("admin", seed["admin"].id, seed["school"].id)
    client.post(
        "/risk/flag",
        json={"student_id": seed["student"].id, "risk_level": "low", "reasons": ["one missed class"]},
    )
    assert _notifications_for(db_session, seed["parent_one"].id, "early_warning")[0].priority == "important"


def test_rejected_flag_creates_no_notification(client, db_session, seed):
    """A 400 rolls back - no notification for a flag that never existed."""
    _override_user("admin", seed["admin"].id, seed["school"].id)
    resp = client.post(
        "/risk/flag", json={"student_id": seed["student"].id, "risk_level": "nonsense", "reasons": ["x"]}
    )
    assert resp.status_code == 400
    assert _notifications_for(db_session, seed["parent_one"].id) == []


# --- fees.py: POST /admin/fees/reminders -> fee_reminder ---


@pytest.fixture()
def overdue_fee(db_session, seed):
    schedule = FeeSchedule(
        school_id=seed["school"].id, class_id=None, academic_year=ACADEMIC_YEAR,
        fee_type="Term 1 Tuition", amount=4500.0, due_date=date.today() - timedelta(days=21),
    )
    db_session.add(schedule)
    db_session.flush()
    record = FeeRecord(
        student_id=seed["student"].id, fee_schedule_id=schedule.id, amount_due=4500.0,
        amount_paid=0.0, status="overdue", due_date=schedule.due_date,
    )
    db_session.add(record)
    db_session.commit()
    return record


def test_fee_reminders_notify_every_linked_parent(client, db_session, seed, overdue_fee):
    _override_user("admin", seed["admin"].id, seed["school"].id)
    resp = client.post("/admin/fees/reminders", json={"overdue_only": True})
    assert resp.status_code == 200

    for recipient in ("parent_one", "parent_two"):
        rows = _notifications_for(db_session, seed[recipient].id, "fee_reminder")
        assert len(rows) == 1, recipient
        assert rows[0].source_id == overdue_fee.id
        assert rows[0].priority == "urgent"
        assert "Term 1 Tuition" in rows[0].body


def test_fee_reminders_do_not_cross_school_boundaries(client, db_session, seed, overdue_fee):
    """An admin firing reminders must not touch another school's records - neither
    a FeeReminder row nor a notification to that school's parents."""
    other_school = School(name="Other School (fees scoping)")
    db_session.add(other_school)
    db_session.flush()
    roles = {n: db_session.query(Role).filter(Role.name == n).one() for n in ("student", "parent")}
    other_student = _make_user(db_session, roles["student"], "other-student", other_school)
    other_parent = _make_user(db_session, roles["parent"], "other-parent", other_school)
    db_session.add(ParentStudent(parent_id=other_parent.id, student_id=other_student.id))

    other_schedule = FeeSchedule(
        school_id=other_school.id, class_id=None, academic_year=ACADEMIC_YEAR,
        fee_type="Term 1 Tuition", amount=1000.0, due_date=date.today() - timedelta(days=21),
    )
    db_session.add(other_schedule)
    db_session.flush()
    db_session.add(
        FeeRecord(
            student_id=other_student.id, fee_schedule_id=other_schedule.id, amount_due=1000.0,
            amount_paid=0.0, status="overdue", due_date=other_schedule.due_date,
        )
    )
    db_session.commit()

    _override_user("admin", seed["admin"].id, seed["school"].id)
    resp = client.post("/admin/fees/reminders", json={"overdue_only": True})
    assert resp.status_code == 200

    assert _notifications_for(db_session, other_parent.id) == []
    # ...and the caller's own school was still processed.
    assert len(_notifications_for(db_session, seed["parent_one"].id, "fee_reminder")) == 1


def test_fee_reminders_do_not_notify_the_student(client, db_session, seed, overdue_fee):
    """Recipients are the parents on the record, not the student themselves."""
    _override_user("admin", seed["admin"].id, seed["school"].id)
    client.post("/admin/fees/reminders", json={"overdue_only": True})
    assert _notifications_for(db_session, seed["student"].id, "fee_reminder") == []


# --- staffing.py: PUT /staff/approve_leave -> leave_decision ---


@pytest.fixture()
def pending_leave(db_session, seed):
    leave = LeaveRequest(
        teacher_id=seed["homeroom"].id, start_date=date.today() + timedelta(days=3),
        end_date=date.today() + timedelta(days=4), reason="Medical", status="pending",
    )
    db_session.add(leave)
    db_session.commit()
    return leave


def test_approve_leave_notifies_the_requesting_teacher(client, db_session, seed, pending_leave):
    _override_user("admin", seed["admin"].id, seed["school"].id)
    resp = client.put(
        "/staff/approve_leave",
        json={"leave_request_id": pending_leave.id, "decision": "approved", "academic_year": ACADEMIC_YEAR},
    )
    assert resp.status_code == 200

    rows = _notifications_for(db_session, seed["homeroom"].id, "leave_decision")
    assert len(rows) == 1
    assert rows[0].source_id == pending_leave.id
    assert "approved" in rows[0].title


def test_reject_leave_also_notifies_the_requesting_teacher(client, db_session, seed, pending_leave):
    _override_user("admin", seed["admin"].id, seed["school"].id)
    client.put(
        "/staff/approve_leave",
        json={"leave_request_id": pending_leave.id, "decision": "rejected", "academic_year": ACADEMIC_YEAR},
    )
    rows = _notifications_for(db_session, seed["homeroom"].id, "leave_decision")
    assert len(rows) == 1
    assert "rejected" in rows[0].title


def test_leave_decision_on_unknown_request_notifies_nobody(client, db_session, seed):
    _override_user("admin", seed["admin"].id, seed["school"].id)
    resp = client.put(
        "/staff/approve_leave",
        json={"leave_request_id": -1, "decision": "approved", "academic_year": ACADEMIC_YEAR},
    )
    assert resp.status_code == 404
    assert _notifications_for(db_session, seed["homeroom"].id, "leave_decision") == []


# --- approvals.py: POST /admin/approvals/{id}/decision -> leave_decision ---


def test_approvals_inbox_decision_notifies_the_requester(client, db_session, seed, pending_leave):
    _override_user("admin", seed["admin"].id, seed["school"].id)
    resp = client.post(
        f"/admin/approvals/leave_request:{pending_leave.id}/decision",
        json={"decision": "approve", "academic_year": ACADEMIC_YEAR},
    )
    assert resp.status_code == 200

    rows = _notifications_for(db_session, seed["homeroom"].id, "leave_decision")
    assert len(rows) == 1
    assert rows[0].source_id == pending_leave.id


# --- end-to-end: the notification is readable through the inbox API ---


def test_dispatched_notification_shows_up_in_the_parents_inbox(client, db_session, seed):
    _override_user("admin", seed["admin"].id, seed["school"].id)
    client.post(
        "/risk/flag",
        json={"student_id": seed["student"].id, "risk_level": "high", "reasons": ["attendance 40%"]},
    )

    _override_user("parent", seed["parent_one"].id, seed["school"].id)
    assert client.get("/notifications/unread-count").json()["count"] == 1
    body = client.get("/notifications").json()
    assert body["total"] == 1
    assert body["items"][0]["source_type"] == "early_warning"
