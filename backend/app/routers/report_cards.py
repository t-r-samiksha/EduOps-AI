"""Report Card Automation Router - Person B (Classroom & Academics).

Implements automated student academic transcripts and report card generation.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.report_card import ReportCard
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.scoping import assert_can_view_student_record
from app.services.report_card_service import (
    bulk_generate_class_report_cards,
    generate_single_report_card,
)

router = APIRouter(tags=["report_cards"])


class ReportCardOut(BaseModel):
    id: int
    school_id: int
    student_id: int
    class_id: int
    term: str
    academic_year: str
    pdf_url: str | None = None
    gpa: float | None = None
    term_average: float | None = None
    attendance_percentage: float | None = None
    source_data_snapshot: dict[str, Any]
    generated_at: Any

    model_config = ConfigDict(from_attributes=True)


def _assert_student_in_caller_school(db: Session, user: CurrentUser, student_id: int) -> None:
    """404 unless the student belongs to the caller's school."""
    student = db.query(User).filter(User.id == student_id).one_or_none()
    if student is None or student.school_id != user.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found in your school")


@router.post("/report_cards/generate/{student_id}", response_model=ReportCardOut)
def generate_student_report_card(
    student_id: int,
    term: str = Query(default="Term 1"),
    academic_year: str = Query(default="2026-27"),
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Generate or update an official academic report card transcript for a student."""
    # BLOCKER B-3: neither this router nor the service compared the student's school to
    # the caller's, so a teacher could generate a report card for another tenant's
    # student AND dispatch notifications to that school's parents. 404 not 403 so
    # student ids in other schools cannot be probed by status code.
    _assert_student_in_caller_school(db, user, student_id)
    try:
        report_card = generate_single_report_card(db, student_id, term, academic_year)
        return report_card
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.post("/report_cards/bulk-generate/{class_id}")
def bulk_generate_reports(
    class_id: int,
    term: str = Query(default="Term 1"),
    academic_year: str = Query(default="2026-27"),
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """High-performance batch report card generation for an entire class section."""
    # BLOCKER B-3, same gap on the bulk path: class_id was unscoped.
    school_class = (
        db.query(SchoolClass)
        .filter(SchoolClass.id == class_id, SchoolClass.school_id == user.school_id)
        .one_or_none()
    )
    if school_class is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class section not found in your school")

    cards = bulk_generate_class_report_cards(db, class_id, term, academic_year)
    return {
        "status": "generated",
        "class_id": class_id,
        "count": len(cards),
        "term": term,
    }


@router.get("/report_cards/{student_id}", response_model=list[ReportCardOut])
def list_student_report_cards(
    student_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List published report cards for a student."""
    assert_can_view_student_record(db, user, student_id, what="report cards")

    cards = (
        db.query(ReportCard)
        .filter(ReportCard.student_id == student_id)
        .order_by(ReportCard.generated_at.desc())
        .all()
    )
    return cards


@router.get("/report_cards/detail/{report_card_id}", response_model=ReportCardOut)
def get_report_card_detail(
    report_card_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """View full structured report card data."""
    card = db.query(ReportCard).filter(ReportCard.id == report_card_id).one_or_none()
    if not card:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report card not found")

    assert_can_view_student_record(db, user, card.student_id, what="report card")

    return card
