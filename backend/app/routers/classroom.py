"""Classroom Stream router - Person B (Classroom & Academics).

Enables teachers to publish stream posts (notes, announcements, materials)
with attachments, and allows enrolled students and teachers to view the
chronological classroom feed.
"""

from __future__ import annotations

import mimetypes
import os
import uuid
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.classroom import Classroom, PostAttachment, StreamPost, POST_TYPES
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.subject import Subject
from app.models.timetable import TimetableSlot
from app.models.user import User
from app.services.announcements import publish_announcement
from app.services.classroom_materials import index_post_attachments
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.scoping import deny_parent
from app.services.supabase_admin import download_resource_file

router = APIRouter(tags=["classroom-stream"])

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB


# --- Pydantic Schemas ---------------------------------------------------------------


class AttachmentIn(BaseModel):
    file_name: str
    file_url: str
    file_type: str = "application/octet-stream"
    file_size: int = Field(ge=0)


class AttachmentOut(BaseModel):
    id: int
    post_id: int
    file_name: str
    file_url: str
    """Object PATH inside the private `resources` bucket, NOT a link. Read the bytes via
    GET /classroom/attachments/{id}/download - see api-contract.md's "Uploaded files:
    NEVER return a Supabase public URL"."""
    file_type: str
    file_size: int
    resource_id: int | None = None
    """The library `resources` row this file was indexed as, so the UI can show that the
    Doubt Bot can answer from it. NULL for images (no extractable text) and for
    attachments uploaded before classroom posts fed the knowledge base."""
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PostCreateRequest(BaseModel):
    post_type: str  # note, announcement, material
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    attachments: list[AttachmentIn] = Field(default_factory=list)
    share_with_grade: bool = True
    """Whether this post's attachments are also filed in the resource library for the whole
    GRADE (default) or pinned to just this class section.

    Grade-wide is the default because a worksheet for Grade 3-B Math is nearly always just
    as relevant to Grade 3-A Math, and because grade is the unit the bots' retrieval scopes
    by. Affects only the library/RAG copy - the stream post itself is always visible to
    this classroom alone, whatever this is set to."""


class PostAuthorOut(BaseModel):
    id: int
    full_name: str | None
    email: str | None
    role: str | None = None

    model_config = ConfigDict(from_attributes=True)


class StreamPostOut(BaseModel):
    id: int
    classroom_id: int
    author_id: int
    author: PostAuthorOut | None
    post_type: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    attachments: list[AttachmentOut]
    indexing_warnings: list[str] = []
    """Per-attachment notes from adding the files to the bots' knowledge base. Empty on the
    happy path and on reads.

    Present so a failure to index is REPORTED rather than swallowed: the post itself
    succeeded (deliberately - see services/classroom_materials.py on why an unparseable PDF
    must not cost a teacher their post), so a 201 is correct, but the teacher still needs to
    know the Doubt Bot cannot read that file yet."""

    model_config = ConfigDict(from_attributes=True)


class ClassroomCreateRequest(BaseModel):
    class_id: int
    subject_id: int
    teacher_id: int | None = None  # defaults to current teacher


class ClassroomOut(BaseModel):
    id: int
    school_id: int
    class_id: int
    class_name: str
    subject_id: int
    subject_name: str | None = None
    teacher_id: int
    teacher_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StreamResponse(BaseModel):
    classroom: ClassroomOut
    items: list[StreamPostOut]


class AttachmentUploadOut(BaseModel):
    file_name: str
    file_url: str
    file_type: str
    file_size: int


# --- Helper Functions ---------------------------------------------------------------


def _get_enrolled_student_ids(db: Session, class_id: int, subject_id: int | None = None) -> list[int]:
    """Return all student IDs enrolled in the given class section."""
    query = db.query(Enrollment.student_id).filter(Enrollment.class_id == class_id)
    if subject_id is not None:
        # N-2: the OR previously read `is_primary.is_(True)` with no subject constraint,
        # so ANY primary enrollment in the class matched - an elective classroom notified
        # the entire homeroom rather than the students taking that elective. Primary
        # enrollments legitimately count (a homeroom student takes the core subject), but
        # only when their enrollment carries no subject of its own.
        query = query.filter(
            (Enrollment.subject_id == subject_id)
            | ((Enrollment.subject_id.is_(None)) & (Enrollment.is_primary.is_(True)))
        )
    return [row.student_id for row in query.distinct().all()]


