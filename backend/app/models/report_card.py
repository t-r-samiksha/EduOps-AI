from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base


class ReportCard(Base):
    """An automated student academic report card snapshot and transcript."""

    __tablename__ = "report_cards"
    __table_args__ = (
        UniqueConstraint("student_id", "term", "academic_year", name="uq_report_card_student_term_year"),
        Index("ix_report_cards_class_term", "class_id", "term"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)

    term: Mapped[str] = mapped_column(String(50), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), default="2026-27", nullable=False)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    gpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    term_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    attendance_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Full structured snapshot: subjects, marks, weights, attendance, remarks, scale
    source_data_snapshot: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False
    )

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship()
    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    school_class: Mapped["SchoolClass"] = relationship()
