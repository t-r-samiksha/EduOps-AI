"""Assignments and Submissions router - Person B (Classroom & Academics).

Implements teacher assignment creation, student submissions with automatic
on-time/late/missing detection, teacher grading workflow with feedback,
and Person C notification dispatch.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.assignment import Assignment, AssignmentSubmission, SUBMISSION_STATUSES
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.subject import Subject
from app.models.timetable import TimetableSlot
from app.models.user import User
from app.services.assignment_service import (
    get_assignment_stats,
    get_enrolled_student_ids,
)
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.notify import dispatch_bulk, dispatch_notification
from app.services.scoping import teacher_class_ids

router = APIRouter(tags=["assignments"])

MAX_ASSIGNMENT_FILE_BYTES = 25 * 1024 * 1024  # 25 MB


# --- Pydantic Schemas ---------------------------------------------------------------


class SubmissionOut(BaseModel):
    id: int
    submission_id: int | None = None
    assignment_id: int
    student_id: int
    student_name: str | None = None
    student_email: str | None = None
    file_url: str | None = None
    file_name: str | None = None
    file_size: int = 0
    grade: float | None = None
    feedback: str | None = None
    status: str  # submitted, late, missing, graded
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssignmentStatsOut(BaseModel):
    enrolled_count: int
    submitted_count: int
    late_count: int
    missing_count: int
    graded_count: int
    average_grade: float | None = None


class AssignmentOut(BaseModel):
    id: int
    school_id: int
    class_id: int
    class_name: str | None = None
    subject_id: int | None = None
    subject_name: str | None = None
    teacher_id: int
    teacher_name: str | None = None
    title: str
    description: str | None = None
    deadline: datetime
    max_marks: float
    attachment_url: str | None = None
    attachment_name: str | None = None
    created_at: datetime
    updated_at: datetime
    stats: AssignmentStatsOut | None = None
    my_submission: SubmissionOut | None = None

    model_config = ConfigDict(from_attributes=True)


class AssignmentCreateRequest(BaseModel):
    class_id: int
    subject_id: int | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    deadline: datetime
    max_marks: float = Field(default=100.0, gt=0)
    attachment_url: str | None = None
    attachment_name: str | None = None


class SubmitAssignmentRequest(BaseModel):
    file_url: str = Field(min_length=1)
    file_name: str | None = None
    file_size: int = Field(default=0, ge=0)


class GradeSubmissionRequest(BaseModel):
    grade: float = Field(ge=0)
    feedback: str | None = None


class UploadFileOut(BaseModel):
    file_name: str
    file_url: str
    file_type: str
    file_size: int


# --- Helper Functions ---------------------------------------------------------------


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _classes_taught_by(db: Session, teacher_id: int) -> set[int]:
    owned = set(teacher_class_ids(db, teacher_id))
    taught = {
        row.class_id
        for row in db.query(TimetableSlot.class_id).filter(TimetableSlot.teacher_id == teacher_id).distinct()
    }
    return owned | taught


def _assert_can_manage_class_assignment(db: Session, user: CurrentUser, class_id: int) -> SchoolClass:
    if user.school_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is not attached to a school")

    school_class = (
        db.query(SchoolClass)
        .filter(SchoolClass.id == class_id, SchoolClass.school_id == user.school_id)
        .first()
    )
    if not school_class:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class section not found")

    if user.role in ("admin", "principal", "teacher"):
        return school_class

    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to manage assignments")


def _format_submission(sub: AssignmentSubmission, db: Session) -> SubmissionOut:
    student = db.query(User).filter(User.id == sub.student_id).one_or_none()
    return SubmissionOut(
        id=sub.id,
        submission_id=sub.id,
        assignment_id=sub.assignment_id,
        student_id=sub.student_id,
        student_name=student.full_name if student else None,
        student_email=student.email if student else None,
        file_url=sub.file_url,
        file_name=sub.file_name,
        file_size=sub.file_size,
        grade=sub.grade,
        feedback=sub.feedback,
        status=sub.status,
        submitted_at=sub.submitted_at,
        graded_at=sub.graded_at,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
    )


def _format_assignment(a: Assignment, user: CurrentUser, db: Session) -> AssignmentOut:
    subj = db.query(Subject).filter(Subject.id == a.subject_id).one_or_none() if a.subject_id else None
    cls = db.query(SchoolClass).filter(SchoolClass.id == a.class_id).one_or_none()
    teacher = db.query(User).filter(User.id == a.teacher_id).one_or_none()

    stats_out = None
    my_sub_out = None

    if user.role in ("teacher", "admin", "principal"):
        stats = get_assignment_stats(db, a)
        stats_out = AssignmentStatsOut(**stats)
    elif user.role == "student":
        sub = (
            db.query(AssignmentSubmission)
            .filter(AssignmentSubmission.assignment_id == a.id, AssignmentSubmission.student_id == user.id)
            .first()
        )
        if sub:
            my_sub_out = _format_submission(sub, db)
        else:
            # Check if past deadline
            now = datetime.now(timezone.utc)
            status_calc = "missing" if _to_utc(a.deadline) <= now else "pending"
            my_sub_out = SubmissionOut(
                id=0,
                assignment_id=a.id,
                student_id=user.id,
                student_name=user.email,
                status=status_calc,
                created_at=a.created_at,
                updated_at=a.created_at,
            )

    return AssignmentOut(
        id=a.id,
        school_id=a.school_id,
        class_id=a.class_id,
        class_name=cls.name if cls else None,
        subject_id=a.subject_id,
        subject_name=subj.name if subj else None,
        teacher_id=a.teacher_id,
        teacher_name=teacher.full_name if teacher else None,
        title=a.title,
        description=a.description,
        deadline=a.deadline,
        max_marks=a.max_marks,
        attachment_url=a.attachment_url,
        attachment_name=a.attachment_name,
        created_at=a.created_at,
        updated_at=a.updated_at,
        stats=stats_out,
        my_submission=my_sub_out,
    )


# --- Endpoints ----------------------------------------------------------------------


@router.post("/assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
def create_assignment(
    body: AssignmentCreateRequest,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Teacher creates an academic assignment for a class and subject."""
    school_class = _assert_can_manage_class_assignment(db, user, body.class_id)

    if body.subject_id is not None:
        subj = (
            db.query(Subject)
            .filter(Subject.id == body.subject_id, Subject.school_id == user.school_id)
            .first()
        )
        if not subj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")

    assignment = Assignment(
        school_id=user.school_id,
        class_id=body.class_id,
        subject_id=body.subject_id,
        teacher_id=user.id,
        title=body.title.strip(),
        description=body.description.strip() if body.description else None,
        deadline=body.deadline,
        max_marks=body.max_marks,
        attachment_url=body.attachment_url,
        attachment_name=body.attachment_name,
    )
    db.add(assignment)
    db.flush()

    # Person C Notification Integration: notify all enrolled students
    enrolled_student_ids = get_enrolled_student_ids(db, body.class_id)
    if enrolled_student_ids:
        subject_name = (
            db.query(Subject.name).filter(Subject.id == body.subject_id).scalar()
            if body.subject_id
            else "Class"
        )
        dispatch_bulk(
            db,
            user_ids=enrolled_student_ids,
            source_type="assignment_created",
            title=f"New Assignment: {body.title}",
            body=f"[{subject_name}] Due on {body.deadline.strftime('%b %d, %Y %H:%M')}. Max Marks: {body.max_marks}",
            priority="important",
            source_id=assignment.id,
        )

    db.commit()
    db.refresh(assignment)
    return _format_assignment(assignment, user, db)


