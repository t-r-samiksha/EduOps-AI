"""Doubt threads: security boundaries, and the ingest/retract loop.

Reduced test scope - security and silently-wrong paths only. The "silently wrong" one
here is a retracted answer that stays in the corpus: unverify that only cleared a flag
would leave content permanently searchable with no error anywhere.
"""

import uuid

import pytest

from app.main import app
from app.models.audit import AuditLogEntry
from app.models.class_ import SchoolClass
from app.models.doubt import DoubtThread, ThreadReply
from app.models.enrollment import Enrollment
from app.models.knowledge import SOURCE_TYPE_VERIFIED_DOUBT_ANSWER, KbChunk
from app.models.notification import Notification
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"
DIM = 1536


def _override_user(role: str, user_id: int, school_id: int | None):
    def _fake_user():
        return CurrentUser(
            id=user_id, sub=str(uuid.uuid4()), email="t@example.com", role=role, school_id=school_id
        )

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    """Ingestion is exercised for real EXCEPT the network call - a unit vector is
    enough to prove the chunk was written, and these tests must not depend on a live
    Gemini key or spend ~1s per verify."""

    def _fake(chunks):
        vector = [0.0] * DIM
        vector[0] = 1.0
        return [list(vector) for _ in chunks]

    monkeypatch.setattr("app.services.ingestion.embed_documents", _fake)


