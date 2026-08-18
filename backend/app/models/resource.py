from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Resource(Base):
    """A teaching resource (notes, worksheet, slides, textbook unit summary, diagram)
    uploaded by a teacher - organized by subject and unit, and used as the source corpus
    that RAG bots retrieve from.

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
        Index("ix_resources_class_subject", "class_id", "subject_id"),
        Index("ix_resources_school_unit", "school_id", "unit"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    grade_level: Mapped[int] = mapped_column(Integer, nullable=False)
    """SCOPE UNIT FOR RETRIEVAL - grade, not class. Was class_id until the grade-level
    re-scope (35f1fab38e0b), and `class_id` below is NOT a revert of that decision.

    Sections of the same grade follow the same curriculum, so a Grade 3 science
    handout is Grade 3 material, not "Grade 3 - A material". Scoping per class meant
    uploading the same file once per section and left 3-B unable to see 3-A's notes.
    This also aligns retrieval with Top Doubts, which already aggregates by
    (school_id, grade_level, subject_id).

    NOT an FK - grade_level is a plain integer on `classes`, not its own table.
    `school_id` is therefore load-bearing: grade 1 exists in every school, so
    filtering on grade_level ALONE would cross tenants.

    EVERY RAG PATH READS THIS, NOT class_id: services/ingestion.py stamps it onto each
    kb_chunk, and services/retrieval.py scopes the nearest-neighbour search by it."""

    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("classes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    """OPTIONAL NARROWING, added alongside grade_level - it does not replace it.

    NULL (the normal case) = grade-scoped material, visible to every section in the
    grade, and the only kind retrieval widens to. Non-NULL = a handout meant for one
    section only, surfaced in Person B's resource browser
    (`GET /resources/{class_id}`, `GET /resources/units`) but never used to scope bot
    retrieval. The read path spells this out as
    `class_id IS NULL AND grade_level = :grade`."""

    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    """Nullable: a general handout may not belong to one subject. Retrieval filters on
    it only when the asker names a subject."""

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    """Supabase Storage object path within the `resources` bucket, e.g.
    "5707/5208/12-multiplication.md". Real and fetchable - see the class docstring."""
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    needs_reindex: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    """DISPLAY FLAG ONLY - `indexed_at` below is what actually gates re-indexing.

    Kept in sync by services/ingestion.py and echoed in the GET /resources response,
    but nothing selects on it. Do not add a re-index job that reads this instead:
    ingest_pending() and the nightly scheduler both select `indexed_at IS NULL`, so a
    resource with needs_reindex=True and a non-NULL indexed_at will never be picked
    up. See docs/audit/merge-01-conflicts.md (D-2)."""

    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """AUTHORITATIVE re-index gate. Null until ingestion has written this resource's
    kb_chunks. The periodic reindex job selects on `indexed_at IS NULL`, so a resource
    whose inline ingestion failed gets picked up automatically rather than silently
    never being searchable."""

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
