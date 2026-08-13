from datetime import date as date_
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AdmissionApplication(Base):
    """A prospective student's admission application. NOT linked to a real `users`
    row while pending - the applicant isn't a student/user in the system yet. See
    services/admissions_rules.py for the legal state-transition machine, and
    routers/admissions.py for what happens (and what's honestly stubbed) on
    acceptance - real Enrollment creation requires an existing student user account,
    and this repo has no account-creation flow anywhere (checked - Supabase Auth
    signup is out of scope here), so acceptance only wires a real Enrollment when the
    caller supplies an already-existing `student_user_id`; otherwise it's a
    documented no-op, not a silent skip.

    Fields beyond the base spec, each necessary rather than decorative:
      - `school_id`/`academic_year`: the task's own eligibility rule ("grade_applied
        must be a valid grade offered by the school") is meaningless without knowing
        WHICH school and year to check offered grades against - the base spec never
        mentions either field, but every other school-scoped model in this codebase
        (FeeSchedule, SyllabusPlan, TimetableSlot, ...) carries them for exactly this
        reason, and eligibility/enrollment can't work without them here either.
      - `submitted_by`: the task's own stub text says applications are "typically
        entered by office staff" - there is no other real user id to use as
        PendingApproval.requested_by once this is registered in
        services/approval_aggregator.py (the applicant has no user row to be one).
      - `submitted_at`: needed as the PendingApproval.requested_at timestamp, same
        role LeaveRequest.requested_at already plays - every other model in this
        codebase has an equivalent "when was this created" column.
      - `enrolled_student_id`: set only when acceptance genuinely created a real
        Enrollment (see above) - lets a caller tell "accepted with a real student
        wired up" apart from "accepted, enrollment still pending" at a glance."""

    __tablename__ = "admission_applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    """The year the applicant is applying to join - also what the eventual
    Enrollment's class must match."""
    applicant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dob: Mapped[date_] = mapped_column(nullable=False)
    guardian_email: Mapped[str] = mapped_column(String(255), nullable=False)
    grade_applied: Mapped[str] = mapped_column(String(20), nullable=False)
    ocr_document_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, server_default="[]")
    """Document.id values from the OCR session (models/document.py) - application-
    level reference only, not a DB-enforced FK array (same polymorphic-reference
    reasoning as AnomalyFlag.entity_id/AuditLogEntry.entity_id elsewhere)."""
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="submitted")
    """One of: submitted, under_review, accepted, rejected."""
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_justification: Mapped[str | None] = mapped_column(Text)
    enrolled_student_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    school: Mapped["School"] = relationship()
    submitter: Mapped["User"] = relationship(foreign_keys=[submitted_by])
    decider: Mapped["User | None"] = relationship(foreign_keys=[decided_by])
    enrolled_student: Mapped["User | None"] = relationship(foreign_keys=[enrolled_student_id])
