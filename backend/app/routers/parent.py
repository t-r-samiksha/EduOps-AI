import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attendance import AttendanceRecord
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.fees import FeePaymentRequest, FeeRecord, FeeSchedule
from app.models.parent_student import ParentStudent
from app.models.risk import RemarkStub, RiskFlag
from app.models.role import Role
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.fee_payments import outstanding_balance
from app.services.notify import dispatch_bulk
from app.services.remark_sentiment import analyze_sentiment
from app.services.attendance_stats import lookback_snapshot
from app.services.scoping import assert_parent_linked
from app.services.supabase_admin import PAYMENT_PROOFS_BUCKET, upload_file
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
    window_label: str = "Last 30 days"
    """M-2: the window travels with the number so the portal, student analytics and the
    report card each say WHICH attendance they are showing. The report card's
    academic-year figure is legitimately different; unlabelled, the pair reads as a
    discrepancy one click apart."""
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
    # M-2: counted here by services/attendance_stats.py, the single implementation every
    # surface shares. Three surfaces used to compute this independently and produced
    # three different numbers for one child.
    att = lookback_snapshot(db, student_id, ATTENDANCE_LOOKBACK_DAYS)
    present, absent, late, total = (
        att.present_count, att.absent_count, att.late_count, att.total_records
    )

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
            present_pct=att.present_pct if att.present_pct is not None else 0.0,
            present_count=present, absent_count=absent, late_count=late,
            days=ATTENDANCE_LOOKBACK_DAYS,
            window_label=att.label,
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


# --- Fee payment confirmation loop: the parent half -----------------------------------
#
# THERE IS NO PAYMENT GATEWAY HERE, and that is the design. Real Indian schools
# collect by UPI, bank transfer or cash at the office and reconcile against a bank
# statement by hand. So the parent pays through their own bank, records the reference
# here as a CLAIM, and an admin confirms it against the statement
# (PUT /admin/fee-payment-requests/{id}/confirm). Only that confirmation writes to
# fee_records.
#
# A row in fee_payment_requests is never the source of truth for whether a fee is
# paid - fee_records.status is, and stays so. That is what keeps the reminder engine
# honest: it reads FeeRecord, so a pending claim does NOT stop reminders firing. A
# parent asserting they have paid cannot silence the school's own alert chain.


PAYMENT_METHODS = ("UPI", "Bank Transfer", "Cash", "Other")
"""Documented vocabulary rather than a DB enum, same approach as
FeeSchedule.fee_type and Notification.source_type."""

PROOF_CONTENT_TYPES = ("image/jpeg", "image/png", "image/webp", "application/pdf")
MAX_PROOF_BYTES = 5 * 1024 * 1024


class PaymentRequestOut(BaseModel):
    id: int
    fee_record_id: int
    amount: float
    payment_method: str
    payment_reference: str
    status: str
    submitted_at: datetime
    reviewed_at: datetime | None
    rejection_reason: str | None
    has_proof: bool
    """A boolean rather than proof_url: the path points into a private bucket and a
    parent has no read route for it, so handing over the path would only invite a
    404 (or a probe)."""


class ParentFeeItem(BaseModel):
    fee_record_id: int
    fee_type: str
    amount_due: float
    amount_paid: float
    outstanding: float
    due_date: date
    record_status: str
    """The canonical fee_records.status - pending/paid/overdue/partial."""
    derived_status: str
    """unpaid | partially_paid | payment_pending | paid | rejected - what the parent
    should see, folding in any open or recently-rejected claim. See api-contract.md.

    `partially_paid` exists because "unpaid" was actively misleading on a fee the
    parent had already put money against: a 300 rupee fee with 200 recorded read
    exactly like one with nothing paid. Anything short of the full amount is still
    INCOMPLETE and stays visible in every portal until it is settled - a part payment
    reduces what is owed, it never removes the obligation from view."""
    request: PaymentRequestOut | None


class ParentFeesResponse(BaseModel):
    student_id: int
    student_name: str
    items: list[ParentFeeItem]


