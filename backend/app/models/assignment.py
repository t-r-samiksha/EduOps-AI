from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

SUBMISSION_STATUSES = ("submitted", "late", "missing", "graded")


class Assignment(Base):
    """An academic assignment created by a teacher for a class and subject."""

    __tablename__ = "assignments"
    __table_args__ = (
        Index("ix_assignments_school_class", "school_id", "class_id"),
        Index("ix_assignments_deadline", "deadline"),
        Index("ix_assignments_teacher_id", "teacher_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_marks: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    attachment_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attachment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship()
    school_class: Mapped["SchoolClass"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])
    submissions: Mapped[list["AssignmentSubmission"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan", order_by="AssignmentSubmission.created_at.desc()"
    )


class AssignmentSubmission(Base):
    """A student's submission for an assignment with grading and feedback."""

    __tablename__ = "assignment_submissions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "student_id", name="uq_assignment_student_submission"),
        Index("ix_submissions_assignment_student", "assignment_id", "student_id"),
        Index("ix_submissions_student_status", "student_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="submitted", nullable=False)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    assignment: Mapped["Assignment"] = relationship(back_populates="submissions")
    student: Mapped["User"] = relationship(foreign_keys=[student_id])
