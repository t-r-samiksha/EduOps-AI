from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AlertDismissal(Base):
    """Cross-cutting dismissal state for alert sources whose underlying table has no
    native, single-action "resolved" concept - see services/alert_aggregator.py's
    module docstring ("RESOLVE ROUTING") for the full reasoning. In short: a pending
    LeaveRequest's real next state is approve/reject (a decision with consequences,
    made through its own endpoint, not a generic "resolve"); a Substitution needs a
    chosen substitute to be confirmed; a failed/low-confidence Document has no
    "acknowledged" flag at all. Dismissing one of these alerts here only removes it
    from GET /admin/alerts - it does NOT change anything in the source table.

    RiskFlag alerts deliberately do NOT use this table: RiskFlag already has a real
    `status="resolved"` transition (PUT /risk/{id}/resolve), and resolving that alert
    routes directly to that field instead - see routers/admin_alerts.py. Duplicating
    it here would create two disagreeing "resolved" concepts for the same entity.

    This is intentionally the ONLY new table this session adds. Every other alert
    source already has enough native state (status columns, correction workflow) that
    a full duplicate `Alert` table read-model would just be a second source of truth
    to keep in sync - the live aggregator in alert_aggregator.py reads source tables
    directly instead, exactly as documented there."""

    __tablename__ = "alert_dismissals"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    """Composite alert id, e.g. "leave_request:12" - see alert_aggregator.Alert.id."""
    dismissed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    dismissed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dismisser: Mapped["User"] = relationship()
