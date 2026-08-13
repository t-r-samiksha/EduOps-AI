from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuditLogEntry(Base):
    """A consistent-schema record of one privileged action, written by
    services/audit_log.py and called from every router where a meaningful state
    change happens (see that module's docstring for the full wired-in list).

    `entity_id` is NOT a foreign key at the database level - which table it refers to
    depends on `entity_type` (risk_flags, timetable_slots, leave_requests,
    substitutions, attendance_records, extracted_entities, anomaly_flags,
    interventions, ...), i.e. genuinely polymorphic across every feature this repo
    has built. Same reasoning as AnomalyFlag.entity_id (models/syllabus.py) and
    Alert.entity_id (services/alert_aggregator.py) - referential integrity is
    enforced in application code, not the DB, because a real FK can't point at
    "whichever table entity_type says."

    Indexed for the two query patterns this table exists to serve:
    GET /audit/by_user/{user_id} (actor_id) and
    GET /audit/by_object/{object_type}/{object_id} (entity_type, entity_id)."""

    __tablename__ = "audit_log_entries"
    __table_args__ = (
        Index("ix_audit_log_entries_actor_id", "actor_id"),
        Index("ix_audit_log_entries_entity_type_entity_id", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    """E.g. create, update, approve, reject, resolve, acknowledge, confirm, correct,
    review, dismiss_alert - free text (not an enum) since new routers will keep
    introducing new verbs, same spirit as Intervention.action_taken elsewhere."""
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    """Free-form - e.g. what changed, old/new values, a comment. Nullable: not every
    action has something worth recording beyond the fact that it happened."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actor: Mapped["User"] = relationship()