def _assert_can_view_classroom(db: Session, user: CurrentUser, classroom: Classroom) -> None:
    """Verify that caller has permission to view this classroom's stream."""
    if user.school_id and classroom.school_id != user.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Classroom not found")

    if user.role in ("admin", "principal"):
        return

    if user.role == "teacher":
        # Teacher of this classroom or homeroom class teacher
        if classroom.teacher_id == user.id:
            return
        school_class = db.query(SchoolClass).filter(SchoolClass.id == classroom.class_id).one_or_none()
        if school_class and school_class.class_teacher_id == user.id:
            return
        # Or teacher has active timetable slots for this class + subject
        has_slot = (
            db.query(TimetableSlot)
            .filter(
                TimetableSlot.teacher_id == user.id,
                TimetableSlot.class_id == classroom.class_id,
                TimetableSlot.is_active.is_(True),
            )
            .first()
        )
        if has_slot:
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not an authorized teacher for this classroom")

    if user.role == "student":
        is_enrolled = (
            db.query(Enrollment)
            .filter(Enrollment.student_id == user.id, Enrollment.class_id == classroom.class_id)
            .first()
        )
        if not is_enrolled:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not enrolled in this classroom")
        return

    if user.role == "parent":
        # Check if parent is linked to any student enrolled in this class
        linked_student_ids = [
            row.student_id
            for row in db.query(ParentStudent.student_id).filter(ParentStudent.parent_id == user.id).all()
        ]
        if not linked_student_ids:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No linked students found")
        is_child_enrolled = (
            db.query(Enrollment)
            .filter(Enrollment.student_id.in_(linked_student_ids), Enrollment.class_id == classroom.class_id)
            .first()
        )
        if not is_child_enrolled:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your child is not enrolled in this classroom")
        return

    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view classroom")


def _assert_can_post_to_classroom(db: Session, user: CurrentUser, classroom: Classroom) -> None:
    """Verify that caller has permission to post in this classroom."""
    if user.school_id and classroom.school_id != user.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Classroom not found")

    if user.role in ("admin", "principal"):
        return

    if user.role == "teacher":
        if classroom.teacher_id == user.id:
            return
        school_class = db.query(SchoolClass).filter(SchoolClass.id == classroom.class_id).one_or_none()
        if school_class and school_class.class_teacher_id == user.id:
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the assigned teacher can post to this classroom")

    raise HTTPException(status.HTTP_403_FORBIDDEN, "Students and parents cannot create classroom posts")


def _format_classroom(classroom: Classroom, db: Session) -> ClassroomOut:
    subject = db.query(Subject).filter(Subject.id == classroom.subject_id).one_or_none()
    teacher = db.query(User).filter(User.id == classroom.teacher_id).one_or_none()
    return ClassroomOut(
        id=classroom.id,
        school_id=classroom.school_id,
        class_id=classroom.class_id,
        class_name=classroom.class_name,
        subject_id=classroom.subject_id,
        subject_name=subject.name if subject else None,
        teacher_id=classroom.teacher_id,
        teacher_name=teacher.full_name if teacher else None,
        created_at=classroom.created_at,
        updated_at=classroom.updated_at,
    )


# --- Endpoints ----------------------------------------------------------------------


