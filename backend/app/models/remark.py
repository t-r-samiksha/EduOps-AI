from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

REMARK_SENTIMENT_TAGS = ("academic", "behavioral", "appreciation")


class Remark(Base):
    """A teacher's qualitative evaluation remark or behavioral observation for a student."""

    __tablename__ = "remarks"
    __table_args__ = (
        Index("ix_remarks_student_id", "student_id"),
        Index("ix_remarks_class_subject", "class_id", "subject_id"),
        Index("ix_remarks_sentiment", "sentiment_tag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment_tag: Mapped[str] = mapped_column(String(50), default="academic", nullable=False)  # academic, behavioral, appreciation

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship()
    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    author: Mapped["User"] = relationship(foreign_keys=[author_id])
    school_class: Mapped["SchoolClass"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
