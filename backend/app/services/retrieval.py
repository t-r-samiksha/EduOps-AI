"""Vector search over kb_chunks, plus the class-scope validation that guards it.

`assert_student_class_access` is the security boundary for the whole RAG feature. It
lives here rather than in the router so every current and future retrieval path is
forced through the same check - a second bot added later cannot accidentally skip it by
forgetting to copy a few lines out of a router.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.knowledge import KbChunk
from app.models.resource import Resource

DEFAULT_TOP_K = 5


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    source_id: int
    chunk_text: str
    distance: float
    title: str | None
    subject_id: int | None = None


def infer_subject_id(chunks: list[RetrievedChunk]) -> int | None:
    """Best guess at which subject a question was about, from what it retrieved.

    WHY THIS EXISTS: the Doubt Bot UI sends only class_id - a student never picks a
    subject - so `subject_id` on the request is almost always None in real traffic.
    Top Doubts, however, aggregates by (school, grade, SUBJECT) and its per-teacher
    endpoint always filters by one, which meant every genuinely-asked question was
    invisible to the feature and only the seeded fixtures ever showed up. Inferring it
    from the retrieved chunks closes that without asking the student to classify their
    own question.

    Majority vote over the retrieved chunks, ties broken by best (smallest) distance,
    so the nearest chunk's subject wins a 1-1 split. Returns None when nothing was
    retrieved or every chunk is subject-less, which is honest rather than guessing.
    """
    counts: dict[int, int] = {}
    best_distance: dict[int, float] = {}
    for chunk in chunks:
        if chunk.subject_id is None:
            continue
        counts[chunk.subject_id] = counts.get(chunk.subject_id, 0) + 1
        best_distance[chunk.subject_id] = min(best_distance.get(chunk.subject_id, 1e9), chunk.distance)
    if not counts:
        return None
    return max(counts, key=lambda sid: (counts[sid], -best_distance[sid]))


def assert_student_class_access(db: Session, *, student_id: int, class_id: int) -> tuple[int, int]:
    """Verify a student is enrolled in the class they named, and resolve its scope.

    THE security boundary for the Doubt Bot. `class_id` arrives in the request body,
    so without this a student could change one number and reach another school's
    material. Validated against the student's own primary Enrollment, server-side,
    before any embedding or retrieval happens.

    Returns `(school_id, grade_level)` - the RETRIEVAL scope, derived from the
    validated class rather than taken from the request. This is what keeps the
    grade-level re-scope safe: the client still names a class it must prove it belongs
    to, and the widening to grade happens entirely server-side. A client that sent a
    grade_level directly could name any grade in the school.

    Consequence worth being explicit about: retrieval is now grade-wide, so a Grade
    3 - A student CAN read material uploaded for Grade 3 - B. That is intended -
    sections of a grade share a curriculum - but it is a genuine widening from the
    per-class boundary this function used to enforce.
    """
    enrolled = (
        db.query(Enrollment)
        .filter(
            Enrollment.student_id == student_id,
            Enrollment.class_id == class_id,
            Enrollment.is_primary.is_(True),
        )
        .first()
    )
    if enrolled is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not enrolled in this class")

    school_class = db.query(SchoolClass).filter(SchoolClass.id == class_id).one_or_none()
    if school_class is None or school_class.grade_level is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your class has no grade level set")
    return school_class.school_id, school_class.grade_level


def search_chunks(
    db: Session,
    *,
    query_embedding: list[float],
    school_id: int,
    grade_level: int,
    subject_id: int | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Top-k nearest chunks by COSINE distance, hard-filtered to one school+grade.

    BOTH filters are required, always. grade_level alone is not a tenant boundary -
    grade 1 exists in every school - so passing only the grade would return other
    schools' material. They are applied as WHERE clauses, not a post-filter on the
    results: a post-filter would let out-of-scope chunks consume the top-k slots and
    silently return fewer (or zero) usable results while appearing to work.

    `.cosine_distance()` emits pgvector's `<=>`, which is what
    ix_kb_chunks_embedding_hnsw is built for (vector_cosine_ops). Distance is in
    [0, 2]; smaller is more similar, and for L2-normalized vectors it equals
    1 - cosine_similarity.
    """
    distance = KbChunk.embedding.cosine_distance(query_embedding)
    query = (
        db.query(KbChunk, distance.label("distance"), Resource.title)
        .outerjoin(Resource, Resource.id == KbChunk.source_id)
        .filter(KbChunk.school_id == school_id, KbChunk.grade_level == grade_level)
    )
    if subject_id is not None:
        query = query.filter(KbChunk.subject_id == subject_id)

    rows = query.order_by(distance).limit(top_k).all()
    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            source_id=chunk.source_id,
            chunk_text=chunk.chunk_text,
            distance=float(dist),
            title=title,
            subject_id=chunk.subject_id,
        )
        for chunk, dist, title in rows
    ]
