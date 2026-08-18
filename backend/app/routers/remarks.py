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
from app.models.subject import Subject
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user
from app.services.scoping import assert_can_view_student_record
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


# --- Person B Official Remarks Endpoints --------------------------------------------


class SingleRemarkIn(BaseModel):
    student_id: int
    class_id: int
    subject_id: int | None = None
    content: str
    sentiment_tag: str = "academic"  # academic, behavioral, appreciation


class BulkRemarkItem(BaseModel):
    student_id: int
    content: str
    sentiment_tag: str = "academic"


class BulkRemarkRequest(BaseModel):
    class_id: int
    subject_id: int | None = None
    remarks: list[BulkRemarkItem]


class RemarkRecordOut(BaseModel):
    id: int
    student_id: int
    student_name: str | None = None
    author_id: int
    author_name: str | None = None
    class_id: int
    subject_id: int | None = None
    subject_name: str | None = None
    content: str
    sentiment_tag: str
    created_at: datetime


@router.post("/remarks", response_model=RemarkRecordOut, status_code=status.HTTP_201_CREATED)
def create_remark(
    body: SingleRemarkIn,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Teacher adds a single remark for a student."""
    from app.models.remark import Remark
    from app.services.remark_service import create_single_remark

    r = create_single_remark(
        db=db,
        school_id=user.school_id or 1,
        author_id=user.id,
        student_id=body.student_id,
        class_id=body.class_id,
        content=body.content,
        sentiment_tag=body.sentiment_tag,
        subject_id=body.subject_id,
    )

    student = db.query(User).filter(User.id == r.student_id).first()
    author = db.query(User).filter(User.id == r.author_id).first()
    subj = db.query(Subject).filter(Subject.id == r.subject_id).first() if r.subject_id else None

    return RemarkRecordOut(
        id=r.id,
        student_id=r.student_id,
        student_name=student.full_name if student else None,
        author_id=r.author_id,
        author_name=author.full_name if author else None,
        class_id=r.class_id,
        subject_id=r.subject_id,
        subject_name=subj.name if subj else None,
        content=r.content,
        sentiment_tag=r.sentiment_tag,
        created_at=r.created_at,
    )


@router.post("/remarks/bulk")
def create_bulk_remarks_endpoint(
    body: BulkRemarkRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Teacher creates remarks for multiple students in one batch request."""
    from app.services.remark_service import create_bulk_remarks

    raw_items = [
        {"student_id": item.student_id, "content": item.content, "sentiment_tag": item.sentiment_tag}
        for item in body.remarks
    ]
    created = create_bulk_remarks(
        db=db,
        school_id=user.school_id or 1,
        author_id=user.id,
        class_id=body.class_id,
        remarks_data=raw_items,
        subject_id=body.subject_id,
    )
    return {"status": "created", "count": len(created)}


@router.get("/remarks/{student_id}", response_model=list[RemarkRecordOut])
def get_student_remark_history(
    student_id: int,
    sentiment_tag: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """View chronological remark history for a student with optional sentiment filter."""
    from app.models.remark import Remark

    assert_can_view_student_record(db, user, student_id, what="remarks")

    query = db.query(Remark).filter(Remark.student_id == student_id)
    if sentiment_tag:
        query = query.filter(Remark.sentiment_tag == sentiment_tag.lower())

    rows = query.order_by(Remark.created_at.desc()).all()

    results = []
    for r in rows:
        student = db.query(User).filter(User.id == r.student_id).first()
        author = db.query(User).filter(User.id == r.author_id).first()
        subj = db.query(Subject).filter(Subject.id == r.subject_id).first() if r.subject_id else None
        results.append(
            RemarkRecordOut(
                id=r.id,
                student_id=r.student_id,
                student_name=student.full_name if student else None,
                author_id=r.author_id,
                author_name=author.full_name if author else None,
                class_id=r.class_id,
                subject_id=r.subject_id,
                subject_name=subj.name if subj else None,
                content=r.content,
                sentiment_tag=r.sentiment_tag,
                created_at=r.created_at,
            )
        )
    return results