def _user(db, role_name: str, school_id: int, name: str) -> User:
    role = db.query(Role).filter(Role.name == role_name).one()
    row = User(
        supabase_id=uuid.uuid4(),
        email=f"{name.replace(' ', '.').lower()}-{uuid.uuid4()}@example.com",
        full_name=name,
        role_id=role.id,
        school_id=school_id,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def seed(db_session):
    """Two sections of grade 3 with DIFFERENT homeroom teachers, plus a second school.

    The 3-A/3-B split is the shape the cross-class verify test needs: same school, same
    grade, different owning teacher.
    """
    school = School(name="Threads Test School")
    other_school = School(name="Threads Other School")
    db_session.add_all([school, other_school])
    db_session.flush()

    teacher_a = _user(db_session, "teacher", school.id, "Teacher A")
    teacher_b = _user(db_session, "teacher", school.id, "Teacher B")
    subject_teacher = _user(db_session, "teacher", school.id, "Subject Teacher")
    student_a = _user(db_session, "student", school.id, "Student A")
    student_b = _user(db_session, "student", school.id, "Student B")
    admin = _user(db_session, "admin", school.id, "Admin One")

    other_teacher = _user(db_session, "teacher", other_school.id, "Other Teacher")
    other_student = _user(db_session, "student", other_school.id, "Other Student")

    class_a = SchoolClass(
        name="T 3 - A", academic_year=ACADEMIC_YEAR, grade_level=3, section="A",
        school_id=school.id, class_teacher_id=teacher_a.id,
    )
    class_b = SchoolClass(
        name="T 3 - B", academic_year=ACADEMIC_YEAR, grade_level=3, section="B",
        school_id=school.id, class_teacher_id=teacher_b.id,
    )
    other_class = SchoolClass(
        name="O 3 - A", academic_year=ACADEMIC_YEAR, grade_level=3, section="A",
        school_id=other_school.id, class_teacher_id=other_teacher.id,
    )
    db_session.add_all([class_a, class_b, other_class])
    db_session.flush()

    db_session.add_all([
        Enrollment(student_id=student_a.id, class_id=class_a.id, is_primary=True),
        Enrollment(student_id=student_b.id, class_id=class_b.id, is_primary=True),
        Enrollment(student_id=other_student.id, class_id=other_class.id, is_primary=True),
    ])

    # The subject teacher teaches class_a a period but owns no class - the read/reply
    # widening, and the thing verify must still refuse.
    subject = Subject(name="T Math", school_id=school.id)
    room = Room(name="TR1", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add_all([subject, room])
    db_session.flush()
    db_session.add(
        TimetableSlot(
            day_of_week=0, period_number=1,
            start_time=__import__("datetime").time(8, 0), end_time=__import__("datetime").time(8, 45),
            subject_id=subject.id, teacher_id=subject_teacher.id, class_id=class_a.id,
            room_id=room.id, academic_year=ACADEMIC_YEAR, is_active=True,
        )
    )
    db_session.commit()

    return {
        "school": school, "other_school": other_school,
        "teacher_a": teacher_a, "teacher_b": teacher_b, "subject_teacher": subject_teacher,
        "student_a": student_a, "student_b": student_b, "admin": admin,
        "other_teacher": other_teacher, "other_student": other_student,
        "class_a": class_a, "class_b": class_b, "other_class": other_class,
        "subject": subject,
    }


def _as(seed, key: str, role: str, school_key: str = "school"):
    _override_user(role, seed[key].id, seed[school_key].id)


def _make_thread(db, seed, class_key: str, author_key: str, title="Why does ice float?") -> DoubtThread:
    cls = seed[class_key]
    thread = DoubtThread(
        school_id=cls.school_id, class_id=cls.id, subject_id=seed["subject"].id,
        author_id=seed[author_key].id, title=title, body="Everything else sinks when solid.",
    )
    db.add(thread)
    db.flush()
    reply = ThreadReply(thread_id=thread.id, author_id=seed[author_key].id, body="Maybe it's about density?")
    db.add(reply)
    db.commit()
    db.refresh(thread)
    db.refresh(reply)
    return thread, reply


def _chunks(db, thread_id: int):
    return (
        db.query(KbChunk)
        .filter(KbChunk.source_type == SOURCE_TYPE_VERIFIED_DOUBT_ANSWER, KbChunk.source_id == thread_id)
        .all()
    )


# =============================================================================
# THE FIVE REQUIRED SECURITY TESTS
# =============================================================================


def test_security_student_cannot_post_to_a_class_they_are_not_enrolled_in(client, seed):
    """SECURITY 1a. class_id arrives from the client, so it is validated against the
    caller's own enrollment server-side - never trusted from the body."""
    _as(seed, "student_a", "student")
    resp = client.post(
        "/threads",
        json={"class_id": seed["class_b"].id, "title": "Sneaking in", "body": "I am not in 3-B"},
    )
    assert resp.status_code == 403
    assert "not enrolled" in resp.json()["detail"]


def test_security_student_cannot_read_a_class_they_are_not_enrolled_in(client, seed, db_session):
    """SECURITY 1b. The read side of the same boundary - list and detail."""
    thread, _reply = _make_thread(db_session, seed, "class_b", "student_b")

    _as(seed, "student_a", "student")
    assert client.get("/threads", params={"class_id": seed["class_b"].id}).status_code == 403
    assert client.get(f"/threads/{thread.id}").status_code == 403
    assert client.post(f"/threads/{thread.id}/reply", json={"body": "hello"}).status_code == 403


def test_security_student_cannot_verify_a_reply(client, seed, db_session):
    """SECURITY 2. The teacher's judgement is the only thing separating this corpus
    from unmoderated student guesses - a student certifying their own classmate's
    answer would put anything into the bot."""
    thread, reply = _make_thread(db_session, seed, "class_a", "student_a")

    _as(seed, "student_a", "student")
    resp = client.put(f"/threads/{thread.id}/verify/{reply.id}")
    assert resp.status_code == 403

    # And nothing reached the knowledge base.
    assert _chunks(db_session, thread.id) == []
    db_session.refresh(thread)
    assert thread.resolved is False
    assert thread.verified_reply_id is None


def test_security_teacher_cannot_verify_in_a_class_they_do_not_teach(client, seed, db_session):
    """SECURITY 3. A teacher with no relationship to the class at all."""
    thread, reply = _make_thread(db_session, seed, "class_a", "student_a")

    stranger = _user(db_session, "teacher", seed["school"].id, "Stranger Teacher")
    db_session.commit()

    _override_user("teacher", stranger.id, seed["school"].id)
    resp = client.put(f"/threads/{thread.id}/verify/{reply.id}")
    assert resp.status_code == 403
    assert _chunks(db_session, thread.id) == []


def test_security_homeroom_teacher_of_another_section_cannot_verify(client, seed, db_session):
    """SECURITY 4. CROSS-CLASS WITHIN ONE SCHOOL - both teachers are legitimate homeroom
    teachers of the same grade in the same school, and a verified answer from either thread
    lands in the same grade-3 corpus. A teacher with no link to 3-B must not touch a 3-B
    thread.

    (a) no relationship to 3-B at all -> refused, at the membership gate. Unchanged.
    (b) TEACHES 3-B but is homeroom of 3-A -> NOW ALLOWED to certify.

    Case (b) INVERTED on 2026-08-18 with the verify-policy change. It used to assert 403
    here, and this docstring used to call it "the one that would silently pass if verify had
    reused the wider _teaching_class_ids" - which is now exactly what verify does, on
    purpose. The reasoning for the old rule (certification reaches the whole grade, so it
    should sit with the class teacher) was overridden because the homeroom teacher may not
    teach the subject in question at all, leaving the qualified teacher unable to verify.
    Kept as a test rather than deleted, so the boundary that DOES still hold - (a), a teacher
    with no relationship to the class - stays covered.
    """
    import datetime

    thread, reply = _make_thread(db_session, seed, "class_b", "student_b")

    # (a) Teacher A owns 3-A and has no link to 3-B - refused as a non-member.
    _as(seed, "teacher_a", "teacher")
    resp = client.put(f"/threads/{thread.id}/verify/{reply.id}")
    assert resp.status_code == 403
    assert "do not teach this class" in resp.json()["detail"]
    assert _chunks(db_session, thread.id) == []

    # (b) Now give Teacher A a real period in 3-B. They are a legitimate member of 3-B
    # and can read and reply there - but still must not certify for it.
    db_session.add(
        TimetableSlot(
            day_of_week=1, period_number=2,
            start_time=datetime.time(9, 0), end_time=datetime.time(9, 45),
            subject_id=seed["subject"].id, teacher_id=seed["teacher_a"].id,
            class_id=seed["class_b"].id,
            room_id=db_session.query(Room).filter(Room.school_id == seed["school"].id).first().id,
            academic_year=ACADEMIC_YEAR, is_active=True,
        )
    )
    db_session.commit()

    _as(seed, "teacher_a", "teacher")
    # Membership now genuinely holds - they can see and answer the thread...
    assert client.get(f"/threads/{thread.id}").status_code == 200
    assert client.post(f"/threads/{thread.id}/reply", json={"body": "A thought."}).status_code == 200
    # ...and since 2026-08-18 they may certify for it too, because they teach it.
    assert client.put(f"/threads/{thread.id}/verify/{reply.id}").status_code == 200
    assert len(_chunks(db_session, thread.id)) == 1

    # Unverify, so 3-B's own homeroom teacher re-verifying below is a real assertion rather
    # than a no-op on an already-verified reply.
    assert client.put(f"/threads/{thread.id}/unverify").status_code == 200
    assert _chunks(db_session, thread.id) == []

    # 3-B's own homeroom teacher can, as always.
    _as(seed, "teacher_b", "teacher")
    assert client.put(f"/threads/{thread.id}/verify/{reply.id}").status_code == 200
    assert len(_chunks(db_session, thread.id)) == 1


def test_security_cross_school_access_returns_no_data(client, seed, db_session):
    """SECURITY 5. Another school's thread must never return data - and a 404 rather
    than a 403 where the class isn't the caller's, so probing ids cannot distinguish
    "exists, not yours" from "doesn't exist"."""
    thread, reply = _make_thread(db_session, seed, "other_class", "other_student")

    # A teacher from the first school.
    _as(seed, "teacher_a", "teacher")
    assert client.get(f"/threads/{thread.id}").status_code == 403
    assert client.get("/threads", params={"class_id": seed["other_class"].id}).status_code == 403
    assert client.put(f"/threads/{thread.id}/verify/{reply.id}").status_code == 403
    assert client.post(f"/threads/{thread.id}/reply", json={"body": "x"}).status_code == 403

    # An ADMIN of the first school - scoped by school_id, so 404 not 403.
    _as(seed, "admin", "admin")
    assert client.get(f"/threads/{thread.id}").status_code == 404
    assert client.get("/threads", params={"class_id": seed["other_class"].id}).status_code == 404

    assert _chunks(db_session, thread.id) == []


# =============================================================================
# The read/reply widening, and that it does NOT extend to verify
# =============================================================================


def test_subject_teacher_can_read_reply_and_verify(client, seed, db_session):
    """A teacher who teaches this class may read, reply AND verify.

    POLICY CHANGE, 2026-08-18, and a deliberate one. Verification used to be homeroom-only
    (scoping.teacher_class_ids) and this test asserted 403 here. The rationale on record was
    that a verified answer enters the GRADE-WIDE bot corpus, so certifying is a bigger act
    than replying and belonged to the class teacher alone.

    That was overridden by product decision: the homeroom teacher of Grade 1-A may teach a
    different subject entirely, so the person actually qualified to judge a Maths answer was
    the one blocked - and a teacher with no homeroom could never verify anything at all. Read,
    reply and verify now share `_teaching_class_ids`.

    What still holds, and is covered by SECURITY 3/4/5 below: a teacher with NO relationship
    to the class cannot verify, and nobody can verify across schools.
    """
    thread, reply = _make_thread(db_session, seed, "class_a", "student_a")

    _as(seed, "subject_teacher", "teacher")
    assert client.get(f"/threads/{thread.id}").status_code == 200
    assert client.post(f"/threads/{thread.id}/reply", json={"body": "Think about density."}).status_code == 200

    assert client.put(f"/threads/{thread.id}/verify/{reply.id}").status_code == 200
    # And the answer really does reach the corpus - the point of verifying.
    assert len(_chunks(db_session, thread.id)) == 1


# =============================================================================
# SILENTLY WRONG: a retracted answer that stays searchable
# =============================================================================


def test_unverify_deletes_the_kb_chunks(client, seed, db_session):
    """THE silently-wrong path. Unverify that only cleared a flag would leave the
    answer permanently retrievable - a teacher who withdrew a wrong answer would keep
    watching the bot cite it, with no error and no way out short of SQL."""
    thread, reply = _make_thread(db_session, seed, "class_a", "student_a")

    _as(seed, "teacher_a", "teacher")
    verify = client.put(f"/threads/{thread.id}/verify/{reply.id}")
    assert verify.status_code == 200
    assert verify.json()["chunks_written"] == 1
    assert "knowledge base" in verify.json()["kb_note"]
    chunk = _chunks(db_session, thread.id)[0]
    # Grade-level, from the thread's class - NOT class-level. See models/doubt.py.
    assert chunk.grade_level == 3
    assert chunk.school_id == seed["school"].id
    assert chunk.chunk_index == 0

    unverify = client.put(f"/threads/{thread.id}/unverify")
    assert unverify.status_code == 200
    assert unverify.json()["chunks_deleted"] == 1
    assert _chunks(db_session, thread.id) == []

    # The reply itself survives - only its KB copy was retracted.
    db_session.refresh(thread)
    assert thread.resolved is False
    assert thread.verified_reply_id is None
    assert db_session.query(ThreadReply).filter(ThreadReply.id == reply.id).one_or_none() is not None


def test_reverifying_a_different_reply_replaces_the_chunk_rather_than_adding_one(client, seed, db_session):
    """Idempotency via the unique (source_type, source_id, chunk_index) key. Without
    it, a teacher changing their mind would leave two answers to the same question
    competing in retrieval."""
    thread, first_reply = _make_thread(db_session, seed, "class_a", "student_a")
    second = ThreadReply(
        thread_id=thread.id, author_id=seed["teacher_a"].id,
        body="Water expands when it freezes, so ice is less dense than liquid water.",
    )
    db_session.add(second)
    db_session.commit()

    _as(seed, "teacher_a", "teacher")
    client.put(f"/threads/{thread.id}/verify/{first_reply.id}")
    assert len(_chunks(db_session, thread.id)) == 1

    client.put(f"/threads/{thread.id}/verify/{second.id}")
    rows = _chunks(db_session, thread.id)
    assert len(rows) == 1, "re-verifying must overwrite chunk 0, not append"
    assert "Water expands when it freezes" in rows[0].chunk_text


def test_verify_rejects_a_reply_from_another_thread(client, seed, db_session):
    thread_a, _ = _make_thread(db_session, seed, "class_a", "student_a")
    thread_b, reply_b = _make_thread(db_session, seed, "class_a", "student_a", title="Second doubt")

    _as(seed, "teacher_a", "teacher")
    resp = client.put(f"/threads/{thread_a.id}/verify/{reply_b.id}")
    assert resp.status_code == 400
    assert "different thread" in resp.json()["detail"]


def test_unverify_an_unverified_thread_is_a_400(client, seed, db_session):
    thread, _ = _make_thread(db_session, seed, "class_a", "student_a")
    _as(seed, "teacher_a", "teacher")
    resp = client.put(f"/threads/{thread.id}/unverify")
    assert resp.status_code == 400
    assert "no verified answer" in resp.json()["detail"]


def test_verify_writes_an_audit_row_and_notifies_the_author(client, seed, db_session):
    thread, reply = _make_thread(db_session, seed, "class_a", "student_a")
    _as(seed, "teacher_a", "teacher")
    client.put(f"/threads/{thread.id}/verify/{reply.id}")

    entry = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.action == "verify_doubt_answer", AuditLogEntry.entity_id == thread.id)
        .one()
    )
    assert entry.actor_id == seed["teacher_a"].id
    assert entry.detail["chunks_written"] == 1
    assert entry.detail["grade_level"] == 3

    note = (
        db_session.query(Notification)
        .filter(Notification.source_type == "doubt_answer_verified", Notification.source_id == thread.id)
        .one()
    )
    assert note.user_id == seed["student_a"].id
    assert "knowledge base" in note.body


