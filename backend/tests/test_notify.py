import uuid

import pytest

from app.models.notification import Notification
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.notify import dispatch_bulk, dispatch_notification


def _make_user(db_session, role_row, prefix, school):
    email = f"{prefix}-{uuid.uuid4()}@example.com"
    user = User(supabase_id=uuid.uuid4(), email=email, full_name=prefix, role_id=role_row.id, school_id=school.id)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def seed(db_session):
    school = School(name="Notify Test School")
    db_session.add(school)
    db_session.flush()

    parent_role = db_session.query(Role).filter(Role.name == "parent").one()
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()

    parent_a = _make_user(db_session, parent_role, "parent-a", school)
    parent_b = _make_user(db_session, parent_role, "parent-b", school)
    teacher = _make_user(db_session, teacher_role, "teacher", school)
    db_session.commit()

    return {"school": school, "parent_a": parent_a, "parent_b": parent_b, "teacher": teacher}


def _rows_for(db_session, user_id):
    return db_session.query(Notification).filter(Notification.user_id == user_id).all()


# --- dispatch_notification ---


def test_dispatch_creates_row_after_caller_commits(db_session, seed):
    dispatch_notification(
        db_session, user_id=seed["parent_a"].id, source_type="early_warning", title="Attendance concern"
    )
    db_session.commit()

    rows = _rows_for(db_session, seed["parent_a"].id)
    assert len(rows) == 1
    assert rows[0].title == "Attendance concern"
    assert rows[0].source_type == "early_warning"


def test_dispatch_does_not_commit(db_session, seed):
    """The whole contract of this module: the caller's commit is what persists it,
    so a rolled-back state change takes its notification with it.

    Rolled back via an explicit savepoint rather than db_session.rollback(),
    because conftest's harness already wraps each test in a nested transaction -
    a bare rollback() would unwind the fixture's own seed rows too and fail for
    the wrong reason."""
    savepoint = db_session.begin_nested()
    dispatch_notification(db_session, user_id=seed["parent_a"].id, source_type="fee_reminder", title="Fee due")
    assert len(_rows_for(db_session, seed["parent_a"].id)) == 1  # visible pre-rollback
    savepoint.rollback()

    assert _rows_for(db_session, seed["parent_a"].id) == []


def test_dispatch_returns_pending_notification_without_id(db_session, seed):
    notification = dispatch_notification(
        db_session, user_id=seed["parent_a"].id, source_type="fee_reminder", title="Fee due"
    )
    assert isinstance(notification, Notification)
    assert notification.id is None
    db_session.flush()
    assert notification.id is not None


def test_dispatch_defaults(db_session, seed):
    dispatch_notification(db_session, user_id=seed["teacher"].id, source_type="leave_decision", title="Leave approved")
    db_session.commit()

    row = _rows_for(db_session, seed["teacher"].id)[0]
    assert row.priority == "normal"
    assert row.body is None
    assert row.source_id is None
    assert row.read_at is None
    assert row.acknowledged_at is None
    assert row.created_at is not None


def test_dispatch_all_optional_fields(db_session, seed):
    dispatch_notification(
        db_session,
        user_id=seed["parent_a"].id,
        source_type="admission_decision",
        title="Application accepted",
        body="Your application has been accepted.",
        priority="urgent",
        source_id=4242,
    )
    db_session.commit()

    row = _rows_for(db_session, seed["parent_a"].id)[0]
    assert row.body == "Your application has been accepted."
    assert row.priority == "urgent"
    assert row.source_id == 4242


def test_dispatch_does_not_validate_source_type(db_session, seed):
    """Documented behaviour: an unknown source_type is stored, not raised on - a
    cosmetic mistake must not fail the state change it accompanies."""
    dispatch_notification(db_session, user_id=seed["parent_a"].id, source_type="not_a_real_kind", title="x")
    db_session.commit()
    assert _rows_for(db_session, seed["parent_a"].id)[0].source_type == "not_a_real_kind"


def test_dispatch_twice_creates_two_rows(db_session, seed):
    """No implicit de-duplication on the single-recipient path."""
    dispatch_notification(db_session, user_id=seed["parent_a"].id, source_type="fee_reminder", title="Fee due")
    dispatch_notification(db_session, user_id=seed["parent_a"].id, source_type="fee_reminder", title="Fee due")
    db_session.commit()
    assert len(_rows_for(db_session, seed["parent_a"].id)) == 2


# --- dispatch_bulk ---


def test_dispatch_bulk_one_row_per_recipient(db_session, seed):
    dispatch_bulk(
        db_session,
        user_ids=[seed["parent_a"].id, seed["parent_b"].id],
        source_type="early_warning",
        title="Attendance concern",
    )
    db_session.commit()

    assert len(_rows_for(db_session, seed["parent_a"].id)) == 1
    assert len(_rows_for(db_session, seed["parent_b"].id)) == 1


def test_dispatch_bulk_deduplicates_user_ids(db_session, seed):
    """parent_student has no unique constraint, so duplicate parent ids reach
    callers routinely - one notification each, not one per link row."""
    dispatch_bulk(
        db_session,
        user_ids=[seed["parent_a"].id, seed["parent_a"].id, seed["parent_b"].id, seed["parent_a"].id],
        source_type="early_warning",
        title="Attendance concern",
    )
    db_session.commit()

    assert len(_rows_for(db_session, seed["parent_a"].id)) == 1
    assert len(_rows_for(db_session, seed["parent_b"].id)) == 1


def test_dispatch_bulk_preserves_first_seen_order(db_session, seed):
    result = dispatch_bulk(
        db_session,
        user_ids=[seed["parent_b"].id, seed["parent_a"].id, seed["parent_b"].id],
        source_type="announcement",
        title="School closed",
    )
    assert [n.user_id for n in result] == [seed["parent_b"].id, seed["parent_a"].id]


def test_dispatch_bulk_empty_user_ids_is_a_noop(db_session, seed):
    result = dispatch_bulk(db_session, user_ids=[], source_type="announcement", title="School closed")
    db_session.commit()

    assert result == []
    assert db_session.query(Notification).filter(Notification.title == "School closed").all() == []


def test_dispatch_bulk_accepts_any_iterable(db_session, seed):
    """Call sites pass generators/sets straight out of a query, not just lists."""
    ids = (u for u in [seed["parent_a"].id, seed["parent_b"].id])
    result = dispatch_bulk(db_session, user_ids=ids, source_type="report_card", title="Report card ready")
    db_session.commit()

    assert len(result) == 2


def test_dispatch_bulk_forwards_all_kwargs(db_session, seed):
    dispatch_bulk(
        db_session,
        user_ids=[seed["parent_a"].id],
        source_type="fee_reminder",
        title="Fee overdue",
        body="Tuition is 5 days overdue.",
        priority="important",
        source_id=77,
    )
    db_session.commit()

    row = _rows_for(db_session, seed["parent_a"].id)[0]
    assert row.source_type == "fee_reminder"
    assert row.body == "Tuition is 5 days overdue."
    assert row.priority == "important"
    assert row.source_id == 77


def test_dispatch_bulk_does_not_commit(db_session, seed):
    savepoint = db_session.begin_nested()
    dispatch_bulk(
        db_session, user_ids=[seed["parent_a"].id, seed["parent_b"].id], source_type="announcement", title="Closed"
    )
    assert len(_rows_for(db_session, seed["parent_a"].id)) == 1
    savepoint.rollback()

    assert _rows_for(db_session, seed["parent_a"].id) == []
    assert _rows_for(db_session, seed["parent_b"].id) == []
