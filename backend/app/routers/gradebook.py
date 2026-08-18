"""Gradebook and Assessment Scoring Router - Person B (Classroom & Academics).

Implements teacher grade recording, configurable category weights,
weighted score calculations, and 4.0 GPA evaluations.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.gradebook import GradebookEntry, GradebookWeight
from app.models.subject import Subject
from app.models.timetable import TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.scoping import assert_can_view_student_record
from app.services.gradebook_service import (
    get_student_gradebook_summary,
    get_term_weights,
    score_to_gpa,
)
from app.services.scoping import teacher_class_ids

router = APIRouter(tags=["gradebook"])


# --- Pydantic Schemas ---------------------------------------------------------------


class GradebookEntryIn(BaseModel):
    student_id: int
    subject_id: int
    class_id: int
    term: str = "Term 1"
    assessment_type: str = Field(description="assignment, quiz, exam, other")
    assessment_id: int | None = None
    score: float = Field(ge=0)
    max_score: float = Field(default=100.0, gt=0)
    weight: float = Field(default=1.0, gt=0)


class GradebookEntryOut(BaseModel):
    id: int
    student_id: int
    student_name: str | None = None
    subject_id: int
    subject_name: str | None = None
    class_id: int
    term: str
    assessment_type: str
    assessment_id: int | None = None
    score: float
    max_score: float
    percentage: float
    weight: float

    model_config = ConfigDict(from_attributes=True)


class BulkGradebookRequest(BaseModel):
    entries: list[GradebookEntryIn] = Field(min_length=1)


class WeightConfigRequest(BaseModel):
    term: str = "Term 1"
    assignment_weight: float = Field(ge=0, le=1)
    quiz_weight: float = Field(ge=0, le=1)
    midterm_weight: float = Field(ge=0, le=1)
    final_weight: float = Field(ge=0, le=1)
    other_weight: float = Field(default=0.0, ge=0, le=1)


# --- Endpoints ----------------------------------------------------------------------


@router.post("/gradebook/entry", response_model=GradebookEntryOut, status_code=status.HTTP_200_OK)
def upsert_gradebook_entry(
    body: GradebookEntryIn,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Teacher creates or updates an assessment gradebook entry idempotently."""
    if body.score > body.max_score:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Score ({body.score}) cannot exceed max score ({body.max_score})",
        )

    # Check existing
    existing = (
        db.query(GradebookEntry)
        .filter(
            GradebookEntry.student_id == body.student_id,
            GradebookEntry.subject_id == body.subject_id,
            GradebookEntry.term == body.term,
            GradebookEntry.assessment_type == body.assessment_type,
            GradebookEntry.assessment_id == body.assessment_id,
        )
        .first()
    )

    if existing:
        existing.score = body.score
        existing.max_score = body.max_score
        existing.weight = body.weight
        db.commit()
        db.refresh(existing)
        entry = existing
    else:
        entry = GradebookEntry(
            school_id=user.school_id or 1,
            student_id=body.student_id,
            subject_id=body.subject_id,
            class_id=body.class_id,
            term=body.term,
            assessment_type=body.assessment_type,
            assessment_id=body.assessment_id,
            score=body.score,
            max_score=body.max_score,
            weight=body.weight,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)

    student = db.query(User).filter(User.id == entry.student_id).one_or_none()
    subject = db.query(Subject).filter(Subject.id == entry.subject_id).one_or_none()
    pct = round((entry.score / entry.max_score) * 100.0, 1) if entry.max_score > 0 else 0.0

    return GradebookEntryOut(
        id=entry.id,
        student_id=entry.student_id,
        student_name=student.full_name if student else None,
        subject_id=entry.subject_id,
        subject_name=subject.name if subject else None,
        class_id=entry.class_id,
        term=entry.term,
        assessment_type=entry.assessment_type,
        assessment_id=entry.assessment_id,
        score=entry.score,
        max_score=entry.max_score,
        percentage=pct,
        weight=entry.weight,
    )


