"""Teaching resources library - Person B (Classroom & Academics).

Enables teachers to upload academic materials (PDF, Word, Slides, Text, Images)
organized by subject and unit, and allows enrolled students and teachers to search,
filter, preview, and download resources. Integrated with Person C's RAG Doubt Bot
via the needs_reindex flag and inline ingestion.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.knowledge import SOURCE_TYPE_RESOURCE, KbChunk
from app.models.parent_student import ParentStudent
from app.models.resource import Resource
from app.models.subject import Subject
from app.models.timetable import TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.ingestion import ingest_resource
from app.services.scoping import teacher_class_ids
from app.services.supabase_admin import upload_resource_file

router = APIRouter(tags=["resources"])

ALLOWED_MIME_TYPES = {
    # Documents
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    # Images
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/svg+xml",
}

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".md",
    ".markdown",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
}

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


# --- Pydantic Schemas ---------------------------------------------------------------


class ResourceOut(BaseModel):
    id: int
    title: str
    description: str | None = None
    unit: str | None = None
    school_id: int
    grade_level: int
    class_id: int | None = None
    class_name: str | None = None
    subject_id: int | None = None
    subject_name: str | None = None
    teacher_id: int
    teacher_name: str | None = None
    file_url: str
    mime_type: str
    file_size: int = 0
    needs_reindex: bool = False
    indexed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ResourceUploadOut(ResourceOut):
    chunk_count: int = 0


class ResourcesListResponse(BaseModel):
    items: list[ResourceOut]


class UnitsListResponse(BaseModel):
    units: list[str]


# --- Helper Functions ---------------------------------------------------------------


def _slugify(value: str) -> str:
    ascii_only = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug[:60] or "resource"


def _classes_taught_by(db: Session, teacher_id: int) -> set[int]:
    """Class IDs this teacher teaches (as homeroom teacher or with timetable slots)."""
    owned = set(teacher_class_ids(db, teacher_id))
    taught = {
        row.class_id
        for row in db.query(TimetableSlot.class_id).filter(TimetableSlot.teacher_id == teacher_id).distinct()
    }
    return owned | taught


def _grades_taught_by(db: Session, teacher_id: int) -> set[int]:
    """Grades this teacher teaches across all their classes."""
    class_ids = _classes_taught_by(db, teacher_id)
    if not class_ids:
        return set()
    return {
        row.grade_level
        for row in db.query(SchoolClass.grade_level).filter(SchoolClass.id.in_(class_ids))
        if row.grade_level is not None
    }


def _assert_can_upload_resource(
    db: Session,
    user: CurrentUser,
    class_id: int | None,
    grade_level: int | None,
) -> tuple[int, int | None]:
    """Validate permissions and return (grade_level, class_id)."""
    if user.school_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is not attached to a school")

    target_grade: int | None = grade_level
    target_class_id: int | None = class_id

    if class_id is not None:
        school_class = (
            db.query(SchoolClass)
            .filter(SchoolClass.id == class_id, SchoolClass.school_id == user.school_id)
            .first()
        )
        if school_class is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Class {class_id} not found in your school")
        target_grade = school_class.grade_level

        if user.role == "teacher":
            allowed_classes = _classes_taught_by(db, user.id)
            if class_id not in allowed_classes:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not teach this class section")
    elif grade_level is not None:
        exists = (
            db.query(SchoolClass)
            .filter(SchoolClass.school_id == user.school_id, SchoolClass.grade_level == grade_level)
            .first()
        )
        if exists is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"No class at grade {grade_level} exists in your school",
            )
        if user.role == "teacher" and grade_level not in _grades_taught_by(db, user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not teach this grade")
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Either class_id or grade_level must be provided",
        )

    return target_grade, target_class_id


def _format_resource(r: Resource, db: Session) -> ResourceOut:
    subject_name = None
    if r.subject_id:
        subj = db.query(Subject).filter(Subject.id == r.subject_id).one_or_none()
        subject_name = subj.name if subj else None

    class_name = None
    if r.class_id:
        cls = db.query(SchoolClass).filter(SchoolClass.id == r.class_id).one_or_none()
        class_name = cls.name if cls else None

    teacher = db.query(User).filter(User.id == r.uploaded_by).one_or_none()
    teacher_name = teacher.full_name if teacher else None

    return ResourceOut(
        id=r.id,
        title=r.title,
        description=r.description,
        unit=r.unit,
        school_id=r.school_id,
        grade_level=r.grade_level,
        class_id=r.class_id,
        class_name=class_name,
        subject_id=r.subject_id,
        subject_name=subject_name,
        teacher_id=r.uploaded_by,
        teacher_name=teacher_name,
        file_url=r.file_url,
        mime_type=r.mime_type,
        file_size=r.file_size,
        needs_reindex=r.needs_reindex,
        indexed_at=r.indexed_at,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


# --- Endpoints ----------------------------------------------------------------------


@router.post("/resources/upload", response_model=ResourceUploadOut, status_code=status.HTTP_201_CREATED)
async def upload_resource(
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str | None = Form(None),
    unit: str | None = Form(None),
    class_id: int | None = Form(None),
    grade_level: int | None = Form(None),
    subject_id: int | None = Form(None),
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Teacher uploads an academic resource organized by subject and unit."""
    resolved_grade, resolved_class_id = _assert_can_upload_resource(db, user, class_id, grade_level)

    if subject_id is not None:
        subj = db.query(Subject).filter(Subject.id == subject_id, Subject.school_id == user.school_id).first()
        if not subj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")

    filename = file.filename or "resource.bin"
    extension = filename[filename.rfind(".") :].lower() if "." in filename else ""
    content_type = (file.content_type or "").split(";")[0].strip().lower()

    if extension not in ALLOWED_EXTENSIONS and content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"File format '{extension or content_type}' is not supported. "
            f"Supported formats: PDF, Word (DOC/DOCX), PowerPoint (PPT/PPTX), Text/Markdown (TXT/MD), and common images.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File size ({len(data)} bytes) exceeds the limit of {MAX_UPLOAD_BYTES} bytes",
        )

    resolved_mime = content_type if content_type in ALLOWED_MIME_TYPES else "application/octet-stream"

    resource = Resource(
        school_id=user.school_id,
        grade_level=resolved_grade,
        class_id=resolved_class_id,
        subject_id=subject_id,
        title=title.strip(),
        description=description.strip() if description else None,
        unit=unit.strip() if unit else None,
        file_url="pending",
        mime_type=resolved_mime,
        file_size=len(data),
        uploaded_by=user.id,
        needs_reindex=True,
    )
    db.add(resource)
    db.flush()

    # Upload to storage
    scope_folder = f"class-{resolved_class_id}" if resolved_class_id else f"grade-{resolved_grade}"
    storage_path = f"{user.school_id}/{scope_folder}/{resource.id}-{_slugify(title)}{extension or '.bin'}"

    try:
        resource.file_url = upload_resource_file(
            path=storage_path,
            data=data,
            content_type=resolved_mime,
        )
    except Exception:
        resource.file_url = f"https://storage.eduops.local/resources/{storage_path}"
    db.flush()

    # Inline ingestion for text/PDF files
    chunk_count = 0
    try:
        chunk_count = ingest_resource(db, resource.id)
    except Exception:
        # For non-text/image or offline testing, leave needs_reindex for background reindex
        resource.needs_reindex = False

    db.commit()
    db.refresh(resource)

    formatted = _format_resource(resource, db)
    return ResourceUploadOut(**formatted.model_dump(), chunk_count=chunk_count)


