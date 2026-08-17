"""Teaching resources - upload (with inline ingestion) and role-scoped listing.

The upload handler copies the SHAPE of routers/documents.py's multipart endpoint
(UploadFile + Form fields, validate, then process) and none of its behaviour: that one
sets `file_url` to a fabricated descriptive string and discards the bytes after OCR.
Here the bytes are genuinely persisted to Supabase Storage, which is what lets
POST /bots/reindex re-chunk a resource later without asking for a re-upload.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.resource import Resource
from app.models.timetable import TimetableSlot
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.ingestion import ingest_resource
from app.services.scoping import teacher_class_ids
from app.services.supabase_admin import upload_resource_file

router = APIRouter(tags=["resources"])

ALLOWED_MIME_TYPES = {"text/plain", "text/markdown", "text/x-markdown", "application/pdf"}
ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf"}
"""Text, markdown and PDF. PDF extraction is TEXT-LAYER ONLY (pypdf, see
services/ingestion.py::extract_text) - a scanned PDF whose pages are images of text
extracts to nothing and is rejected with 422 rather than stored as an empty resource.
Anything else is still refused: a corpus quietly full of binary garbage is worse than
a corpus that refused the upload."""

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
"""Raised from 2 MB with PDF support - a scanned-image textbook chapter runs to
several MB where a markdown file never would."""


class ResourceOut(BaseModel):
    id: int
    title: str
    school_id: int
    grade_level: int
    subject_id: int | None
    file_url: str
    mime_type: str
    indexed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResourceUploadOut(ResourceOut):
    chunk_count: int
    """How many kb_chunks this upload produced. Returned because ingestion is inline
    and synchronous - the number is truthful at response time, not a promise."""


class ResourcesListResponse(BaseModel):
    items: list[ResourceOut]


def _slugify(value: str) -> str:
    ascii_only = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug[:60] or "resource"


def _grades_taught_by(db: Session, teacher_id: int) -> set[int]:
    """Grades this teacher actually teaches - homeroom classes plus any class they hold
    timetable slots for. A subject teacher needs to upload for a grade even where they
    are not the class teacher of any of its sections."""
    owned = set(teacher_class_ids(db, teacher_id))
    taught = {
        row.class_id
        for row in db.query(TimetableSlot.class_id).filter(TimetableSlot.teacher_id == teacher_id).distinct()
    }
    class_ids = owned | taught
    if not class_ids:
        return set()
    return {
        row.grade_level
        for row in db.query(SchoolClass.grade_level).filter(SchoolClass.id.in_(class_ids))
        if row.grade_level is not None
    }


def _assert_can_write_grade(db: Session, user: CurrentUser, grade_level: int) -> None:
    """Upload scoping, now per grade rather than per class.

    A teacher may upload for a grade they teach; an admin/principal for any grade in
    their own school. The school check is not optional - without it an admin could
    write into another tenant's grade, and since grade_level is a bare integer there is
    no FK to catch it.
    """
    if user.school_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is not attached to a school")

    exists = (
        db.query(SchoolClass)
        .filter(SchoolClass.school_id == user.school_id, SchoolClass.grade_level == grade_level)
        .first()
    )
    if exists is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"No class at grade {grade_level} exists in your school, so nothing could retrieve this resource",
        )

    if user.role == "teacher" and grade_level not in _grades_taught_by(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not teach this grade")


def _readable_grades(db: Session, user: CurrentUser) -> set[int] | None:
    """Grades this caller may read resources for. None means "every grade in their own
    school" (admin/principal), which the caller turns into a school_id-only filter."""
    if user.role in ("admin", "principal"):
        return None
    if user.role == "teacher":
        return _grades_taught_by(db, user.id)
    if user.role == "student":
        class_ids = [
            row.class_id
            for row in db.query(Enrollment.class_id).filter(
                Enrollment.student_id == user.id, Enrollment.is_primary.is_(True)
            )
        ]
        if not class_ids:
            return set()
        return {
            row.grade_level
            for row in db.query(SchoolClass.grade_level).filter(SchoolClass.id.in_(class_ids))
            if row.grade_level is not None
        }
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view resources")


@router.post("/resources/upload", response_model=ResourceUploadOut, status_code=status.HTTP_201_CREATED)
async def upload_resource(
    file: UploadFile = File(...),
    title: str = Form(...),
    grade_level: int = Form(...),
    subject_id: int | None = Form(None),
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    _assert_can_write_grade(db, user, grade_level)

    filename = file.filename or "upload.txt"
    extension = filename[filename.rfind(".") :].lower() if "." in filename else ""
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if extension not in ALLOWED_EXTENSIONS and content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Only {', '.join(sorted(ALLOWED_EXTENSIONS))} files are supported "
            f"(got {filename!r}, content-type {content_type or 'unknown'!r}).",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is {len(data)} bytes; the limit is {MAX_UPLOAD_BYTES}",
        )

    resolved_mime = content_type if content_type in ALLOWED_MIME_TYPES else "text/markdown"

    resource = Resource(
        school_id=user.school_id,
        grade_level=grade_level,
        subject_id=subject_id,
        title=title,
        file_url="pending",
        mime_type=resolved_mime,
        uploaded_by=user.id,
    )
    db.add(resource)
    db.flush()

    resource.file_url = upload_resource_file(
        path=f"{user.school_id}/grade-{grade_level}/{resource.id}-{_slugify(title)}{extension or '.md'}",
        data=data,
        content_type=resolved_mime,
    )
    db.flush()

    # Inline ingestion, following POST /admin/fees/schedules' synchronous-trigger
    # precedent. Inside the same transaction: if embedding fails the resource row is
    # rolled back too, so we never end up with a resource that exists but can never be
    # retrieved. (The stored object is orphaned in that case, which is harmless - the
    # next upload to the same id overwrites it.)
    chunk_count = ingest_resource(db, resource.id)
    if chunk_count == 0:
        # No text came out. For a PDF this means a scanned/image-only document, which
        # pypdf cannot read (it does not OCR). Fail loudly rather than committing a
        # resource that exists, claims to be indexed, and can never be retrieved.
        db.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "No readable text could be extracted from this file. If it is a scanned PDF, "
            "its pages are images and text extraction cannot read them - upload a text-layer "
            "PDF, or convert it to .md/.txt first.",
        )
    db.commit()
    db.refresh(resource)

    return ResourceUploadOut(
        id=resource.id, title=resource.title, school_id=resource.school_id,
        grade_level=resource.grade_level, subject_id=resource.subject_id,
        file_url=resource.file_url, mime_type=resource.mime_type, indexed_at=resource.indexed_at,
        created_at=resource.created_at, chunk_count=chunk_count,
    )


@router.get("/resources", response_model=ResourcesListResponse)
def list_resources(
    grade_level: int | None = None,
    subject_id: int | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed = _readable_grades(db, user)
    # school_id is applied for EVERY role, not just admin/principal - grade_level is a
    # bare integer, so without it a grade filter would span tenants.
    query = db.query(Resource).filter(Resource.school_id == user.school_id)

    if allowed is not None:
        query = query.filter(Resource.grade_level.in_(allowed or [-1]))

    if grade_level is not None:
        # A grade outside the caller's scope is a 403, never a silently empty list -
        # an empty list would read as "no resources exist" rather than "not yours".
        if allowed is not None and grade_level not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view this grade's resources")
        query = query.filter(Resource.grade_level == grade_level)
    if subject_id is not None:
        query = query.filter(Resource.subject_id == subject_id)

    return ResourcesListResponse(
        items=[ResourceOut.model_validate(r) for r in query.order_by(Resource.id.desc()).all()]
    )
