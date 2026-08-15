from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Document(Base):
    """An uploaded document awaiting/undergoing OCR. `file_url` is a descriptive
    reference path, not a real file-storage integration - like attendance-CV's
    /attendance/enroll and /attendance/mark, the uploaded image is processed
    in-memory during the request and not persisted anywhere durable (no file/object
    storage exists anywhere in this codebase yet, so this doesn't introduce a new
    inconsistency)."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"))
    """Added by a reliability-audit fix (a cross-tenant leak: list/detail had zero
    tenant scoping, confirmed empirically - Admin A could see Admin B's documents).
    Nullable only for rows that predate this column (their uploader's own
    User.school_id was also unset at the time, so there's no honest value to
    backfill - see the migration) - every NEW upload always sets it via a required
    `school_id` form field, matching how every other Person A endpoint scopes
    school-specific data (CurrentUser carries no school_id of its own to derive
    this from - see services/auth.py). A null-school_id row is invisible through
    every school_id-scoped endpoint below (list/detail/correct/reextract), not
    deleted - a legacy row a real admin can't reach via the API, not silently
    exposed to the wrong tenant either."""
    document_type: Mapped[str] = mapped_column(String(20), nullable=False)
    """One of: marksheet, admission_form, id_proof, other."""
    file_url: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="queued")
    """One of: queued, processing, done, failed."""
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    uploader: Mapped["User"] = relationship(foreign_keys=[uploaded_by])


class OcrResult(Base):
    """Raw OCR output for a Document - one row per document (re-extraction re-runs
    postprocessing against this same raw_text rather than re-running OCR)."""

    __tablename__ = "ocr_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, unique=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    """0..1 overall OCR confidence (mean word-level confidence), null if no text was
    confidently recognized at all."""
    engine_version: Mapped[str] = mapped_column(String(100), nullable=False)
    ocr_metadata: Mapped[dict | None] = mapped_column(JSONB)
    """Free-form extra engine info (e.g. image dimensions, word count) - not
    load-bearing for anything, just diagnostic."""

    document: Mapped["Document"] = relationship()


class ExtractedEntity(Base):
    """One structured field pulled out of a document's OCR text by
    services/ocr_postprocess.py, with the manual-correction workflow's state."""

    __tablename__ = "extracted_entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    field_value: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    is_low_confidence: Mapped[bool] = mapped_column(nullable=False)
    corrected_value: Mapped[str | None] = mapped_column(String(500))
    corrected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped["Document"] = relationship()
    corrector: Mapped["User | None"] = relationship(foreign_keys=[corrected_by])