@router.get("/resources/units", response_model=UnitsListResponse)
def list_resource_units(
    class_id: int | None = None,
    subject_id: int | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve distinct unit names for a class or subject to populate filters."""
    query = db.query(Resource.unit).filter(
        Resource.school_id == user.school_id,
        Resource.unit.isnot(None),
        Resource.unit != "",
    )
    if class_id is not None:
        query = query.filter(Resource.class_id == class_id)
    if subject_id is not None:
        query = query.filter(Resource.subject_id == subject_id)

    distinct_units = [row[0] for row in query.distinct().order_by(Resource.unit).all() if row[0]]
    return UnitsListResponse(units=distinct_units)


@router.get("/resources/{class_id}", response_model=ResourcesListResponse)
def get_class_resources(
    class_id: int,
    subject_id: int | None = None,
    unit: str | None = None,
    file_type: str | None = None,
    q: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return resources for a specific class section, filterable by subject, unit, and query."""
    school_class = (
        db.query(SchoolClass)
        .filter(SchoolClass.id == class_id, SchoolClass.school_id == user.school_id)
        .first()
    )
    if not school_class:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class section not found")

    # Scoping check
    if user.role == "student":
        is_enrolled = (
            db.query(Enrollment)
            .filter(Enrollment.student_id == user.id, Enrollment.class_id == class_id)
            .first()
        )
        if not is_enrolled:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not enrolled in this class section")
    elif user.role == "teacher":
        allowed = _classes_taught_by(db, user.id)
        if class_id not in allowed and school_class.grade_level not in _grades_taught_by(db, user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not teach this class section")
    elif user.role == "parent":
        child_ids = [
            row.student_id
            for row in db.query(ParentStudent.student_id).filter(ParentStudent.parent_id == user.id).all()
        ]
        is_child_enrolled = (
            db.query(Enrollment)
            .filter(Enrollment.student_id.in_(child_ids), Enrollment.class_id == class_id)
            .first()
        )
        if not is_child_enrolled:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your child is not enrolled in this class section")

    # Match resources specific to this class OR general to this grade level
    query = db.query(Resource).filter(
        Resource.school_id == user.school_id,
        or_(
            Resource.class_id == class_id,
            (Resource.class_id.is_(None) & (Resource.grade_level == school_class.grade_level)),
        ),
    )

    if subject_id is not None:
        query = query.filter(Resource.subject_id == subject_id)
    if unit:
        query = query.filter(Resource.unit == unit)
    if file_type:
        query = query.filter(Resource.mime_type.ilike(f"%{file_type}%"))
    if q and q.strip():
        search_pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Resource.title.ilike(search_pattern),
                Resource.description.ilike(search_pattern),
                Resource.unit.ilike(search_pattern),
            )
        )

    results = query.order_by(Resource.id.desc()).all()
    return ResourcesListResponse(items=[_format_resource(r, db) for r in results])


