"""Doubt threads: students ask, the class answers, the teacher certifies one reply.

Implements the older `POST /doubts` / `GET /doubts/{thread_id}` stubs at `/threads/*`
instead - see the reconciliation table in docs/api-contract.md. Renamed because
"/doubts" now collides with two shipped features that answer questions rather than host
them: the Doubt Bot (routers/bots.py) and Top Doubts (services/doubt_insights.py).

THE POINT OF THIS ROUTER IS THE VERIFY ENDPOINT. Threads are ordinary CRUD; verifying a
reply is what feeds a human teacher's answer into the RAG corpus, so the bot starts
citing a person instead of a PDF. Unverify deletes those chunks again, because a
retraction that only cleared a flag would leave unremovable content in the bot.

TEACHER SCOPE IS TWO DIFFERENT RULES, deliberately:
  - read/reply: homeroom teacher OR any teacher with an active slot for that class. A
    subject teacher who teaches Grade 1-A Math has to be able to answer a Grade 1-A
    Math doubt, and homeroom-only would lock them out of the feature entirely.
  - verify/unverify: homeroom teacher ONLY (services/scoping.teacher_class_ids).
    Certifying content into the grade-wide corpus is the class teacher's call.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.doubt import DoubtThread, ThreadReply
from app.models.enrollment import Enrollment
from app.models.timetable import TimetableSlot
from app.models.user import User
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.ingestion import ingest_verified_doubt_answer, remove_verified_doubt_answer
from app.services.notify import dispatch_notification
from app.services.scoping import teacher_class_ids

router = APIRouter(prefix="/threads", tags=["threads"])


# --- Response models ------------------------------------------------------------------


class ReplyOut(BaseModel):
    id: int
    thread_id: int
    author_id: int
    author_name: str
    body: str
    created_at: datetime
    is_verified: bool


class ThreadOut(BaseModel):
    id: int
    school_id: int
    class_id: int
    class_name: str | None
    subject_id: int | None
    title: str
    body: str
    author_id: int
    author_name: str
    resolved: bool
    verified_reply_id: int | None
    reply_count: int
    created_at: datetime
    verified_reply: ReplyOut | None


class ThreadDetailOut(ThreadOut):
    replies: list[ReplyOut]
    """Chronological. The verified one is also flagged in place via is_verified, so a
    client can pin it without having to cross-reference verified_reply_id."""


class ThreadListResponse(BaseModel):
    items: list[ThreadOut]


class CreateThreadRequest(BaseModel):
    class_id: int
    subject_id: int | None = None
    title: str
    body: str


class CreateReplyRequest(BaseModel):
    body: str


class VerifyResponse(BaseModel):
    thread: ThreadDetailOut
    chunks_written: int
    kb_note: str
    """Human-readable confirmation for the UI to show inline. The causal link between
    verifying and the bot getting smarter is the whole demo; a bare 200 hides it."""


class UnverifyResponse(BaseModel):
    thread: ThreadDetailOut
    chunks_deleted: int


# --- Scope helpers --------------------------------------------------------------------


def _display_name(user: User | None) -> str:
    if user is None:
        return "Unknown"
    return user.full_name or user.email or f"User #{user.id}"


def _teaching_class_ids(db: Session, teacher_id: int) -> set[int]:
    """Homeroom classes plus any class this teacher actually teaches a period to.

    Wider than scoping.teacher_class_ids on purpose, and used ONLY for read/reply -
    see the module docstring.
    """
    owned = set(teacher_class_ids(db, teacher_id))
    taught = {
        row.class_id
        for row in db.query(TimetableSlot.class_id).filter(
            TimetableSlot.teacher_id == teacher_id, TimetableSlot.is_active.is_(True)
        )
    }
    return owned | taught


def _assert_class_member(db: Session, user: CurrentUser, class_id: int) -> SchoolClass:
    """Verify the caller belongs to this class, and return it.

    THE security boundary for this router. `class_id` arrives from the client on
    create, so it is validated against the caller's own enrollment or teaching
    assignment server-side - never trusted. Same principle as
    retrieval.assert_student_class_access guards the bot.

    404 for a class outside the caller's school, so probing ids cannot distinguish
    "exists, not yours" from "doesn't exist".
    """
    school_class = db.query(SchoolClass).filter(SchoolClass.id == class_id).one_or_none()
    if school_class is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")

    if user.role == "student":
        enrolled = (
            db.query(Enrollment)
            .filter(
                Enrollment.student_id == user.id,
                Enrollment.class_id == class_id,
                Enrollment.is_primary.is_(True),
            )
            .first()
        )
        if enrolled is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not enrolled in this class")
        return school_class

    if user.role == "teacher":
        if class_id not in _teaching_class_ids(db, user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not teach this class")
        return school_class

    if user.role in ("admin", "principal"):
        if user.school_id is None or school_class.school_id != user.school_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
        return school_class

    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for class threads")


def _load_thread(db: Session, user: CurrentUser, thread_id: int) -> DoubtThread:
    thread = db.query(DoubtThread).filter(DoubtThread.id == thread_id).one_or_none()
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    _assert_class_member(db, user, thread.class_id)
    return thread


def _assert_homeroom_teacher(db: Session, user: CurrentUser, thread: DoubtThread) -> None:
    """The verify/unverify boundary - stricter than membership.

    A student must never be able to certify their own or a classmate's answer into the
    knowledge base: the teacher's judgement is the only thing separating this corpus
    from unmoderated student guesses. And a teacher may only certify for the class they
    are the class teacher of.
    """
    if user.role != "teacher":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a teacher can verify an answer")
    if thread.class_id not in teacher_class_ids(db, user.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only this class's teacher can verify an answer for it"
        )


# --- Serialisation --------------------------------------------------------------------


def _reply_out(reply: ThreadReply, *, author: User | None, verified_reply_id: int | None) -> ReplyOut:
    return ReplyOut(
        id=reply.id,
        thread_id=reply.thread_id,
        author_id=reply.author_id,
        author_name=_display_name(author),
        body=reply.body,
        created_at=reply.created_at,
        is_verified=reply.id == verified_reply_id,
    )


def _users_by_id(db: Session, ids: set[int]) -> dict[int, User]:
    if not ids:
        return {}
    return {u.id: u for u in db.query(User).filter(User.id.in_(ids))}


def _thread_out(
    db: Session, thread: DoubtThread, *, replies: list[ThreadReply] | None = None, detail: bool = False
):
    if replies is None:
        replies = (
            db.query(ThreadReply)
            .filter(ThreadReply.thread_id == thread.id)
            .order_by(ThreadReply.created_at, ThreadReply.id)
            .all()
        )
    users = _users_by_id(db, {thread.author_id} | {r.author_id for r in replies})
    school_class = db.query(SchoolClass).filter(SchoolClass.id == thread.class_id).one_or_none()

    verified = next((r for r in replies if r.id == thread.verified_reply_id), None)
    common = dict(
        id=thread.id,
        school_id=thread.school_id,
        class_id=thread.class_id,
        class_name=school_class.name if school_class else None,
        subject_id=thread.subject_id,
        title=thread.title,
        body=thread.body,
        author_id=thread.author_id,
        author_name=_display_name(users.get(thread.author_id)),
        resolved=thread.resolved,
        verified_reply_id=thread.verified_reply_id,
        reply_count=len(replies),
        created_at=thread.created_at,
        verified_reply=(
            _reply_out(verified, author=users.get(verified.author_id), verified_reply_id=thread.verified_reply_id)
            if verified is not None
            else None
        ),
    )
    if not detail:
        return ThreadOut(**common)
    return ThreadDetailOut(
        **common,
        replies=[
            _reply_out(r, author=users.get(r.author_id), verified_reply_id=thread.verified_reply_id)
            for r in replies
        ],
    )


# --- Endpoints ------------------------------------------------------------------------


@router.post("", response_model=ThreadOut)
def create_thread(
    body: CreateThreadRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    title = body.title.strip()
    text = body.body.strip()
    if not title:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "title must not be empty")
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "body must not be empty")

    school_class = _assert_class_member(db, user, body.class_id)

    thread = DoubtThread(
        # school_id comes from the VALIDATED class, never from the request - a client
        # that could name a school_id could plant a thread in another tenant.
        school_id=school_class.school_id,
        class_id=school_class.id,
        subject_id=body.subject_id,
        author_id=user.id,
        title=title,
        body=text,
        resolved=False,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return _thread_out(db, thread, replies=[])


@router.get("", response_model=ThreadListResponse)
def list_threads(
    class_id: int = Query(...),
    resolved: bool | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_class_member(db, user, class_id)

    query = db.query(DoubtThread).filter(DoubtThread.class_id == class_id)
    if resolved is not None:
        query = query.filter(DoubtThread.resolved.is_(resolved))
    threads = query.all()

    replies_by_thread: dict[int, list[ThreadReply]] = {}
    if threads:
        for reply in (
            db.query(ThreadReply)
            .filter(ThreadReply.thread_id.in_([t.id for t in threads]))
            .order_by(ThreadReply.created_at, ThreadReply.id)
        ):
            replies_by_thread.setdefault(reply.thread_id, []).append(reply)

    items = [_thread_out(db, t, replies=replies_by_thread.get(t.id, [])) for t in threads]
    # Unresolved first, then newest. A thread list is a work queue for the teacher, not
    # a chronological log - an answered doubt sinking below open ones is the point.
    items.sort(key=lambda t: (t.resolved, -t.created_at.timestamp()))
    return ThreadListResponse(items=items)


@router.get("/{thread_id}", response_model=ThreadDetailOut)
def get_thread(
    thread_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    thread = _load_thread(db, user, thread_id)
    return _thread_out(db, thread, detail=True)


@router.post("/{thread_id}/reply", response_model=ReplyOut)
def create_reply(
    thread_id: int,
    body: CreateReplyRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    text = body.body.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "body must not be empty")

    thread = _load_thread(db, user, thread_id)
    reply = ThreadReply(thread_id=thread.id, author_id=user.id, body=text)
    db.add(reply)

    # Tell the asker someone answered - unless they are answering themselves.
    if thread.author_id != user.id:
        author = db.query(User).filter(User.id == user.id).one_or_none()
        dispatch_notification(
            db,
            user_id=thread.author_id,
            source_type="doubt_reply",
            title=f"{_display_name(author)} replied to your doubt",
            body=f'"{thread.title}" — {text[:160]}',
            priority="normal",
            source_id=thread.id,
        )

    db.commit()
    db.refresh(reply)
    return _reply_out(
        reply,
        author=db.query(User).filter(User.id == reply.author_id).one_or_none(),
        verified_reply_id=thread.verified_reply_id,
    )


@router.put("/{thread_id}/verify/{reply_id}", response_model=VerifyResponse)
def verify_reply(
    thread_id: int,
    reply_id: int,
    user: CurrentUser = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
):
    """Certify a reply and ingest it into the knowledge base.

    Ingestion is INLINE and shares this transaction, so a failed embedding rolls the
    verification back with it. A thread flagged verified whose answer never reached the
    corpus is the worst outcome available: the teacher believes the bot knows something
    it does not.
    """
    thread = _load_thread(db, user, thread_id)
    _assert_homeroom_teacher(db, user, thread)

    reply = db.query(ThreadReply).filter(ThreadReply.id == reply_id).one_or_none()
    if reply is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reply not found")
    if reply.thread_id != thread.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That reply belongs to a different thread")

    previous_reply_id = thread.verified_reply_id
    thread.resolved = True
    thread.verified_reply_id = reply.id
    db.flush()

    try:
        chunks_written = ingest_verified_doubt_answer(db, thread.id)
    except ValueError as exc:
        # Unindexable states (no grade level on the class, missing reply) are the
        # caller's problem to fix, not a 500.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    school_class = db.query(SchoolClass).filter(SchoolClass.id == thread.class_id).one_or_none()
    grade_label = (
        school_class.grade_label or f"Grade {school_class.grade_level}"
        if school_class and school_class.grade_level is not None
        else "the class"
    )

    write_audit_log(
        db,
        actor_id=user.id,
        action="verify_doubt_answer",
        entity_type="doubt_threads",
        entity_id=thread.id,
        detail={
            "reply_id": reply.id,
            "previous_verified_reply_id": previous_reply_id,
            "class_id": thread.class_id,
            "chunks_written": chunks_written,
            "grade_level": school_class.grade_level if school_class else None,
        },
    )

    if thread.author_id != user.id:
        verifier = db.query(User).filter(User.id == user.id).one_or_none()
        dispatch_notification(
            db,
            user_id=thread.author_id,
            source_type="doubt_answer_verified",
            title=f"{_display_name(verifier)} verified an answer to your doubt",
            body=f'"{thread.title}" now has a verified answer, and it has been added to the class knowledge base.',
            priority="normal",
            source_id=thread.id,
        )

    db.commit()
    db.refresh(thread)
    return VerifyResponse(
        thread=_thread_out(db, thread, detail=True),
        chunks_written=chunks_written,
        kb_note=f"Added to the {grade_label} knowledge base — the Doubt Bot can now cite this answer.",
    )


@router.put("/{thread_id}/unverify", response_model=UnverifyResponse)
def unverify_reply(
    thread_id: int,
    user: CurrentUser = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
):
    """Retract a verified answer AND remove it from the corpus.

    The deletion is the whole reason this endpoint exists rather than being a flag
    toggle: content a teacher has withdrawn must stop being retrievable, or the bot
    keeps quoting an answer nobody stands behind.
    """
    thread = _load_thread(db, user, thread_id)
    _assert_homeroom_teacher(db, user, thread)

    if thread.verified_reply_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This thread has no verified answer")

    previous_reply_id = thread.verified_reply_id
    thread.resolved = False
    thread.verified_reply_id = None
    db.flush()

    chunks_deleted = remove_verified_doubt_answer(db, thread.id)

    write_audit_log(
        db,
        actor_id=user.id,
        action="unverify_doubt_answer",
        entity_type="doubt_threads",
        entity_id=thread.id,
        detail={
            "previous_verified_reply_id": previous_reply_id,
            "class_id": thread.class_id,
            "chunks_deleted": chunks_deleted,
        },
    )
    db.commit()
    db.refresh(thread)
    return UnverifyResponse(thread=_thread_out(db, thread, detail=True), chunks_deleted=chunks_deleted)
