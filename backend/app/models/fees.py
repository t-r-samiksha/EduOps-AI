from datetime import date as date_
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FeeSchedule(Base):
    """A recurring fee definition for a school (or one class within it) for an
    academic_year - e.g. "Grade 8 tuition, due 2026-09-01, Rs 15000". `class_id` is
    nullable: null means a school-wide fee (e.g. a transport fee everyone pays), set
    means a class-specific fee (e.g. grade-tiered tuition) - matches how real school
    fee structures vary by grade far more often than by individual student, so
    class-level (not student-level) is the right granularity for a *schedule*;
    FeeRecord is where the per-student obligation actually lives."""

    __tablename__ = "fee_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    fee_type: Mapped[str] = mapped_column(String(30), nullable=False)
    """Free text, e.g. tuition, transport, lab, library - not an enum, same spirit
    as Intervention.action_taken elsewhere in this codebase."""
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    due_date: Mapped[date_] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    school: Mapped["School"] = relationship()
    school_class: Mapped["SchoolClass | None"] = relationship()


class FeeRecord(Base):
    """One student's obligation under one FeeSchedule - generated in bulk by
    scripts/run_monthly_fee_invoicing.py, one row per (student, fee_schedule)."""

    __tablename__ = "fee_records"
    __table_args__ = (UniqueConstraint("student_id", "fee_schedule_id", name="uq_fee_record_student_schedule"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    fee_schedule_id: Mapped[int] = mapped_column(ForeignKey("fee_schedules.id"), nullable=False)
    amount_due: Mapped[float] = mapped_column(Float, nullable=False)
    amount_paid: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    """One of: pending, paid, overdue, partial."""
    due_date: Mapped[date_] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped["User"] = relationship()
    fee_schedule: Mapped["FeeSchedule"] = relationship()


class FeeReminder(Base):
    """A reminder logged against a FeeRecord by services/fee_reminder_engine.py's
    cadence heuristic. `sent_at` is nullable/stub - same honest pattern as Command
    Center's briefing email: checked, no email-sending infrastructure exists
    anywhere in this repo (same finding as every prior session), so a row here means
    "the system determined a reminder was due and logged why," not "an email was
    actually delivered." Wire real sending in once an email provider exists;
    `sent_at` would then be set for real instead of staying null."""

    __tablename__ = "fee_reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    fee_record_id: Mapped[int] = mapped_column(ForeignKey("fee_records.id"), nullable=False)
    cadence_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    """Why this reminder fired, e.g. "14 days overdue - second reminder" - see
    services/fee_reminder_engine.py's REMINDER_TIERS."""
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    fee_record: Mapped["FeeRecord"] = relationship()
