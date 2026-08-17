from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Resource(Base):
    """A teaching resource (notes, a worksheet, a topic summary) uploaded by a
    teacher - the source corpus the RAG bots retrieve from.

    CONTRAST WITH models/document.py's `Document`, which looks similar and is not:
    Document.file_url is a FABRICATED descriptive string ("documents/12/scan.png")
    for an image that is OCR'd in memory and then discarded - nothing is ever stored,
    and fetching that path returns nothing (see routers/documents.py's own comment
    saying as much). Resource.file_url is a REAL Supabase Storage object path in the
    `resources` bucket that can be fetched back, which is what makes re-indexing
    without a re-upload possible.
    """

    __tablename__ = "resources"
    __table_args__ = (
        # Every retrieval and listing query filters on this exact pair.
        Index("ix_resources_school_grade", "school_id", "grade_level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    grade_level: Mapped[int] = mapped_column(Integer, nullable=False)
    """SCOPE UNIT - grade, not class. Was class_id until the grade-level re-scope.

    Sections of the same grade follow the same curriculum, so a Grade 3 science
    handout is Grade 3 material, not "Grade 3 - A material". Scoping per class meant
    uploading the same file once per section and left 3-B unable to see 3-A's notes.
    This also aligns retrieval with Top Doubts, which already aggregates by
    (school_id, grade_level, subject_id).

    NOT an FK - grade_level is a plain integer on `classes`, not its own table.
    `school_id` is therefore load-bearing: grade 1 exists in every school, so
    filtering on grade_level ALONE would cross tenants."""

    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    """Nullable: a general handout may not belong to one subject. Retrieval filters on
    it only when the asker names a subject."""

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    """Supabase Storage object path within the `resources` bucket, e.g.
    "5707/5208/12-multiplication.md". Real and fetchable - see the class docstring."""
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)

    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Null until ingestion has written this resource's kb_chunks. The periodic
    reindex job selects on `indexed_at IS NULL`, so a resource whose inline ingestion
    failed gets picked up automatically rather than silently never being searchable."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    school: Mapped["School"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
    uploader: Mapped["User"] = relationship(foreign_keys=[uploaded_by])