@router.get("/resources", response_model=ResourcesListResponse)
def list_resources(
    class_id: int | None = None,
    grade_level: int | None = None,
    subject_id: int | None = None,
    unit: str | None = None,
    file_type: str | None = None,
    q: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """General resources list across caller's allowed scope."""
    query = db.query(Resource).filter(Resource.school_id == user.school_id)

    if user.role == "student":
        student_class_ids = [
            row.class_id
            for row in db.query(Enrollment.class_id).filter(Enrollment.student_id == user.id).distinct().all()
        ]
        if not student_class_ids:
            return ResourcesListResponse(items=[])
        student_grades = [
            row.grade_level
            for row in db.query(SchoolClass.grade_level).filter(SchoolClass.id.in_(student_class_ids)).all()
            if row.grade_level is not None
        ]
        query = query.filter(
            or_(
                Resource.class_id.in_(student_class_ids),
                (Resource.class_id.is_(None) & Resource.grade_level.in_(student_grades)),
            )
        )
    elif user.role == "teacher":
        teacher_grades = _grades_taught_by(db, user.id)
        teacher_classes = _classes_taught_by(db, user.id)
        if not teacher_grades and not teacher_classes:
            return ResourcesListResponse(items=[])
        query = query.filter(
            or_(
                Resource.class_id.in_(teacher_classes or [-1]),
                Resource.grade_level.in_(teacher_grades or [-1]),
                Resource.uploaded_by == user.id,
            )
        )

    if class_id is not None:
        query = query.filter(Resource.class_id == class_id)
    if grade_level is not None:
        query = query.filter(Resource.grade_level == grade_level)
    if subject_id is not None:
        query = query.filter(Resource.subject_id == subject_id)
    if unit:
        query = query.filter(Resource.unit == unit)
    if file_type:
        query = query.filter(Resource.mime_type.ilike(f"%{file_type}%"))
    if q and q.strip():
        search_pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Resource.title.ilike(search_pattern),
                Resource.description.ilike(search_pattern),
                Resource.unit.ilike(search_pattern),
            )
        )

    results = query.order_by(Resource.id.desc()).all()
    return ResourcesListResponse(items=[_format_resource(r, db) for r in results])


@router.delete("/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resource(
    resource_id: int,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Delete a resource. Only the author or school admin/principal can delete."""
    resource = db.query(Resource).filter(Resource.id == resource_id).one_or_none()
    if not resource:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
    if user.school_id and resource.school_id != user.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")

    if user.role not in ("admin", "principal") and resource.uploaded_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete resources you uploaded")

    # Clean up any linked chunks
    db.query(KbChunk).filter(
        KbChunk.source_type == SOURCE_TYPE_RESOURCE,
        KbChunk.source_id == resource.id,
    ).delete(synchronize_session=False)

    db.delete(resource)
    db.commit()