@router.get("/assignments/{class_id}", response_model=list[AssignmentOut])
def get_class_assignments(
    class_id: int,
    subject_id: int | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all assignments for a class section."""
    school_class = (
        db.query(SchoolClass)
        .filter(SchoolClass.id == class_id, SchoolClass.school_id == user.school_id)
        .first()
    )
    if not school_class:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class section not found")

    # Authorization
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
        if class_id not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not teach this class section")

    query = db.query(Assignment).filter(Assignment.class_id == class_id)
    if subject_id is not None:
        query = query.filter(Assignment.subject_id == subject_id)

    assignments = query.order_by(Assignment.deadline.desc()).all()
    return [_format_assignment(a, user, db) for a in assignments]


@router.get("/assignments", response_model=list[AssignmentOut])
def list_my_assignments(
    subject_id: int | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return assignments across all accessible classes for the current user."""
    query = db.query(Assignment).filter(Assignment.school_id == user.school_id)

    if user.role == "student":
        student_class_ids = [
            row.class_id
            for row in db.query(Enrollment.class_id).filter(Enrollment.student_id == user.id).distinct().all()
        ]
        if not student_class_ids:
            return []
        query = query.filter(Assignment.class_id.in_(student_class_ids))
    elif user.role == "teacher":
        teacher_classes = _classes_taught_by(db, user.id)
        if not teacher_classes:
            return []
        query = query.filter(
            or_(Assignment.class_id.in_(teacher_classes), Assignment.teacher_id == user.id)
        )
    elif user.role == "parent":
        child_ids = [
            row.student_id
            for row in db.query(ParentStudent.student_id).filter(ParentStudent.parent_id == user.id).all()
        ]
        parent_class_ids = [
            row.class_id
            for row in db.query(Enrollment.class_id).filter(Enrollment.student_id.in_(child_ids)).distinct().all()
        ]
        if not parent_class_ids:
            return []
        query = query.filter(Assignment.class_id.in_(parent_class_ids))

    if subject_id is not None:
        query = query.filter(Assignment.subject_id == subject_id)

    assignments = query.order_by(Assignment.deadline.desc()).all()
    return [_format_assignment(a, user, db) for a in assignments]


@router.get("/assignments/detail/{assignment_id}", response_model=AssignmentOut)
def get_assignment_detail(
    assignment_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return detailed assignment view."""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).one_or_none()
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    if user.school_id and assignment.school_id != user.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")

    return _format_assignment(assignment, user, db)


@router.post("/assignments/{assignment_id}/upload", response_model=UploadFileOut)
async def upload_assignment_file(
    assignment_id: int,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload assignment prompts or student submission files."""
    if assignment_id != 0:
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).one_or_none()
        if not assignment:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    if len(data) > MAX_ASSIGNMENT_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds maximum allowed size of {MAX_ASSIGNMENT_FILE_BYTES} bytes",
        )

    filename = file.filename or "file.bin"
    content_type = file.content_type or "application/octet-stream"

    # Save to storage
    storage_path = f"{user.school_id}/assignments/{assignment_id}/{uuid.uuid4()}-{filename}"
    try:
        from app.services.supabase_admin import upload_resource_file

        upload_resource_file(path=storage_path, data=data, content_type=content_type)
        file_url = f"https://storage.eduops.local/resources/{storage_path}"
    except Exception:
        file_url = f"https://storage.eduops.local/assignments/{assignment_id}/{filename}"

    return UploadFileOut(
        file_name=filename,
        file_url=file_url,
        file_type=content_type,
        file_size=len(data),
    )