def _request_out(request: FeePaymentRequest) -> PaymentRequestOut:
    return PaymentRequestOut(
        id=request.id,
        fee_record_id=request.fee_record_id,
        amount=request.amount,
        payment_method=request.payment_method,
        payment_reference=request.payment_reference,
        status=request.status,
        submitted_at=request.submitted_at,
        reviewed_at=request.reviewed_at,
        rejection_reason=request.rejection_reason,
        has_proof=request.proof_url is not None,
    )


def _resolve_child(db: Session, user: CurrentUser, student_id: int) -> User:
    """The student a caller is allowed to read fees for.

    A parent must be linked (assert_parent_linked raises 403 otherwise). Staff are
    allowed through for support purposes but confined to their own school, so this
    can't become a cross-tenant read of any student's fee history.
    """
    if user.role == "parent":
        assert_parent_linked(db, user.id, student_id)
    elif user.role in ("admin", "principal", "teacher"):
        if user.school_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account is not linked to a school")
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view a child's fees")

    student = db.query(User).filter(User.id == student_id).one_or_none()
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    if user.role in ("admin", "principal", "teacher") and student.school_id != user.school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    return student


@router.get("/child/{student_id}/fees", response_model=ParentFeesResponse)
def child_fees(
    student_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One child's fees with a status that folds in any open payment claim.

    Exists as its own endpoint rather than reusing GET /admin/fees/status because
    `payment_pending` and `rejected` are not expressible from fee_records at all -
    they come from fee_payment_requests.
    """
    student = _resolve_child(db, user, student_id)

    rows = (
        db.query(FeeRecord, FeeSchedule)
        .join(FeeSchedule, FeeRecord.fee_schedule_id == FeeSchedule.id)
        .filter(FeeRecord.student_id == student_id)
        .order_by(FeeRecord.due_date.desc())
        .all()
    )
    record_ids = [record.id for record, _ in rows]

    # Newest first, so the first row seen per fee is the one that matters.
    requests_by_record: dict[int, list[FeePaymentRequest]] = {}
    if record_ids:
        for request in (
            db.query(FeePaymentRequest)
            .filter(FeePaymentRequest.fee_record_id.in_(record_ids))
            .order_by(FeePaymentRequest.submitted_at.desc(), FeePaymentRequest.id.desc())
        ):
            requests_by_record.setdefault(request.fee_record_id, []).append(request)

    items: list[ParentFeeItem] = []
    for record, schedule in rows:
        history = requests_by_record.get(record.id, [])
        open_request = next((r for r in history if r.status == "pending"), None)
        relevant = open_request or (history[0] if history else None)

        # Precedence, most actionable first. `paid` is the ONLY settled state: a
        # record is settled when the school has the whole amount, never merely
        # because some of it arrived.
        if record.status == "paid" or record.amount_paid >= record.amount_due:
            derived = "paid"
        elif open_request is not None:
            derived = "payment_pending"
        elif relevant is not None and relevant.status == "rejected":
            # A rejected claim outranks partially_paid: the parent needs to know their
            # last submission was declined before they see the balance.
            derived = "rejected"
        elif record.amount_paid > 0:
            derived = "partially_paid"
        else:
            derived = "unpaid"

        items.append(
            ParentFeeItem(
                fee_record_id=record.id,
                fee_type=schedule.fee_type,
                amount_due=record.amount_due,
                amount_paid=record.amount_paid,
                outstanding=outstanding_balance(record),
                due_date=record.due_date,
                record_status=record.status,
                derived_status=derived,
                request=_request_out(relevant) if relevant is not None else None,
            )
        )

    return ParentFeesResponse(
        student_id=student_id,
        student_name=student.full_name or student.email,
        items=items,
    )


@router.post("/child/{student_id}/fees/{fee_record_id}/payment-request", response_model=PaymentRequestOut)
async def create_payment_request(
    student_id: int,
    fee_record_id: int,
    payment_method: str = Form(...),
    payment_reference: str = Form(...),
    amount: float = Form(...),
    proof_file: UploadFile | None = File(None),
    user: CurrentUser = Depends(require_role("parent")),
    db: Session = Depends(get_db),
):
    """Raise a claim that this fee has been paid outside the system.

    Parent-only on purpose: a staff member recording a payment they collected uses
    POST /admin/fees/records/{id}/payment, which writes to the fee record directly
    and needs no confirmation step.
    """
    assert_parent_linked(db, user.id, student_id)

    record = (
        db.query(FeeRecord)
        .filter(FeeRecord.id == fee_record_id, FeeRecord.student_id == student_id)
        .one_or_none()
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fee record not found for this student")
    if record.status == "paid":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This fee is already fully paid")

    if payment_method not in PAYMENT_METHODS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"payment_method must be one of {PAYMENT_METHODS}")
    if not payment_reference.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "payment_reference is required")
    if amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "amount must be positive")

    outstanding = outstanding_balance(record)
    if amount > outstanding:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"amount {amount} is more than the outstanding balance of {outstanding}",
        )

    # Checked here for a clean 400 with a useful message; the partial unique index
    # uq_fee_payment_request_one_open is what actually guarantees it, since two
    # concurrent submits would both pass this SELECT.
    existing = (
        db.query(FeePaymentRequest)
        .filter(
            FeePaymentRequest.fee_record_id == fee_record_id,
            FeePaymentRequest.status == "pending",
        )
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A payment request for this fee is already awaiting review",
        )

    proof_path: str | None = None
    if proof_file is not None and proof_file.filename:
        content_type = proof_file.content_type or "application/octet-stream"
        if content_type not in PROOF_CONTENT_TYPES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"proof_file must be one of {PROOF_CONTENT_TYPES}"
            )
        data = await proof_file.read()
        if len(data) > MAX_PROOF_BYTES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"proof_file is larger than {MAX_PROOF_BYTES // (1024 * 1024)}MB",
            )
        suffix = Path(proof_file.filename).suffix or ""
        # The stored path carries the fee record id and a uuid, never the parent's
        # original filename - collision-free, and a crafted filename can't steer the
        # object path.
        proof_path = upload_file(
            path=f"fee-proofs/{fee_record_id}/{uuid.uuid4().hex}{suffix}",
            data=data,
            content_type=content_type,
            bucket=PAYMENT_PROOFS_BUCKET,
        )

    request = FeePaymentRequest(
        fee_record_id=fee_record_id,
        student_id=student_id,
        parent_id=user.id,
        amount=round(amount, 2),
        payment_method=payment_method,
        payment_reference=payment_reference.strip(),
        proof_url=proof_path,
        status="pending",
    )
    db.add(request)
    db.flush()

    student = db.query(User).filter(User.id == student_id).one()
    parent_row = db.query(User).filter(User.id == user.id).one()
    parent_name = parent_row.full_name or parent_row.email or "A parent"
    schedule = db.query(FeeSchedule).filter(FeeSchedule.id == record.fee_schedule_id).one()

    # Every admin and principal in the STUDENT'S school - not the caller's own
    # school_id, which can legitimately be null on a parent account.
    reviewer_ids = [
        row.id
        for row in db.query(User.id)
        .join(Role, User.role_id == Role.id)
        .filter(User.school_id == student.school_id, Role.name.in_(("admin", "principal")))
    ]
    dispatch_bulk(
        db,
        user_ids=reviewer_ids,
        source_type="fee_payment_request",
        title=f"{parent_name} reports paying {request.amount:.2f} for {student.full_name or student.email}",
        body=(
            f"{schedule.fee_type} - {payment_method} ref {request.payment_reference}. "
            f"Outstanding before this claim: {outstanding:.2f}. "
            "Confirm or reject it in the fee payment queue."
        ),
        priority="important",
        source_id=request.id,
    )

    db.commit()
    db.refresh(request)
    return _request_out(request)
