from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attendance import AttendanceRecord
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.fees import FeeRecord, FeeSchedule
from app.models.parent_student import ParentStudent
from app.models.risk import RemarkStub, RiskFlag
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.remark_sentiment import analyze_sentiment
from app.services.scoping import assert_parent_linked
from scripts.run_nightly_risk_scoring import ATTENDANCE_LOOKBACK_DAYS

router = APIRouter(prefix="/parent", tags=["parent"])

# Same gap-closing pattern as reference.py's /reference/lookup: the schema has
# real multi-child support (ParentStudent, see its own docstring) but no
# endpoint ever exposed "which children am I linked to" - every parent-scoped
# endpoint built so far (Timetable, Attendance, Risk) instead makes the parent
# type in a student_id by hand. That's a real, honestly-documented gap in each
# of those api-contract.md sections, not a bug - but it blocks a real parent
# dashboard from existing at all, so it's closed here, scoped strictly to the
# calling parent's own linked children (role-gated, not a general lookup).


class LinkedChild(BaseModel):
    id: int
    name: str
    class_id: int | None
    class_name: str | None

    model_config = ConfigDict(from_attributes=True)


class ChildrenResponse(BaseModel):
    items: list[LinkedChild]


@router.get("/children", response_model=ChildrenResponse)
def get_linked_children(
    user: CurrentUser = Depends(require_role("parent")),
    db: Session = Depends(get_db),
):
    links = db.query(ParentStudent).filter(ParentStudent.parent_id == user.id).all()
    student_ids = [link.student_id for link in links]
    students = db.query(User).filter(User.id.in_(student_ids)).all() if student_ids else []
    students_by_id = {s.id: s for s in students}

    # Same primary-enrollment resolution as timetable.py's _resolve_student_class_id.
    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.student_id.in_(student_ids), Enrollment.is_primary.is_(True))
        .all()
        if student_ids
        else []
    )
    class_id_by_student = {e.student_id: e.class_id for e in enrollments}
    class_ids = list(class_id_by_student.values())
    classes_by_id = {c.id: c for c in db.query(SchoolClass).filter(SchoolClass.id.in_(class_ids)).all()} if class_ids else {}

    items = []
    for student_id in student_ids:
        student = students_by_id.get(student_id)
        if student is None:
            continue
        class_id = class_id_by_student.get(student_id)
        school_class = classes_by_id.get(class_id) if class_id else None
        items.append(
            LinkedChild(
                id=student.id,
                name=student.full_name or student.email,
                class_id=class_id,
                class_name=school_class.name if school_class else None,
            )
        )

    return ChildrenResponse(items=items)


# --- GET /parent/child/{student_id}/summary -------------------------------------------
# ONE round trip for the whole parent portal. Composed from existing sources - the
# attendance aggregation, risk_flags, the Day 1 remarks query, fee status - rather than
# reimplementing any of them. Four sequential calls from a phone on venue wifi is a
# visibly slow screen; this is one.


class SummaryStudent(BaseModel):
    id: int
    name: str
    class_id: int | None
    class_name: str | None
    grade_level: int | None


class SummaryAttendance(BaseModel):
    present_pct: float
    present_count: int
    absent_count: int
    late_count: int
    days: int
    """Window size in CALENDAR days, matching run_nightly_risk_scoring's
    ATTENDANCE_LOOKBACK_DAYS. Deliberately the same window the risk scorer uses: if
    these diverged, the at-risk banner would quote one attendance figure while the
    attendance card directly above it showed a different one."""


class SummaryRisk(BaseModel):
    level: str
    score: float
    reasons: list[str]
    flagged_at: datetime


class SummarySentiment(BaseModel):
    label: str
    compound: float


class SummaryRemark(BaseModel):
    id: int
    teacher_name: str | None
    remark_text: str
    sentiment: SummarySentiment
    created_at: datetime


class SummaryFee(BaseModel):
    fee_record_id: int
    fee_type: str
    amount_due: float
    amount_paid: float
    status: str
    due_date: date


class SummaryUpcoming(BaseModel):
    type: str
    title: str
    date: date


class ChildSummaryResponse(BaseModel):
    student: SummaryStudent
    attendance: SummaryAttendance
    risk: SummaryRisk | None
    """None is the HEALTHY case - the UI hides the banner entirely rather than
    rendering an empty one. run_nightly_risk_scoring skips low-risk students, so a
    child with no open flag genuinely has no row here."""
    remarks: list[SummaryRemark]
    fees: list[SummaryFee]
    upcoming: list[SummaryUpcoming]