@router.post("/assignments/{assignment_id}/submit", response_model=SubmissionOut)
def submit_assignment(
    assignment_id: int,
    body: SubmitAssignmentRequest,
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    """Student submits an assignment. Calculates on-time vs late status."""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).one_or_none()
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")

    # Verify student is enrolled in this assignment's class
    is_enrolled = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == user.id, Enrollment.class_id == assignment.class_id)
        .first()
    )
    if not is_enrolled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot submit to an assignment for a class you are not enrolled in")

    now = datetime.now(timezone.utc)
    submission_status = "submitted" if now <= _to_utc(assignment.deadline) else "late"

    existing = (
        db.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.assignment_id == assignment_id,
            AssignmentSubmission.student_id == user.id,
        )
        .first()
    )

    if existing:
        if existing.grade is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This assignment has already been graded and cannot be resubmitted",
            )
        existing.file_url = body.file_url
        existing.file_name = body.file_name
        existing.file_size = body.file_size
        existing.status = submission_status
        existing.submitted_at = now
        db.commit()
        db.refresh(existing)
        return _format_submission(existing, db)

    submission = AssignmentSubmission(
        assignment_id=assignment_id,
        student_id=user.id,
        file_url=body.file_url,
        file_name=body.file_name,
        file_size=body.file_size,
        status=submission_status,
        submitted_at=now,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return _format_submission(submission, db)


@router.put("/assignments/{assignment_id}/grade/{submission_id}", response_model=SubmissionOut)
def grade_submission(
    assignment_id: int,
    submission_id: int,
    body: GradeSubmissionRequest,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Teacher grades an assignment submission."""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).one_or_none()
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")

    if user.role == "teacher":
        allowed = _classes_taught_by(db, user.id)
        if assignment.class_id not in allowed and assignment.teacher_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot grade this assignment")

    submission = (
        db.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.id == submission_id,
            AssignmentSubmission.assignment_id == assignment_id,
        )
        .one_or_none()
    )
    if not submission:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")

    # Validate grade within bounds
    if body.grade < 0 or body.grade > assignment.max_marks:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Grade must be between 0 and {assignment.max_marks} (got {body.grade})",
        )

    now = datetime.now(timezone.utc)
    submission.grade = body.grade
    submission.feedback = body.feedback.strip() if body.feedback else None
    submission.status = "graded"
    submission.graded_at = now

    # Person C Notification: Notify student of grade release
    dispatch_notification(
        db,
        user_id=submission.student_id,
        source_type="assignment_graded",
        title=f"Grade Released: {assignment.title}",
        body=f"You received {body.grade}/{assignment.max_marks} marks on '{assignment.title}'.",
        priority="important",
        source_id=assignment.id,
    )

    db.commit()
    db.refresh(submission)
    return _format_submission(submission, db)


@router.get("/assignments/{assignment_id}/submissions", response_model=list[SubmissionOut])
def get_assignment_submissions(
    assignment_id: int,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Teacher views submission list for all enrolled students in the class."""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).one_or_none()
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")

    if user.role == "teacher":
        allowed = _classes_taught_by(db, user.id)
        if assignment.class_id not in allowed and assignment.teacher_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view submissions")

    enrolled_student_ids = get_enrolled_student_ids(db, assignment.class_id)
    existing_submissions = {
        s.student_id: s
        for s in db.query(AssignmentSubmission)
        .filter(AssignmentSubmission.assignment_id == assignment_id)
        .all()
    }

    now = datetime.now(timezone.utc)
    is_past_deadline = _to_utc(assignment.deadline) <= now

    results: list[SubmissionOut] = []
    for sid in enrolled_student_ids:
        sub = existing_submissions.get(sid)
        if sub:
            results.append(_format_submission(sub, db))
        else:
            # Missing placeholder
            student = db.query(User).filter(User.id == sid).one_or_none()
            status_val = "missing" if is_past_deadline else "pending"
            results.append(
                SubmissionOut(
                    id=0,
                    assignment_id=assignment.id,
                    student_id=sid,
                    student_name=student.full_name if student else None,
                    student_email=student.email if student else None,
                    status=status_val,
                    created_at=assignment.created_at,
                    updated_at=assignment.created_at,
                )
            )

    return results


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(
    assignment_id: int,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Delete an assignment. Only author or admin/principal can delete."""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).one_or_none()
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")

    if user.role == "teacher" and assignment.teacher_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete assignments you created")

    db.delete(assignment)
    db.commit()


@router.post("/assignments/{assignment_id}/nudge/{student_id}")
def nudge_student(
    assignment_id: int,
    student_id: int,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Teacher sends a submission reminder nudge to a student."""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).one_or_none()
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")

    if user.role == "teacher":
        allowed = _classes_taught_by(db, user.id)
        if assignment.class_id not in allowed and assignment.teacher_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not authorized to nudge students for this class")

    # Verify student is enrolled
    is_enrolled = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == student_id, Enrollment.class_id == assignment.class_id)
        .first()
    )
    if not is_enrolled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student is not enrolled in this class section")

    sender_name = user.email.split("@")[0]
    teacher_record = db.query(User).filter(User.id == user.id).one_or_none()
    if teacher_record and teacher_record.full_name:
        sender_name = teacher_record.full_name

    # Dispatch notification to student
    dispatch_notification(
        db,
        user_id=student_id,
        source_type="assignment_nudge",
        title=f"Submission Reminder: {assignment.title}",
        body=f"Teacher {sender_name} has requested your submission for '{assignment.title}'. Due: {assignment.deadline.strftime('%b %d, %H:%M UTC')}.",
        priority="important",
        source_id=assignment.id,
    )

    # Also nudge parents if linked
    parent_ids = [
        row.parent_id
        for row in db.query(ParentStudent.parent_id).filter(ParentStudent.student_id == student_id).all()
    ]
    if parent_ids:
        dispatch_bulk(
            db,
            user_ids=parent_ids,
            source_type="assignment_nudge",
            title=f"Homework Reminder: {assignment.title}",
            body=f"Teacher {sender_name} reminded {student_id} to submit '{assignment.title}'.",
            priority="important",
            source_id=assignment.id,
        )

    db.commit()
    return {"status": "nudged", "student_id": student_id, "assignment_id": assignment_id}


