"""Tests for the RAG pipeline (Steps 1-5): llm normalization, chunking, ingestion
idempotency, cosine ordering, and resource upload/read scoping.

SCOPE, deliberately narrow (per Day 2's testing amendment): only things that are
security-critical or that fail SILENTLY AND PLAUSIBLY. There is no test here for
"upload returns the right JSON keys", no per-role matrix, and no 401-on-every-route -
those cost time and catch nothing that a demo wouldn't surface immediately.

NO LIVE API CALLS. Every embedding is mocked. The real Gemini calls were verified
once, by hand, at the Step 5 checkpoint; wiring them into an 8-minute suite would make
it slower, flakier, and dependent on a rate-limited free tier.
"""

from __future__ import annotations

import math
import uuid

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.knowledge import SOURCE_TYPE_RESOURCE, KbChunk
from app.models.resource import Resource
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user
from app.services.ingestion import chunk_text
from app.services.llm import l2_normalize
from app.services.retrieval import assert_student_class_access, search_chunks

ACADEMIC_YEAR = "2026-27"
DIM = 1536


def _override_user(role: str, user_id: int = 999, school_id: int | None = None):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="t@example.com", role=role, school_id=school_id)

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _make_user(db_session, role_name, prefix, school):
    role = db_session.query(Role).filter(Role.name == role_name).one()
    user = User(
        supabase_id=uuid.uuid4(), email=f"{prefix}-{uuid.uuid4()}@example.com",
        full_name=prefix, role_id=role.id, school_id=school.id,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _unit_vector(*, axis: int) -> list[float]:
    """A one-hot unit vector. Two one-hot vectors on different axes are exactly
    orthogonal (cosine distance 1.0), and identical ones are distance 0.0 - which
    makes expected ordering arithmetically exact rather than approximate."""
    vector = [0.0] * DIM
    vector[axis] = 1.0
    return vector


@pytest.fixture()
def rag_seed(db_session):
    school = School(name="RAG Test School")
    db_session.add(school)
    db_session.flush()

    teacher = _make_user(db_session, "teacher", "teacher", school)
    other_teacher = _make_user(db_session, "teacher", "other-teacher", school)

    # Two SECTIONS of grade 3 (same scope under grade-level scoping) plus one class at
    # a DIFFERENT grade - the shape needed to test both halves of the boundary: sibling
    # sections now share material, other grades still must not.
    class_a = SchoolClass(
        name="RAG 3 - A", academic_year=ACADEMIC_YEAR, grade_level=3, section="A",
        school_id=school.id, class_teacher_id=teacher.id,
    )
    class_b = SchoolClass(
        name="RAG 3 - B", academic_year=ACADEMIC_YEAR, grade_level=3, section="B",
        school_id=school.id, class_teacher_id=other_teacher.id,
    )
    class_g4 = SchoolClass(
        name="RAG 4 - A", academic_year=ACADEMIC_YEAR, grade_level=4, section="A",
        school_id=school.id, class_teacher_id=other_teacher.id,
    )
    db_session.add_all([class_a, class_b, class_g4])
    db_session.flush()

    student_a = _make_user(db_session, "student", "student-a", school)
    student_b = _make_user(db_session, "student", "student-b", school)
    student_g4 = _make_user(db_session, "student", "student-g4", school)
    db_session.add_all([
        Enrollment(student_id=student_a.id, class_id=class_a.id, subject_id=None, is_primary=True),
        Enrollment(student_id=student_b.id, class_id=class_b.id, subject_id=None, is_primary=True),
        Enrollment(student_id=student_g4.id, class_id=class_g4.id, subject_id=None, is_primary=True),
    ])
    db_session.commit()
    return {
        "school": school, "teacher": teacher, "other_teacher": other_teacher,
        "class_a": class_a, "class_b": class_b, "class_g4": class_g4,
        "student_a": student_a, "student_b": student_b, "student_g4": student_g4,
    }


# --- SILENTLY WRONG: embedding normalization -------------------------------------
# gemini-embedding-001 returns UNNORMALIZED vectors at any truncated dimensionality
# (verified live: raw L2 norm ~0.692 at 1536 dims). Cosine distance over unnormalized
# vectors still returns numbers in a believable range with subtly wrong ORDERING -
# retrieval that looks like it works and quietly returns the wrong chunks.


def test_l2_normalize_produces_unit_length():
    vector = [3.0, 4.0] + [0.0] * (DIM - 2)
    normalized = l2_normalize(vector)
    assert math.isclose(math.sqrt(sum(x * x for x in normalized)), 1.0, rel_tol=1e-9)
    # Direction preserved: 3-4-5 triangle scales to 0.6 / 0.8.
    assert math.isclose(normalized[0], 0.6, rel_tol=1e-9)
    assert math.isclose(normalized[1], 0.8, rel_tol=1e-9)


def test_l2_normalize_does_not_divide_by_zero():
    """A degenerate all-zero vector must not raise - it cannot come from the real API,
    but a mocked or malformed one should not take the ingestion down with it."""
    assert l2_normalize([0.0] * 8) == [0.0] * 8


# --- SILENTLY WRONG: cosine ordering ----------------------------------------------


def test_search_chunks_orders_by_cosine_distance_ascending(db_session, rag_seed):
    """Nearest first. A reversed or unordered result set would still return plausible
    chunks and would only show up as consistently mediocre answers."""
    near = _unit_vector(axis=0)
    far = _unit_vector(axis=1)
    db_session.add_all([
        KbChunk(source_type=SOURCE_TYPE_RESOURCE, source_id=9001, chunk_index=0, chunk_text="near chunk",
                embedding=near, school_id=rag_seed["school"].id, grade_level=3),
        KbChunk(source_type=SOURCE_TYPE_RESOURCE, source_id=9001, chunk_index=1, chunk_text="far chunk",
                embedding=far, school_id=rag_seed["school"].id, grade_level=3),
    ])
    db_session.commit()

    hits = search_chunks(db_session, query_embedding=near, school_id=rag_seed["school"].id, grade_level=3, top_k=5)
    assert [h.chunk_text for h in hits] == ["near chunk", "far chunk"]
    assert hits[0].distance == pytest.approx(0.0, abs=1e-6)
    assert hits[1].distance == pytest.approx(1.0, abs=1e-6)  # orthogonal
    assert hits[0].distance < hits[1].distance


# --- SECURITY: retrieval scope ----------------------------------------------------


def test_search_chunks_never_returns_another_grades_chunks(db_session, rag_seed):
    """The scope filters are WHERE clauses, not a post-filter. A post-filter would let
    out-of-scope chunks occupy the top-k slots and silently return fewer."""
    shared = _unit_vector(axis=0)
    db_session.add_all([
        KbChunk(source_type=SOURCE_TYPE_RESOURCE, source_id=9002, chunk_index=0, chunk_text="grade 3 material",
                embedding=shared, school_id=rag_seed["school"].id, grade_level=3),
        KbChunk(source_type=SOURCE_TYPE_RESOURCE, source_id=9003, chunk_index=0, chunk_text="grade 4 material",
                embedding=shared, school_id=rag_seed["school"].id, grade_level=4),
    ])
    db_session.commit()

    hits = search_chunks(db_session, query_embedding=shared, school_id=rag_seed["school"].id, grade_level=3, top_k=10)
    texts = [h.chunk_text for h in hits]
    assert "grade 3 material" in texts
    assert "grade 4 material" not in texts


def test_search_chunks_never_crosses_schools_at_the_same_grade(db_session, rag_seed):
    """grade_level is a bare integer, not an FK - grade 3 exists in EVERY school. If
    school_id were ever dropped from the filter this is the test that catches it, and
    the failure would otherwise be a silent cross-tenant leak."""
    other_school = School(name="Foreign RAG School")
    db_session.add(other_school)
    db_session.flush()
    shared = _unit_vector(axis=0)
    db_session.add_all([
        KbChunk(source_type=SOURCE_TYPE_RESOURCE, source_id=9101, chunk_index=0, chunk_text="ours",
                embedding=shared, school_id=rag_seed["school"].id, grade_level=3),
        KbChunk(source_type=SOURCE_TYPE_RESOURCE, source_id=9102, chunk_index=0, chunk_text="theirs",
                embedding=shared, school_id=other_school.id, grade_level=3),
    ])
    db_session.commit()

    hits = search_chunks(db_session, query_embedding=shared, school_id=rag_seed["school"].id, grade_level=3, top_k=10)
    texts = [h.chunk_text for h in hits]
    assert "ours" in texts
    assert "theirs" not in texts


def test_subject_is_inferred_from_retrieved_chunks_when_not_supplied(db_session, rag_seed):
    """The Doubt Bot UI sends only class_id - a student never classifies their own
    question - but Top Doubts aggregates by SUBJECT and its per-teacher endpoint always
    filters by one. Without inference every real question logged subject_id=NULL and was
    invisible to the teacher's widget, while seeded fixtures (which set it explicitly)
    still showed up - a gap that looked like a working feature."""
    from app.services.retrieval import RetrievedChunk, infer_subject_id

    # Majority wins.
    chunks = [
        RetrievedChunk(chunk_id=1, source_id=1, chunk_text="a", distance=0.10, title=None, subject_id=7),
        RetrievedChunk(chunk_id=2, source_id=1, chunk_text="b", distance=0.20, title=None, subject_id=7),
        RetrievedChunk(chunk_id=3, source_id=2, chunk_text="c", distance=0.15, title=None, subject_id=9),
    ]
    assert infer_subject_id(chunks) == 7

    # A 1-1 split is broken by the NEAREST chunk, not by iteration order.
    tied = [
        RetrievedChunk(chunk_id=1, source_id=1, chunk_text="a", distance=0.40, title=None, subject_id=7),
        RetrievedChunk(chunk_id=2, source_id=2, chunk_text="b", distance=0.10, title=None, subject_id=9),
    ]
    assert infer_subject_id(tied) == 9

    # Honest None rather than a guess when there is nothing to infer from.
    assert infer_subject_id([]) is None
    assert infer_subject_id(
        [RetrievedChunk(chunk_id=1, source_id=1, chunk_text="a", distance=0.1, title=None, subject_id=None)]
    ) is None


def test_student_cannot_claim_a_class_they_are_not_enrolled_in(db_session, rag_seed):
    """THE Doubt Bot security boundary. class_id comes from the request body, so a
    student editing that number must be rejected before any retrieval happens - even
    though scope has widened to grade level, the CLASS enrollment check is what stops a
    student naming a class (and therefore a grade) that isn't theirs."""
    from fastapi import HTTPException

    # Own class -> resolves to that class's (school_id, grade_level).
    assert assert_student_class_access(
        db_session, student_id=rag_seed["student_a"].id, class_id=rag_seed["class_a"].id
    ) == (rag_seed["school"].id, 3)

    # A class at another grade, that they are not enrolled in.
    with pytest.raises(HTTPException) as exc:
        assert_student_class_access(
            db_session, student_id=rag_seed["student_a"].id, class_id=rag_seed["class_g4"].id
        )
    assert exc.value.status_code == 403


def test_sibling_sections_of_a_grade_now_share_material(db_session, rag_seed):
    """DELIBERATE WIDENING, documented as a test so it can't be mistaken for a leak.

    Under the old class_id scoping a Grade 3 - A student could not see material
    uploaded for Grade 3 - B. Sections of a grade follow the same curriculum, so they
    now resolve to the same (school_id, grade_level) scope and share a corpus. If this
    test ever fails, the re-scope has been partially reverted."""
    scope_a = assert_student_class_access(
        db_session, student_id=rag_seed["student_a"].id, class_id=rag_seed["class_a"].id
    )
    scope_b = assert_student_class_access(
        db_session, student_id=rag_seed["student_b"].id, class_id=rag_seed["class_b"].id
    )
    assert scope_a == scope_b


# --- SILENTLY WRONG: chunking + upsert idempotency --------------------------------


def test_chunk_text_overlaps_so_boundary_facts_are_not_lost():
    text = "\n\n".join(f"Paragraph {i} with enough words to matter here." for i in range(60))
    chunks = chunk_text(text, target_chars=400, overlap_chars=100)
    assert len(chunks) > 1
    # Consecutive chunks must share text, or a fact spanning the boundary is
    # unretrievable from either side.
    assert any(chunks[0][-40:] in chunks[1] for _ in [0]) or chunks[1].startswith(chunks[0][-40:][:10])


def test_chunk_text_returns_single_chunk_when_short():
    assert chunk_text("short note") == ["short note"]


def test_reingesting_updates_chunks_in_place_instead_of_duplicating(db_session, rag_seed, monkeypatch):
    """The unique key on (source_type, source_id, chunk_index) is what makes reindex
    idempotent. Without it every reindex would double the corpus and bias retrieval
    toward whatever had been ingested most often - with no error anywhere."""
    from app.services import ingestion

    resource = Resource(
        school_id=rag_seed["school"].id, grade_level=3, subject_id=None,
        title="Reindex Me", file_url="fake/path.md", mime_type="text/markdown",
        uploaded_by=rag_seed["teacher"].id,
    )
    db_session.add(resource)
    db_session.commit()

    monkeypatch.setattr(ingestion, "download_resource_file", lambda path: b"alpha content here")
    monkeypatch.setattr(ingestion, "embed_documents", lambda texts: [_unit_vector(axis=0) for _ in texts])

    first = ingestion.ingest_resource(db_session, resource.id)
    db_session.commit()
    count_after_first = db_session.query(KbChunk).filter(KbChunk.source_id == resource.id).count()

    second = ingestion.ingest_resource(db_session, resource.id)
    db_session.commit()
    count_after_second = db_session.query(KbChunk).filter(KbChunk.source_id == resource.id).count()

    assert first == second
    assert count_after_first == count_after_second, "re-ingestion duplicated chunks"
    assert resource.indexed_at is not None


def test_reingesting_a_shortened_resource_deletes_orphan_chunks(db_session, rag_seed, monkeypatch):
    """An edited, shorter document must not leave stale chunks behind - they would stay
    searchable forever, citing text no longer in the document."""
    from app.services import ingestion

    resource = Resource(
        school_id=rag_seed["school"].id, grade_level=3, subject_id=None,
        title="Shrinking", file_url="fake/shrink.md", mime_type="text/markdown",
        uploaded_by=rag_seed["teacher"].id,
    )
    db_session.add(resource)
    db_session.commit()

    monkeypatch.setattr(ingestion, "embed_documents", lambda texts: [_unit_vector(axis=0) for _ in texts])
    long_text = "\n\n".join(f"Section {i} " + ("word " * 120) for i in range(4))
    monkeypatch.setattr(ingestion, "download_resource_file", lambda path: long_text.encode())
    ingestion.ingest_resource(db_session, resource.id)
    db_session.commit()
    many = db_session.query(KbChunk).filter(KbChunk.source_id == resource.id).count()
    assert many > 1

    monkeypatch.setattr(ingestion, "download_resource_file", lambda path: b"now very short")
    ingestion.ingest_resource(db_session, resource.id)
    db_session.commit()
    few = db_session.query(KbChunk).filter(KbChunk.source_id == resource.id).count()
    assert few == 1, f"orphan chunks left behind: {few} rows remain"


# --- SECURITY: resource upload + read scoping -------------------------------------


def test_teacher_cannot_upload_to_a_grade_they_do_not_teach(client, rag_seed):
    _override_user("teacher", user_id=rag_seed["teacher"].id, school_id=rag_seed["school"].id)
    resp = client.post(
        "/resources/upload",
        files={"file": ("notes.md", b"# hello", "text/markdown")},
        data={"title": "Sneaky", "grade_level": "4"},
    )
    assert resp.status_code == 403


def test_upload_rejects_unsupported_file_type(client, rag_seed):
    """PDF is now accepted (pypdf text extraction), but anything else still must not be
    ingested as binary mojibake - a corpus quietly full of garbage is worse than a
    refused upload."""
    _override_user("teacher", user_id=rag_seed["teacher"].id, school_id=rag_seed["school"].id)
    resp = client.post(
        "/resources/upload",
        files={"file": ("sheet.xlsx", b"PK binary", "application/vnd.ms-excel")},
        data={"title": "A spreadsheet", "grade_level": "3"},
    )
    assert resp.status_code == 415


def test_student_listing_sees_sibling_sections_material(client, db_session, rag_seed):
    """Companion to test_sibling_sections_of_a_grade_now_share_material, at the HTTP
    layer: a 3-A student sees a resource uploaded for grade 3 regardless of section."""
    db_session.add(
        Resource(school_id=rag_seed["school"].id, grade_level=3, subject_id=None,
                 title="Grade 3 shared", file_url="g3.md", mime_type="text/markdown",
                 uploaded_by=rag_seed["other_teacher"].id)
    )
    db_session.commit()
    _override_user("student", user_id=rag_seed["student_a"].id, school_id=rag_seed["school"].id)
    titles = [i["title"] for i in client.get("/resources").json()["items"]]
    assert "Grade 3 shared" in titles


def test_upload_cannot_target_a_grade_that_exists_only_in_another_school(client, db_session, rag_seed):
    """Cross-tenant upload is now STRUCTURALLY impossible rather than a 403: the
    resource's school_id is taken from the caller's token and is not a request field at
    all, so there is nothing to forge. What remains checkable is that naming a grade
    which exists only in someone else's school is rejected (400) instead of quietly
    creating an unreachable resource in the caller's own school.

    Replaces test_admin_cannot_upload_into_another_schools_class, which asserted a 403
    that the shape of the endpoint no longer makes reachable.
    """
    other_school = School(name="Other RAG School")
    db_session.add(other_school)
    db_session.flush()
    db_session.add(
        SchoolClass(
            name="Foreign 9 - A", academic_year=ACADEMIC_YEAR, grade_level=9, section="A",
            school_id=other_school.id,
        )
    )
    db_session.commit()

    _override_user("admin", user_id=rag_seed["teacher"].id, school_id=rag_seed["school"].id)
    resp = client.post(
        "/resources/upload",
        files={"file": ("notes.md", b"# hello", "text/markdown")},
        data={"title": "Cross tenant", "grade_level": "9"},
    )
    assert resp.status_code == 400
    assert "grade 9" in resp.json()["detail"].lower()


def test_student_listing_resources_sees_only_their_own_grade(client, db_session, rag_seed):
    db_session.add_all([
        Resource(school_id=rag_seed["school"].id, grade_level=3, subject_id=None,
                 title="A material", file_url="a.md", mime_type="text/markdown", uploaded_by=rag_seed["teacher"].id),
        Resource(school_id=rag_seed["school"].id, grade_level=4, subject_id=None,
                 title="B material", file_url="b.md", mime_type="text/markdown", uploaded_by=rag_seed["other_teacher"].id),
    ])
    db_session.commit()

    _override_user("student", user_id=rag_seed["student_a"].id, school_id=rag_seed["school"].id)
    resp = client.get("/resources")
    assert resp.status_code == 200
    titles = [i["title"] for i in resp.json()["items"]]
    assert "A material" in titles          # grade 3, theirs
    assert "B material" not in titles      # grade 4, not theirs


def test_student_requesting_another_grade_gets_403_not_empty_list(client, rag_seed):
    """403, never a silently empty list - an empty list reads as "nothing exists here"
    rather than "not yours", which hides the boundary from anyone testing it."""
    _override_user("student", user_id=rag_seed["student_a"].id, school_id=rag_seed["school"].id)
    resp = client.get("/resources", params={"grade_level": 4})
    assert resp.status_code == 403


def test_resources_router_requires_authentication(client):
    """One 401 test for the router is enough (per the testing amendment)."""
    assert client.get("/resources").status_code == 401
