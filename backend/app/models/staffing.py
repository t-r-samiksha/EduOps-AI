from datetime import date as date_
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LeaveRequest(Base):
    """A teacher's request to be away for a date range. Approval is what triggers
    substitute-finding (see Substitution) for every timetable slot they'd otherwise
    have taught during [start_date, end_date]."""

    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    start_date: Mapped[date_] = mapped_column(nullable=False)
    end_date: Mapped[date_] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    """One of: pending, approved, rejected."""
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(String(500))
    """The approver's note back to the teacher ("short-staffed that week, refile for
    September"). Same role AdmissionApplication.decision_justification plays for an
    admission decision. Previously the Approvals Inbox accepted a `comment` and wrote
    it ONLY into audit_log_entries.detail - a table teachers can't read (GET /audit/*
    is admin/principal-only) - so the decision reason was invisible to the one person
    it was written for. Persisted here so it survives on the record itself rather than
    only inside a notification the teacher may have already dismissed."""

    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])
    decider: Mapped["User | None"] = relationship(foreign_keys=[decided_by])


class Substitution(Base):
    """One row per distinct timetable slot a teacher needs covered for the duration
    of an approved leave - not one row per calendar occurrence. A weekly-recurring
    slot that falls inside the leave window multiple times is still a single
    substitution need (the same sub covers it for as long as the leave lasts)."""

    __tablename__ = "substitutions"
    __table_args__ = (
        UniqueConstraint("leave_request_id", "timetable_slot_id", name="uq_substitution_leave_slot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    leave_request_id: Mapped[int] = mapped_column(ForeignKey("leave_requests.id"), nullable=False)
    timetable_slot_id: Mapped[int] = mapped_column(ForeignKey("timetable_slots.id"), nullable=False)
    original_teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    substitute_teacher_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="suggested")
    """One of: suggested, confirmed, declined."""
    suggested_score: Mapped[float | None] = mapped_column(Float)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    leave_request: Mapped["LeaveRequest"] = relationship()
    timetable_slot: Mapped["TimetableSlot"] = relationship()
    original_teacher: Mapped["User"] = relationship(foreign_keys=[original_teacher_id])
    substitute_teacher: Mapped["User | None"] = relationship(foreign_keys=[substitute_teacher_id])


class StaffingForecast(Base):
    """Persisted output of the staffing-gap forecasting model (services/
    staffing_forecast.py) for one school/date, so the (future) admin command center
    can read forecasts without re-running the model on every page load. Recomputed
    and upserted by GET /admin/staffing/forecast on each call."""

    __tablename__ = "staffing_forecasts"
    __table_args__ = (UniqueConstraint("school_id", "date", name="uq_staffing_forecast_school_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    date: Mapped[date_] = mapped_column(nullable=False)
    predicted_gap_count: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    """One of: low, medium, high."""
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    school: Mapped["School"] = relationship()