@router.post("/assignments/{assignment_id}/nudge-missing")
def nudge_all_missing(
    assignment_id: int,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Teacher sends bulk submission reminder to all students who have not submitted."""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).one_or_none()
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")

    if user.role == "teacher":
        allowed = _classes_taught_by(db, user.id)
        if assignment.class_id not in allowed and assignment.teacher_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not authorized to nudge students for this class")

    enrolled_ids = get_enrolled_student_ids(db, assignment.class_id)
    submitted_ids = {
        s.student_id
        for s in db.query(AssignmentSubmission.student_id)
        .filter(
            AssignmentSubmission.assignment_id == assignment_id,
            AssignmentSubmission.status.in_(("submitted", "late", "graded")),
        )
        .all()
    }

    missing_ids = [sid for sid in enrolled_ids if sid not in submitted_ids]
    if not missing_ids:
        return {"status": "no_missing_students", "nudged_count": 0}

    sender_name = user.email.split("@")[0]
    teacher_record = db.query(User).filter(User.id == user.id).one_or_none()
    if teacher_record and teacher_record.full_name:
        sender_name = teacher_record.full_name

    dispatch_bulk(
        db,
        user_ids=missing_ids,
        source_type="assignment_nudge",
        title=f"Submission Reminder: {assignment.title}",
        body=f"Teacher {sender_name} sent a reminder to submit '{assignment.title}'.",
        priority="important",
        source_id=assignment.id,
    )

    db.commit()
    return {"status": "bulk_nudged", "nudged_count": len(missing_ids)}