@router.get("/classroom/my-classrooms", response_model=list[ClassroomOut])
def get_my_classrooms(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List classrooms accessible to the current user based on their role."""
    deny_parent(user, feature="the classroom stream")
    query = db.query(Classroom)
    if user.school_id:
        query = query.filter(Classroom.school_id == user.school_id)

    if user.role in ("admin", "principal"):
        classrooms = query.order_by(Classroom.class_name, Classroom.id).all()
    elif user.role == "teacher":
        # Teacher's own classrooms or where they teach
        classrooms = query.filter(Classroom.teacher_id == user.id).order_by(Classroom.class_name).all()
    elif user.role == "student":
        student_class_ids = [
            row.class_id
            for row in db.query(Enrollment.class_id).filter(Enrollment.student_id == user.id).distinct().all()
        ]
        if not student_class_ids:
            return []
        classrooms = query.filter(Classroom.class_id.in_(student_class_ids)).order_by(Classroom.class_name).all()
    elif user.role == "parent":
        child_ids = [
            row.student_id
            for row in db.query(ParentStudent.student_id).filter(ParentStudent.parent_id == user.id).all()
        ]
        if not child_ids:
            return []
        parent_class_ids = [
            row.class_id
            for row in db.query(Enrollment.class_id).filter(Enrollment.student_id.in_(child_ids)).distinct().all()
        ]
        if not parent_class_ids:
            return []
        classrooms = query.filter(Classroom.class_id.in_(parent_class_ids)).order_by(Classroom.class_name).all()
    else:
        return []

    return [_format_classroom(c, db) for c in classrooms]


@router.post("/classroom", response_model=ClassroomOut, status_code=status.HTTP_201_CREATED)
def create_classroom(
    body: ClassroomCreateRequest,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Create or retrieve a classroom for a class and subject."""
    school_class = db.query(SchoolClass).filter(SchoolClass.id == body.class_id).one_or_none()
    if not school_class:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    if user.school_id and school_class.school_id != user.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")

    subject = db.query(Subject).filter(Subject.id == body.subject_id).one_or_none()
    if not subject:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")

    teacher_id = body.teacher_id or user.id
    teacher = db.query(User).filter(User.id == teacher_id).one_or_none()
    if not teacher:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")

    # Check existing classroom
    existing = (
        db.query(Classroom)
        .filter(
            Classroom.class_id == body.class_id,
            Classroom.subject_id == body.subject_id,
            Classroom.teacher_id == teacher_id,
        )
        .first()
    )
    if existing:
        return _format_classroom(existing, db)

    classroom = Classroom(
        school_id=school_class.school_id,
        class_id=body.class_id,
        class_name=school_class.name,
        subject_id=body.subject_id,
        teacher_id=teacher_id,
    )
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return _format_classroom(classroom, db)


@router.get("/classroom/{classroom_id}", response_model=ClassroomOut)
def get_classroom(
    classroom_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get single classroom info."""
    deny_parent(user, feature="the classroom stream")
    classroom = db.query(Classroom).filter(Classroom.id == classroom_id).one_or_none()
    if not classroom:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Classroom not found")
    _assert_can_view_classroom(db, user, classroom)
    return _format_classroom(classroom, db)


@router.post("/classroom/{classroom_id}/post", response_model=StreamPostOut, status_code=status.HTTP_201_CREATED)
def create_stream_post(
    classroom_id: int,
    body: PostCreateRequest,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Create a stream post (note, announcement, material) with optional attachments."""
    if body.post_type not in POST_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Invalid post_type '{body.post_type}'. Must be one of: {', '.join(POST_TYPES)}",
        )

    classroom = db.query(Classroom).filter(Classroom.id == classroom_id).one_or_none()
    if not classroom:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Classroom not found")

    _assert_can_post_to_classroom(db, user, classroom)

    post = StreamPost(
        classroom_id=classroom_id,
        author_id=user.id,
        post_type=body.post_type,
        title=body.title.strip(),
        content=body.content.strip(),
    )
    db.add(post)
    db.flush()

    attachment_rows: list[PostAttachment] = []
    for att in body.attachments:
        attachment_row = PostAttachment(
            post_id=post.id,
            file_name=att.file_name,
            file_url=att.file_url,
            file_type=att.file_type,
            file_size=att.file_size,
        )
        db.add(attachment_row)
        attachment_rows.append(attachment_row)

    # EVERY ATTACHED FILE ALSO BECOMES A LIBRARY RESOURCE, INDEXED FOR THE BOTS.
    #
    # This step did not exist. Posting a file here wrote bytes to storage and nothing else
    # - no `resources` row, no ingestion - so the Doubt Bot could never answer from
    # anything a teacher shared with their own class. `POST /resources/upload` was the only
    # path into the RAG corpus, which meant uploading the same PDF twice, in two different
    # screens, with nothing in either saying so. See services/classroom_materials.py.
    #
    # Returns warnings rather than raising: a PDF with no text layer must not cost the
    # teacher their post. Those resources keep `indexed_at = NULL` and the periodic reindex
    # job retries them.
    indexing_warnings: list[str] = []
    if attachment_rows:
        db.flush()  # attachment ids, before they are linked to resources
        indexing_warnings = index_post_attachments(
            db,
            classroom=classroom,
            post_title=post.title,
            attachments=attachment_rows,
            uploader_id=user.id,
            share_with_grade=body.share_with_grade,
        )

    # A stream post of type "announcement" becomes a REAL announcement row.
    #
    # It used to call dispatch_bulk directly with source_type="announcement" and
    # source_id=post.id, so stream-post ids shared an id namespace with announcement ids
    # and a notification could deep-link to the wrong record. It also meant a class
    # announcement never appeared in the announcement feed - only inside the stream of the
    # one classroom, which is the place a parent does not look. publish_announcement fixes
    # both: source_id is an Announcement.id, and the feed picks it up.
    #
    # Audience is still computed HERE, not by resolve_audience. A class-scoped
    # announcement reaches the whole homeroom, but an elective classroom must reach only
    # the students taking that elective (N-2) - so the narrowed list is passed through as
    # audience_override, with linked guardians added (N-3). Both earlier fixes survive.
    if post.post_type == "announcement":
        subject = db.query(Subject).filter(Subject.id == classroom.subject_id).one_or_none()
        subj_title = subject.name if subject else "Class"
        student_ids = _get_enrolled_student_ids(db, classroom.class_id, classroom.subject_id)
        parent_ids = [
            row.parent_id
            for row in db.query(ParentStudent.parent_id)
            .filter(ParentStudent.student_id.in_(student_ids))
            .distinct()
        ] if student_ids else []
        publish_announcement(
            db,
            author_id=user.id,
            school_id=classroom.school_id,
            scope_type="class",
            scope_class_id=classroom.class_id,
            title=f"[{subj_title}] {body.title.strip()}",
            body=body.content.strip(),
            category="academic",
            priority="important",
            # audit_logs.action is varchar(30) - a longer verb raises
            # StringDataRightTruncation at commit, not at import.
            audit_action="announce_from_stream",
            audience_override=[*student_ids, *parent_ids],
        )

    db.commit()
    db.refresh(post)

    author_user = db.query(User).filter(User.id == user.id).one_or_none()
    author_out = (
        PostAuthorOut(
            id=author_user.id,
            full_name=author_user.full_name or user.email,
            email=author_user.email,
            role=user.role,
        )
        if author_user
        else None
    )

    return StreamPostOut(
        id=post.id,
        classroom_id=post.classroom_id,
        author_id=post.author_id,
        author=author_out,
        post_type=post.post_type,
        title=post.title,
        content=post.content,
        created_at=post.created_at,
        updated_at=post.updated_at,
        attachments=[AttachmentOut.model_validate(a) for a in post.attachments],
        indexing_warnings=indexing_warnings,
    )


@router.get("/classroom/{classroom_id}/stream", response_model=StreamResponse)
def get_classroom_stream(
    classroom_id: int,
    post_type: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve chronological classroom stream posts, newest first."""
    deny_parent(user, feature="the classroom stream")
    classroom = db.query(Classroom).filter(Classroom.id == classroom_id).one_or_none()
    if not classroom:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Classroom not found")

    _assert_can_view_classroom(db, user, classroom)

    query = (
        db.query(StreamPost)
        .filter(StreamPost.classroom_id == classroom_id)
        .order_by(StreamPost.created_at.desc(), StreamPost.id.desc())
    )
    if post_type:
        query = query.filter(StreamPost.post_type == post_type)

    posts = query.all()

    items: list[StreamPostOut] = []
    for p in posts:
        author = db.query(User).filter(User.id == p.author_id).one_or_none()
        author_out = (
            PostAuthorOut(
                id=author.id,
                full_name=author.full_name or author.email,
                email=author.email,
                role=author.role.name if author and author.role else None,
            )
            if author
            else None
        )
        items.append(
            StreamPostOut(
                id=p.id,
                classroom_id=p.classroom_id,
                author_id=p.author_id,
                author=author_out,
                post_type=p.post_type,
                title=p.title,
                content=p.content,
                created_at=p.created_at,
                updated_at=p.updated_at,
                attachments=[AttachmentOut.model_validate(a) for a in p.attachments],
            )
        )

    return StreamResponse(
        classroom=_format_classroom(classroom, db),
        items=items,
    )


@router.delete("/classroom/{classroom_id}/post/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stream_post(
    classroom_id: int,
    post_id: int,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Delete a stream post. Only the post author or school admin/principal can delete."""
    post = (
        db.query(StreamPost)
        .filter(StreamPost.id == post_id, StreamPost.classroom_id == classroom_id)
        .one_or_none()
    )
    if not post:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")

    if user.role not in ("admin", "principal") and post.author_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete your own posts")

    db.delete(post)
    db.commit()


@router.post("/classroom/{classroom_id}/upload", response_model=AttachmentUploadOut)
async def upload_classroom_attachment(
    classroom_id: int,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Upload a file attachment for a classroom post."""
    classroom = db.query(Classroom).filter(Classroom.id == classroom_id).one_or_none()
    if not classroom:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Classroom not found")
    _assert_can_post_to_classroom(db, user, classroom)

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File size ({len(data)} bytes) exceeds limit of {MAX_ATTACHMENT_BYTES} bytes",
        )

    filename = file.filename or "attachment"
    content_type = file.content_type or "application/octet-stream"

    # `file_url` is an object PATH inside the private `resources` bucket, not a URL.
    # Read it back through GET /classroom/attachments/{id}/download.
    #
    # THIS USED TO RETURN A PUBLIC URL AND EVERY ATTACHMENT 404ed. The old code uploaded
    # into `resources` - created with `public: False` (see supabase_admin.RESOURCES_BUCKET)
    # - and then handed the browser
    #     {SUPABASE_URL}/storage/v1/object/public/resources/{path}
    # Supabase answers the /public/ route for a private bucket with
    # `{"statusCode":"404","error":"Bucket not found","code":"NoSuchBucket"}`, so the link
    # was dead the moment it was created, however well the upload itself went. Making the
    # bucket public would "fix" the link by making every object URL-guessable and routing
    # around this router's own view scoping - the exact tradeoff that bucket's docstring
    # rejects. So: keep the bucket private, store the path, serve it through a scoped
    # route. Same shape as fee payment proofs (routers/fees.py::get_payment_request_proof).
    #
    # AND IT NO LONGER FAKES SUCCESS. `except Exception` swallowed every storage failure
    # and substituted an invented `https://storage.eduops.local/...` link, so a failed
    # upload returned 200 with a URL resolving to nothing - the post was created carrying a
    # permanently broken attachment and nothing anywhere recorded that the write had
    # failed. An upload that did not store the bytes is an error.
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key or "your-" in supabase_url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "File storage is not configured on this server - set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY to upload attachments.",
        )

    from app.services.supabase_admin import upload_resource_file

    storage_path = f"classroom/{classroom_id}/{uuid.uuid4()}-{filename}"
    # Raises 502 on failure rather than returning a link to nothing.
    upload_resource_file(path=storage_path, data=data, content_type=content_type)

    return AttachmentUploadOut(
        file_name=filename,
        file_url=storage_path,
        file_type=content_type,
        file_size=len(data),
    )


@router.get("/classroom/attachments/{attachment_id}/download")
def download_classroom_attachment(
    attachment_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream a post attachment back, scoped to who may view its classroom.

    Exists because PostAttachment.file_url is a path into a PRIVATE bucket - there is
    deliberately no public URL for the UI to link at, so the request has to carry the
    caller's bearer token and be checked here. The frontend fetches this as a blob
    (api/client.ts::apiGetBlob, same as fee payment proofs).

    Attachments uploaded BEFORE this route existed hold a full `https://...` URL rather
    than a path - those objects were never publicly readable and some were never stored
    at all (see the upload handler's note on the invented eduops.local fallback), so they
    are reported as gone instead of being passed to the storage client, which would fail
    with a confusing 502.
    """
    attachment = (
        db.query(PostAttachment).filter(PostAttachment.id == attachment_id).one_or_none()
    )
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")

    post = db.query(StreamPost).filter(StreamPost.id == attachment.post_id).one_or_none()
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    classroom = db.query(Classroom).filter(Classroom.id == post.classroom_id).one_or_none()
    if classroom is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")

    # Whoever may read the stream may read its attachments - no separate rule, so the
    # two can never drift apart.
    _assert_can_view_classroom(db, user, classroom)

    if "://" in attachment.file_url:
        raise HTTPException(
            status.HTTP_410_GONE,
            "This attachment was uploaded before file storage was working and its "
            "contents were never stored. Please re-upload it.",
        )

    data = download_resource_file(attachment.file_url)
    media_type = attachment.file_type or mimetypes.guess_type(attachment.file_url)[0] or "application/octet-stream"
    return Response(
        content=data,
        media_type=media_type,
        headers={
            # filename* (RFC 5987) so non-ASCII names survive; `inline` lets a PDF open
            # in the browser's viewer rather than forcing a save.
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(attachment.file_name)}",
        },
    )
