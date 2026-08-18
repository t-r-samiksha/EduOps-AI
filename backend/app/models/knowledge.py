"""RAG storage: the embedded corpus (`kb_chunks`) and the bot interaction log
(`chatbot_logs`).

pgvector note - this is the SECOND vector column in the schema and the FIRST indexed
one. `face_embeddings.embedding` (models/attendance.py, Vector(128)) has no ANN index
at all and does a brute-force scan on every recognition. That is tolerable for a few
hundred faces; it would not be for a growing curriculum corpus, so `kb_chunks` gets a
real HNSW index - created via raw `op.execute` in the migration, since Alembic
autogenerate does not emit pgvector index types.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.class_ import SchoolClass
    from app.models.school import School
    from app.models.subject import Subject
    from app.models.user import User

EMBEDDING_DIM = 1536
"""Must equal services/llm.py::EMBEDDING_DIMENSIONS. Kept as a separate constant here
rather than imported from that module so importing a model never pulls in the Gemini
client (which raises at import when GEMINI_API_KEY is unset - that would make every
model import, and therefore alembic and the whole test suite, depend on an API key)."""

SOURCE_TYPE_RESOURCE = "resource"
SOURCE_TYPE_VERIFIED_DOUBT_ANSWER = "verified_doubt_answer"
SOURCE_TYPES = (SOURCE_TYPE_RESOURCE, SOURCE_TYPE_VERIFIED_DOUBT_ANSWER)


class KbChunk(Base):
    """One embedded slice of a source document."""

    __tablename__ = "kb_chunks"
    __table_args__ = (
        # THE idempotency key. Re-ingesting a resource must update its chunks in
        # place, not append a second copy - without this, every reindex would double
        # the corpus and skew retrieval toward whatever was ingested most often.
        UniqueConstraint("source_type", "source_id", "chunk_index", name="uq_kb_chunk_source_index"),
        # Every retrieval query filters on this exact pair before the vector search.
        Index("ix_kb_chunks_school_grade", "school_id", "grade_level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    """One of SOURCE_TYPES. `verified_doubt_answer` is not written yet - it is the
    hook for feeding teacher-approved bot answers back into the corpus."""
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    """Polymorphic by source_type - a resources.id today. Deliberately not an FK, for
    the same reason AnomalyFlag.entity_id isn't one: it points at different tables
    depending on source_type."""
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    """L2-NORMALIZED at write time by services/llm.py. Cosine distance (`<=>`) is used
    for search; storing unnormalized truncated vectors would give quietly wrong
    ordering rather than an error. See llm.py::_NORMALIZE_REQUIRED."""

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    """LOAD-BEARING for tenant isolation, and easy to miss.

    When chunks were scoped by class_id, the school was implied - a class belongs to
    exactly one school. grade_level implies nothing: grade 1 exists in EVERY school,
    so filtering on grade_level alone would return other schools' material. Both
    columns are always applied together; see services/retrieval.py::search_chunks."""

    grade_level: Mapped[int] = mapped_column(Integer, nullable=False)
    """Scope unit, mirroring resources.grade_level - see that column's docstring for
    why grade rather than class."""

    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    school: Mapped["School"] = relationship()
    subject: Mapped["Subject | None"] = relationship()


class ChatbotLog(Base):
    """One bot interaction. Analytics and the Top Doubts clustering read from here;
    nothing reads it back as conversation context (the ask endpoint is stateless)."""

    __tablename__ = "chatbot_logs"
    __table_args__ = (
        # Top Doubts aggregates by (school, grade_level, subject) and resolves grade
        # through this class_id, within a recent time window.
        Index("ix_chatbot_logs_class_id", "class_id"),
        Index("ix_chatbot_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    bot_type: Mapped[str] = mapped_column(String(20), nullable=False)
    """"student" today; "teacher"/"parent" when those bots exist."""
    query: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    kb_chunks_used: Mapped[dict | None] = mapped_column(JSONB)
    """The chunk ids that grounded the answer, for auditing a bad answer after the
    fact - "what did it actually read" is unanswerable otherwise."""

    query_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    """Reuses the vector already computed for retrieval in POST /bots/student/ask -
    the query is never embedded twice. Nullable because a log written on a path that
    didn't embed (or a backfilled row) still belongs here; the clustering skips nulls.

    No HNSW index deliberately: these are scanned in bulk within a short time window
    by one aggregation job, never searched by nearest-neighbour globally. An HNSW
    index would cost write throughput on every question asked and buy nothing."""

    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"), nullable=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship()
    school_class: Mapped["SchoolClass"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
