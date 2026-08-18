"""Classroom Stream router - Person B (Classroom & Academics).

Enables teachers to publish stream posts (notes, announcements, materials)
with attachments, and allows enrolled students and teachers to view the
chronological classroom feed.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
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
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.scoping import deny_parent
from app.services.notify import dispatch_bulk

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
    file_type: str
    file_size: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PostCreateRequest(BaseModel):
    post_type: str  # note, announcement, material
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    attachments: list[AttachmentIn] = Field(default_factory=list)


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

    for att in body.attachments:
        attachment_row = PostAttachment(
            post_id=post.id,
            file_name=att.file_name,
            file_url=att.file_url,
            file_type=att.file_type,
            file_size=att.file_size,
        )
        db.add(attachment_row)

    # Person C Announcement Integration
    if body.post_type == "announcement":
        enrolled_student_ids = _get_enrolled_student_ids(db, classroom.class_id, classroom.subject_id)
        if enrolled_student_ids:
            subject = db.query(Subject).filter(Subject.id == classroom.subject_id).one_or_none()
            subj_title = subject.name if subject else "Class"
            # N-3: students only, previously. A class announcement that parents never see
            # is the announcement most worth sending - "bring a leaf on Thursday" is
            # addressed to whoever packs the bag. Linked guardians are included, and
            # dispatch_bulk de-duplicates a parent with two children in the class.
            parent_ids = [
                row.parent_id
                for row in db.query(ParentStudent.parent_id)
                .filter(ParentStudent.student_id.in_(enrolled_student_ids))
                .distinct()
            ]
            dispatch_bulk(
                db,
                user_ids=[*enrolled_student_ids, *parent_ids],
                source_type="announcement",
                title=f"[{subj_title}] {body.title}",
                body=body.content[:250],
                priority="important",
                source_id=post.id,
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

    # Try storing to Supabase Storage if configured, else generate local reference
    file_url = f"/attachments/classroom-{classroom_id}/{uuid.uuid4()}-{filename}"
    try:
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if supabase_url and supabase_key and "your-" not in supabase_url:
            from app.services.supabase_admin import upload_resource_file

            storage_path = f"classroom/{classroom_id}/{uuid.uuid4()}-{filename}"
            upload_resource_file(path=storage_path, data=data, content_type=content_type)
            file_url = f"{supabase_url}/storage/v1/object/public/resources/{storage_path}"
    except Exception:
        # Fall back to descriptive link
        file_url = f"https://storage.eduops.local/classroom/{classroom_id}/{uuid.uuid4()}/{filename}"

    return AttachmentUploadOut(
        file_name=filename,
        file_url=file_url,
        file_type=content_type,
        file_size=len(data),
    )
