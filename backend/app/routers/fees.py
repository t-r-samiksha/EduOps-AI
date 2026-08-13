from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.fees import FeeRecord, FeeReminder, FeeSchedule
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, require_role
from app.services.fee_reminder_engine import determine_reminder

router = APIRouter(tags=["fees"])


# --- Fee schedule config: create/list ------------------------------------------------


class ScheduleCreateRequest(BaseModel):
    school_id: int
    class_id: int | None = None
    """Omit/null for a school-wide fee; set for a class-specific one."""
    academic_year: str
    fee_type: str
    amount: float
    due_date: date


class ScheduleOut(BaseModel):
    id: int
    school_id: int
    class_id: int | None
    academic_year: str
    fee_type: str
    amount: float
    due_date: date
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("/admin/fees/schedules", response_model=ScheduleOut)
def create_schedule(
    body: ScheduleCreateRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if body.amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "amount must be positive")
    if not body.fee_type.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "fee_type must not be empty")
    if body.class_id is not None and db.query(SchoolClass).filter(SchoolClass.id == body.class_id).one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")

    schedule = FeeSchedule(
        school_id=body.school_id, class_id=body.class_id, academic_year=body.academic_year,
        fee_type=body.fee_type, amount=body.amount, due_date=body.due_date,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return ScheduleOut.model_validate(schedule)


@router.get("/admin/fees/schedules", response_model=list[ScheduleOut])
def list_schedules(
    school_id: int | None = None,
    academic_year: str | None = None,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    query = db.query(FeeSchedule)
    if school_id is not None:
        query = query.filter(FeeSchedule.school_id == school_id)
    if academic_year is not None:
        query = query.filter(FeeSchedule.academic_year == academic_year)
    return [ScheduleOut.model_validate(s) for s in query.order_by(FeeSchedule.due_date.desc()).all()]


# --- POST /admin/fees/reminders ------------------------------------------------------


class RemindersRequest(BaseModel):
    class_id: int | None = None
    overdue_only: bool = True


class RemindersResponse(BaseModel):
    sent_count: int


@router.post("/admin/fees/reminders", response_model=RemindersResponse)
def trigger_reminders(
    body: RemindersRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    today = date.today()
    query = db.query(FeeRecord)
    if body.class_id is not None:
        query = query.join(FeeSchedule, FeeRecord.fee_schedule_id == FeeSchedule.id).filter(FeeSchedule.class_id == body.class_id)
    if body.overdue_only:
        query = query.filter(FeeRecord.status == "overdue")
    else:
        query = query.filter(FeeRecord.status.in_(("overdue", "pending", "partial")))

    sent_count = 0
    for record in query.all():
        days_overdue = (today - record.due_date).days
        already_sent = {r.cadence_reason for r in db.query(FeeReminder).filter(FeeReminder.fee_record_id == record.id)}
        decision = determine_reminder(days_overdue, already_sent)
        if decision.should_send:
            db.add(FeeReminder(fee_record_id=record.id, cadence_reason=decision.cadence_reason, sent_at=None))
            sent_count += 1

    db.commit()
    return RemindersResponse(sent_count=sent_count)


# --- GET /admin/fees/status -----------------------------------------------------------


class StatusItemOut(BaseModel):
    student_id: int
    fee_record_id: int
    amount_due: float
    amount_paid: float
    due_date: date
    status: str


class StatusResponse(BaseModel):
    items: list[StatusItemOut]


@router.get("/admin/fees/status", response_model=StatusResponse)
def fee_status(
    class_id: int | None = None,
    status_filter: str | None = Query(None, alias="status"),
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    query = db.query(FeeRecord)
    if class_id is not None:
        query = query.join(FeeSchedule, FeeRecord.fee_schedule_id == FeeSchedule.id).filter(FeeSchedule.class_id == class_id)
    if status_filter is not None:
        query = query.filter(FeeRecord.status == status_filter)

    items = [
        StatusItemOut(
            student_id=r.student_id, fee_record_id=r.id, amount_due=r.amount_due, amount_paid=r.amount_paid,
            due_date=r.due_date, status=r.status,
        )
        for r in query.order_by(FeeRecord.due_date.desc()).all()
    ]
    return StatusResponse(items=items)


# --- Payment reconciliation -----------------------------------------------------------
# Records a payment however it was collected (cash at the office, bank transfer,
# etc.) - the frontend payment-collection UI itself is explicitly Person C's
# parent-portal territory per the team build plan; this only persists the outcome.


class PaymentRequest(BaseModel):
    amount: float
    paid_at: datetime | None = None
    """Defaults to now if omitted."""


class PaymentResponse(BaseModel):
    fee_record_id: int
    amount_paid: float
    amount_due: float
    status: str


@router.post("/admin/fees/records/{fee_record_id}/payment", response_model=PaymentResponse)
def record_payment(
    fee_record_id: int,
    body: PaymentRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if body.amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "amount must be positive")

    record = db.query(FeeRecord).filter(FeeRecord.id == fee_record_id).one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fee record not found")

    previous_paid = record.amount_paid
    record.amount_paid = round(record.amount_paid + body.amount, 2)
    if record.amount_paid >= record.amount_due:
        record.status = "paid"
    elif record.amount_paid > 0:
        record.status = "partial"

    write_audit_log(
        db, actor_id=user.id, action="record_payment", entity_type="fee_records", entity_id=record.id,
        detail={"amount": body.amount, "previous_amount_paid": previous_paid, "new_amount_paid": record.amount_paid, "new_status": record.status},
    )
    db.commit()
    db.refresh(record)

    return PaymentResponse(fee_record_id=record.id, amount_paid=record.amount_paid, amount_due=record.amount_due, status=record.status)
