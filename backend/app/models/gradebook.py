from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

ASSESSMENT_TYPES = ("assignment", "quiz", "exam", "other")


class GradebookEntry(Base):
    """An individual academic assessment grade entry in a student's gradebook."""

    __tablename__ = "gradebook_entries"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "subject_id", "term", "assessment_type", "assessment_id",
            name="uq_gradebook_student_assessment",
        ),
        Index("ix_gradebook_student_term", "student_id", "term"),
        Index("ix_gradebook_class_subject", "class_id", "subject_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)

    term: Mapped[str] = mapped_column(String(50), nullable=False)  # "Term 1", "Term 2", "Annual"
    assessment_type: Mapped[str] = mapped_column(String(50), nullable=False)  # assignment, quiz, exam, other
    assessment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # link to assignment_id, quiz_id

    score: Mapped[float] = mapped_column(Float, nullable=False)
    max_score: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship()
    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    subject: Mapped["Subject"] = relationship()
    school_class: Mapped["SchoolClass"] = relationship()


class GradebookWeight(Base):
    """Configurable term grading weights for assessment categories."""

    __tablename__ = "gradebook_weights"
    __table_args__ = (
        Index("ix_gradebook_weights_school_term", "school_id", "term"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True)
    term: Mapped[str] = mapped_column(String(50), default="Term 1", nullable=False)

    assignment_weight: Mapped[float] = mapped_column(Float, default=0.20, nullable=False)
    quiz_weight: Mapped[float] = mapped_column(Float, default=0.20, nullable=False)
    midterm_weight: Mapped[float] = mapped_column(Float, default=0.20, nullable=False)
    final_weight: Mapped[float] = mapped_column(Float, default=0.40, nullable=False)
    other_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