REMARK_LIMIT = 10


def _assert_can_view_child(db: Session, user: CurrentUser, student: User) -> None:
    """Parents: own linked children only. Admin/principal: own school only.

    Uses the shared scoping helper rather than a fifth inline copy of the
    ParentStudent lookup (services/scoping.py exists for exactly this).
    """
    if user.role == "parent":
        assert_parent_linked(db, user.id, student.id)
    elif user.role in ("admin", "principal"):
        if student.school_id != user.school_id:
            # 404 not 403, so an admin cannot probe another school's user ids by
            # status code - same reasoning as remarks.py and fees.py.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view this child")


@router.get("/child/{student_id}/summary", response_model=ChildSummaryResponse)
def child_summary(
    student_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    student = db.query(User).filter(User.id == student_id).one_or_none()
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    _assert_can_view_child(db, user, student)

    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == student_id, Enrollment.is_primary.is_(True))
        .one_or_none()
    )
    school_class = (
        db.query(SchoolClass).filter(SchoolClass.id == enrollment.class_id).one_or_none()
        if enrollment is not None
        else None
    )

    # --- attendance, over the SAME window the risk scorer uses ---
    since = date.today() - timedelta(days=ATTENDANCE_LOOKBACK_DAYS)
    records = (
        db.query(AttendanceRecord)
        .filter(AttendanceRecord.student_id == student_id, AttendanceRecord.date >= since)
        .all()
    )
    present = sum(1 for r in records if r.status == "present")
    absent = sum(1 for r in records if r.status == "absent")
    late = sum(1 for r in records if r.status == "late")
    total = len(records)

    # --- most recent OPEN risk flag ---
    flag = (
        db.query(RiskFlag)
        .filter(RiskFlag.student_id == student_id, RiskFlag.status == "open")
        .order_by(RiskFlag.flagged_at.desc(), RiskFlag.id.desc())
        .first()
    )

    # --- remarks, same query and per-request sentiment as GET /remarks/student/{id} ---
    remark_rows = (
        db.query(RemarkStub, User.full_name)
        .outerjoin(User, RemarkStub.teacher_id == User.id)
        .filter(RemarkStub.student_id == student_id)
        .order_by(RemarkStub.created_at.desc(), RemarkStub.id.desc())
        .limit(REMARK_LIMIT)
        .all()
    )

    # --- fees for this student ---
    fee_rows = (
        db.query(FeeRecord, FeeSchedule)
        .join(FeeSchedule, FeeRecord.fee_schedule_id == FeeSchedule.id)
        .filter(FeeRecord.student_id == student_id)
        .order_by(FeeRecord.due_date.desc())
        .all()
    )

    return ChildSummaryResponse(
        student=SummaryStudent(
            id=student.id,
            name=student.full_name or student.email,
            class_id=school_class.id if school_class else None,
            class_name=school_class.name if school_class else None,
            grade_level=school_class.grade_level if school_class else None,
        ),
        attendance=SummaryAttendance(
            present_pct=round(100 * present / total, 1) if total else 0.0,
            present_count=present, absent_count=absent, late_count=late,
            days=ATTENDANCE_LOOKBACK_DAYS,
        ),
        risk=(
            SummaryRisk(
                level=flag.risk_level, score=flag.score,
                reasons=list(flag.reasons or []), flagged_at=flag.flagged_at,
            )
            if flag is not None
            else None
        ),
        remarks=[
            SummaryRemark(
                id=remark.id, teacher_name=teacher_name, remark_text=remark.remark_text,
                sentiment=SummarySentiment(**_sentiment_fields(remark.remark_text)),
                created_at=remark.created_at,
            )
            for remark, teacher_name in remark_rows
        ],
        fees=[
            SummaryFee(
                fee_record_id=record.id, fee_type=schedule.fee_type,
                amount_due=record.amount_due, amount_paid=record.amount_paid,
                status=record.status, due_date=record.due_date,
            )
            for record, schedule in fee_rows
        ],
        # Deliberately empty. Exams/timetable events would be a third and fourth join
        # for the least important row on the screen; the field exists so adding them
        # later is not a response-shape change. See api-contract.md.
        upcoming=[],
    )


def _sentiment_fields(text: str) -> dict:
    result = analyze_sentiment(text)
    return {"label": result.label, "compound": result.compound}
