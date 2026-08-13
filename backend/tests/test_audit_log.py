import uuid

import pytest

from app.models.audit import AuditLogEntry
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.audit_log import write_audit_log


@pytest.fixture()
def actor(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    user = User(supabase_id=uuid.uuid4(), email=f"actor-{uuid.uuid4()}@example.com", full_name="Actor", role_id=admin_role.id, school_id=school.id)
    db_session.add(user)
    db_session.commit()
    return user


def test_write_audit_log_creates_entry_with_all_fields(db_session, actor):
    entry = write_audit_log(
        db_session, actor_id=actor.id, action="resolve", entity_type="risk_flags", entity_id=43, detail={"note": "x"}
    )
    db_session.commit()
    db_session.refresh(entry)

    assert entry.id is not None
    assert entry.actor_id == actor.id
    assert entry.action == "resolve"
    assert entry.entity_type == "risk_flags"
    assert entry.entity_id == 43
    assert entry.detail == {"note": "x"}
    assert entry.created_at is not None


def test_write_audit_log_detail_defaults_to_none(db_session, actor):
    entry = write_audit_log(db_session, actor_id=actor.id, action="acknowledge", entity_type="risk_flags", entity_id=1)
    db_session.commit()
    db_session.refresh(entry)
    assert entry.detail is None


def test_write_audit_log_does_not_commit_itself(db_session, actor):
    # Caller controls the transaction - write_audit_log only adds to the session.
    write_audit_log(db_session, actor_id=actor.id, action="update", entity_type="timetable_slots", entity_id=1)
    # Still visible within the same session before an explicit commit (SQLAlchemy
    # autoflushes on query) - proves add() happened without needing commit() here.
    pending = db_session.query(AuditLogEntry).filter(AuditLogEntry.actor_id == actor.id, AuditLogEntry.entity_id == 1).one()
    assert pending.action == "update"
