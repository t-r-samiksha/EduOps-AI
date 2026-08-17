"""Read access to teacher remarks (`remark_stubs`).

Read-only by design: creating remarks belongs to Person B's gradebook/report-card
system, which doesn't exist in this repo yet. This only surfaces the text the
early-warning scorer is already consuming, so a parent/student can see what's
behind a flag instead of just the derived sentiment inside a RiskFlag reason
string. See app/models/risk.py's RemarkStub docstring for why the backing table
is a placeholder and what changes when the real one lands (the query here; not
this module's response shape).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.risk import RemarkStub
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user
from app.services.remark_sentiment import analyze_sentiment
from app.services.scoping import assert_parent_linked, students_in_classes, teacher_class_ids

router = APIRouter(tags=["remarks"])


class SentimentOut(BaseModel):
    label: str
    compound: float


class RemarkOut(BaseModel):
    id: int
    student_id: int
    teacher_id: int
    teacher_name: str | None
    remark_text: str
    sentiment: SentimentOut
    """Computed per-request by services/remark_sentiment.py - there is no sentiment
    column on remark_stubs, and deliberately so: the scorer's thresholds can change
    without a backfill."""
    created_at: datetime


class RemarksResponse(BaseModel):
    items: list[RemarkOut]


@router.get("/remarks/student/{student_id}", response_model=RemarksResponse)
def student_remarks(
    student_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remarks about one student, newest first, scoped by caller role - same
    role-branching shape as routers/fees.py::fee_status."""
    student = db.query(User).filter(User.id == student_id).one_or_none()
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    if user.role in ("admin", "principal"):
        # Cross-tenant scoping: 404 rather than 403 so an admin can't probe
        # another school's user ids by status code (same reasoning as the
        # school_id filters in fees.py/admissions.py).
        if student.school_id != user.school_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    elif user.role == "teacher":
        if student_id not in students_in_classes(db, teacher_class_ids(db, user.id)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this student")
    elif user.role == "parent":
        assert_parent_linked(db, user.id, student_id)
    elif user.role == "student":
        if student_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this student")
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view remarks")

    rows = (
        db.query(RemarkStub, User.full_name)
        .outerjoin(User, RemarkStub.teacher_id == User.id)
        .filter(RemarkStub.student_id == student_id)
        .order_by(RemarkStub.created_at.desc(), RemarkStub.id.desc())
        .all()
    )

    items = []
    for remark, teacher_name in rows:
        result = analyze_sentiment(remark.remark_text)
        items.append(
            RemarkOut(
                id=remark.id,
                student_id=remark.student_id,
                teacher_id=remark.teacher_id,
                teacher_name=teacher_name,
                remark_text=remark.remark_text,
                sentiment=SentimentOut(label=result.label, compound=result.compound),
                created_at=remark.created_at,
            )
        )
    return RemarksResponse(items=items)
