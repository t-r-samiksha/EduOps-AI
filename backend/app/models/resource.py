from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Resource(Base):
    """A teaching resource (notes, worksheet, slides, textbook unit summary, diagram)
    uploaded by a teacher - organized by subject and unit, and used as the source corpus
    that RAG bots retrieve from.
    """

    __tablename__ = "resources"
    __table_args__ = (
        Index("ix_resources_school_grade", "school_id", "grade_level"),
        Index("ix_resources_class_subject", "class_id", "subject_id"),
        Index("ix_resources_school_unit", "school_id", "unit"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    grade_level: Mapped[int] = mapped_column(Integer, nullable=False)

    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("classes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    needs_reindex: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship()
    school_class: Mapped["SchoolClass | None"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
    uploader: Mapped["User"] = relationship(foreign_keys=[uploaded_by])

    @property
    def teacher_id(self) -> int:
        return self.uploaded_by
