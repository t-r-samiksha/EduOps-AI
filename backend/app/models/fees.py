from datetime import date as date_
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint, and_, func
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


SETTLED_STATUSES = ("paid",)
"""Statuses that mean nothing is owed. Everything else - pending, overdue, partial -
still represents money the school has not received."""


def has_outstanding_balance(today: date_):
    """SQL predicate: this fee still owes money AND its due date has passed.

    THE ONE DEFINITION OF "STILL OWED, AND LATE", shared by the reminder engine
    (routers/fees.py::_reminder_scope_query) and the Command Center alert feed
    (services/alert_aggregator.py::fee_overdue_alerts).

    WHY IT EXISTS: both used to filter on `status == "overdue"` independently, and
    recording any payment flips a record to "partial". So paying 1 rupee of a 350 rupee
    fee removed it from BOTH surfaces - no reminders, no alert - while 349 rupees stayed
    unpaid and 30 days late. Two copies of the same wrong idea, which is exactly the
    duplication that made it invisible. A part payment must make a debt smaller, never
    quieter.

    `paid` is the only settled status. A record with amount_paid >= amount_due but a
    stale status is also excluded, so a mis-set status cannot resurrect a settled fee.
    """
    return and_(
        ~FeeRecord.status.in_(SETTLED_STATUSES),
        FeeRecord.amount_paid < FeeRecord.amount_due,
        FeeRecord.due_date < today,
    )


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


class FeePaymentRequest(Base):
    """A parent's claim that they have paid a fee outside the system, awaiting an
    admin's confirmation.

    WHY THIS TABLE EXISTS, rather than a payment-gateway integration: real Indian
    schools collect by UPI, bank transfer or cash at the office and reconcile by
    hand. There is no gateway to integrate with, mocked or otherwise. So the
    honest model is a claim-and-review loop - the parent pays through their own
    bank, records the reference here, and an admin confirms it against the
    statement. Only that confirmation writes through to the canonical FeeRecord.

    A row here is therefore NEVER the source of truth for whether a fee is paid;
    `fee_records.status` is, and stays so. That separation is what keeps the fee
    reminder engine honest: it reads FeeRecord, so a pending claim does not
    silence reminders (see routers/fees.py::trigger_reminders) - a claim is a
    claim until someone checks it.

    ONE OPEN REQUEST PER FEE is enforced by a PARTIAL unique index on
    (fee_record_id) WHERE status = 'pending', created with raw SQL in migration
    6b10048f8738 because Alembic autogenerate cannot express a partial index. A
    plain unique constraint would be wrong - it would block a parent from ever
    resubmitting after a rejection, which is exactly the flow the reject branch
    is for.
    """

    __tablename__ = "fee_payment_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    fee_record_id: Mapped[int] = mapped_column(ForeignKey("fee_records.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    """Denormalised from fee_record.student_id so the admin queue can filter and
    display by child without joining through fee_records on every read."""
    parent_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    """Who submitted the claim - not necessarily the only parent linked to the
    student, so this records which one actually acted."""
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    """What the parent says they paid. Validated at submit time to be > 0 and no
    more than the record's outstanding balance, but deliberately allowed to be
    LESS - part payments are normal and land the record on `partial`."""
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    """One of: UPI, Bank Transfer, Cash, Other. Free text with a documented
    vocabulary, same spirit as FeeSchedule.fee_type."""
    payment_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    """The parent's UPI transaction id, bank reference or office receipt number -
    the string an admin actually matches against a statement."""
    proof_url: Mapped[str | None] = mapped_column(String(500))
    """Object PATH inside the private `payment-proofs` bucket, not a public URL -
    same convention as Resource.file_url. Read back through
    GET /admin/fee-payment-requests/{id}/proof, which applies role scoping;
    a public URL would route around that."""
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    """One of: pending, confirmed, rejected."""
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    """Required when status = 'rejected'; surfaced to the parent so a rejection is
    actionable rather than a dead end."""

    fee_record: Mapped["FeeRecord"] = relationship()
    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    parent: Mapped["User"] = relationship(foreign_keys=[parent_id])
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by])
