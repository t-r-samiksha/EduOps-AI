from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

SOURCE_TYPES = (
    "early_warning",
    "fee_reminder",
    "fee_payment_request",
    "fee_payment_confirmed",
    "fee_payment_rejected",
    "report_card",
    "substitute_assigned",
    "announcement",
    "remark_posted",
    "leave_decision",
    "admission_decision",
)
"""Known notification sources. Kept as a plain tuple, not a DB enum or a Python
Enum class: new features keep adding kinds, and a Postgres enum would need a
migration for each one. Same free-text-with-a-documented-vocabulary approach as
AuditLogEntry.action and Intervention.action_taken."""

PRIORITIES = ("normal", "important", "urgent")


class Notification(Base):
    """One delivered notification for one user.

    Written only by services/notify.py, which is called from inside the
    transaction of whatever state change caused it (see that module's docstring)
    - so a notification exists if and only if the thing it announces actually
    committed.

    `source_id` is NOT a foreign key: which table it points at depends on
    `source_type` (risk_flags, fee_records, leave_requests, substitutions,
    admission_applications, ...). Same deliberate polymorphism as
    AuditLogEntry.entity_id and AnomalyFlag.entity_id - a real FK can't point at
    "whichever table source_type says", so integrity is an application concern.
    It's nullable because not every notification has a single originating row
    (a broadcast announcement, for instance).

    READ STATE
    ------------
    `read_at`/`acknowledged_at` are nullable timestamps rather than booleans, so
    "when did they see it" is answerable, not just "did they". Note this is the
    first table in the schema to carry mutable timestamps of this kind - no table
    here has an `updated_at`, so don't expect one to be maintained for you.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # (user_id, read_at) serves the unread-count query, which every client
        # polls and the SSE stream re-runs on each tick - it must not table-scan
        # a table that only ever grows. The leading column also covers plain
        # "my inbox" reads, so no separate user_id-only index is needed.
        Index("ix_notifications_user_id_read_at", "user_id", "read_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    """The recipient. A notification is per-user, not per-entity: two parents
    linked to the same flagged student get two rows, not one shared one.

    Deliberately no `index=True` here: the (user_id, read_at) composite in
    __table_args__ already indexes user_id as its leading column, so a standalone
    one would be dead weight on every insert. See that index's comment."""
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal", server_default="normal")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Null means unread - the unread-count query is `read_at IS NULL`."""
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Stronger than read: the user explicitly dismissed/actioned it. Independent
    of read_at rather than implying it, matching how RiskFlag keeps acknowledge
    and resolve separate."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["User"] = relationship()