@router.post("/gradebook/bulk")
def bulk_upsert_gradebook(
    body: BulkGradebookRequest,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Teacher records marks for an entire class/assessment batch in one request."""
    saved_count = 0
    for e in body.entries:
        if e.score < 0 or e.score > e.max_score:
            continue

        existing = (
            db.query(GradebookEntry)
            .filter(
                GradebookEntry.student_id == e.student_id,
                GradebookEntry.subject_id == e.subject_id,
                GradebookEntry.term == e.term,
                GradebookEntry.assessment_type == e.assessment_type,
                GradebookEntry.assessment_id == e.assessment_id,
            )
            .first()
        )
        if existing:
            existing.score = e.score
            existing.max_score = e.max_score
            existing.weight = e.weight
        else:
            db.add(
                GradebookEntry(
                    school_id=user.school_id or 1,
                    student_id=e.student_id,
                    subject_id=e.subject_id,
                    class_id=e.class_id,
                    term=e.term,
                    assessment_type=e.assessment_type,
                    assessment_id=e.assessment_id,
                    score=e.score,
                    max_score=e.max_score,
                    weight=e.weight,
                )
            )
        saved_count += 1

    db.commit()
    return {"status": "saved", "count": saved_count}


@router.get("/gradebook/{student_id}")
def get_student_gradebook(
    student_id: int,
    term: str = Query(default="Term 1"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """View individual student's gradebook, term average, and 4.0 scale GPA."""
    assert_can_view_student_record(db, user, student_id, what="gradebook")

    return get_student_gradebook_summary(db, student_id, term)


@router.get("/gradebook/class/{class_id}")
def get_class_gradebook_grid(
    class_id: int,
    subject_id: int | None = None,
    term: str = Query(default="Term 1"),
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Teacher views class section gradebook matrix with student rows and calculated averages."""
    enrolled_students = (
        db.query(User)
        .join(Enrollment, Enrollment.student_id == User.id)
        .filter(Enrollment.class_id == class_id)
        .distinct()
        .all()
    )

    rows = []
    for s in enrolled_students:
        summary = get_student_gradebook_summary(db, s.id, term)
        rows.append({
            "student_id": s.id,
            "student_name": s.full_name or s.email,
            "term_average": summary["term_average"],
            "gpa": summary["gpa"],
            "letter_grade": summary["letter_grade"],
            "subjects": summary["subjects"],
        })

    return {"class_id": class_id, "term": term, "students": rows}


@router.get("/gradebook/config/weights")
def get_gradebook_weights_config(
    term: str = Query(default="Term 1"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get term assessment weighting configuration."""
    return get_term_weights(db, user.school_id or 1, term)


@router.put("/gradebook/config/weights")
def update_gradebook_weights_config(
    body: WeightConfigRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """Admin/Principal updates term assessment weighting configuration."""
    total = (
        body.assignment_weight + body.quiz_weight + body.midterm_weight + body.final_weight + body.other_weight
    )
    if round(total, 2) != 1.0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Weights must sum to 1.0 (got {total})",
        )

    row = (
        db.query(GradebookWeight)
        .filter(GradebookWeight.school_id == user.school_id, GradebookWeight.term == body.term)
        .first()
    )
    if row:
        row.assignment_weight = body.assignment_weight
        row.quiz_weight = body.quiz_weight
        row.midterm_weight = body.midterm_weight
        row.final_weight = body.final_weight
        row.other_weight = body.other_weight
    else:
        row = GradebookWeight(
            school_id=user.school_id or 1,
            term=body.term,
            assignment_weight=body.assignment_weight,
            quiz_weight=body.quiz_weight,
            midterm_weight=body.midterm_weight,
            final_weight=body.final_weight,
            other_weight=body.other_weight,
        )
        db.add(row)

    db.commit()
    return {"status": "updated", "weights": body.model_dump()}