# =============================================================================
# Ordinary behaviour worth pinning
# =============================================================================


def test_thread_list_puts_unresolved_first(client, seed, db_session):
    """A thread list is a work queue for the teacher, not a chronological log."""
    open_thread, _ = _make_thread(db_session, seed, "class_a", "student_a", title="Still open")
    done_thread, done_reply = _make_thread(db_session, seed, "class_a", "student_a", title="Answered")

    _as(seed, "teacher_a", "teacher")
    client.put(f"/threads/{done_thread.id}/verify/{done_reply.id}")

    items = client.get("/threads", params={"class_id": seed["class_a"].id}).json()["items"]
    assert items[0]["id"] == open_thread.id
    assert items[0]["resolved"] is False
    assert items[-1]["id"] == done_thread.id
    assert items[-1]["verified_reply"]["body"].startswith("Maybe it's about density")


def test_thread_detail_flags_the_verified_reply_in_place(client, seed, db_session):
    thread, reply = _make_thread(db_session, seed, "class_a", "student_a")
    extra = ThreadReply(thread_id=thread.id, author_id=seed["teacher_a"].id, body="Second reply.")
    db_session.add(extra)
    db_session.commit()

    _as(seed, "teacher_a", "teacher")
    client.put(f"/threads/{thread.id}/verify/{extra.id}")

    detail = client.get(f"/threads/{thread.id}").json()
    by_id = {r["id"]: r for r in detail["replies"]}
    assert by_id[extra.id]["is_verified"] is True
    assert by_id[reply.id]["is_verified"] is False
    # Chronological order preserved.
    assert [r["id"] for r in detail["replies"]] == [reply.id, extra.id]


def test_thread_creation_ignores_a_school_id_it_was_not_given(client, seed):
    """school_id comes from the VALIDATED class, never the request - a client that
    could name one could plant a thread in another tenant."""
    _as(seed, "student_a", "student")
    resp = client.post(
        "/threads",
        json={"class_id": seed["class_a"].id, "title": "Legit", "body": "Question body"},
    )
    assert resp.status_code == 200
    assert resp.json()["school_id"] == seed["school"].id


def test_blank_title_or_body_is_rejected(client, seed):
    _as(seed, "student_a", "student")
    for payload in (
        {"class_id": seed["class_a"].id, "title": "   ", "body": "ok"},
        {"class_id": seed["class_a"].id, "title": "ok", "body": "   "},
    ):
        assert client.post("/threads", json=payload).status_code == 400


def test_threads_require_authentication(client, seed):
    assert client.get("/threads", params={"class_id": seed["class_a"].id}).status_code == 401
    assert client.post("/threads", json={"class_id": 1, "title": "a", "body": "b"}).status_code == 401
