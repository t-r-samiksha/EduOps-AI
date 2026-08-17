from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.fees import FeeRecord, FeeReminder, FeeSchedule
from app.models.parent_student import ParentStudent
from app.models.school import School
from app.models.user import User
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.fee_reminder_engine import determine_reminder
from app.services.notify import dispatch_bulk
from scripts.run_monthly_fee_invoicing import AUTO_GENERATE_WINDOW_DAYS, generate_fee_records_for_schedule, run_monthly_invoicing

router = APIRouter(tags=["fees"])


# --- Scoping helpers - same shape as routers/risk.py's (each domain router keeps its
# own copy rather than sharing one, matching this codebase's "keep Person A/B/C's
# code in separate files" convention) --------------------------------------------------


def _teacher_class_ids(db: Session, teacher_id: int) -> list[int]:
    return [c.id for c in db.query(SchoolClass).filter(SchoolClass.class_teacher_id == teacher_id).all()]


def _students_in_classes(db: Session, class_ids: list[int]) -> set[int]:
    if not class_ids:
        return set()
    return {
        row.student_id
        for row in db.query(Enrollment.student_id).filter(
            Enrollment.class_id.in_(class_ids), Enrollment.is_primary.is_(True)
        )
    }


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
    records_generated: bool
    """Whether at least one FeeRecord exists for this schedule yet. False means
    its due_date is still more than AUTO_GENERATE_WINDOW_DAYS away (nothing has
    triggered generation for it yet) - use POST .../generate to do it early."""

    model_config = ConfigDict(from_attributes=True)


def _schedule_out(db: Session, schedule: FeeSchedule) -> ScheduleOut:
    records_generated = db.query(FeeRecord).filter(FeeRecord.fee_schedule_id == schedule.id).first() is not None
    return ScheduleOut(
        id=schedule.id, school_id=schedule.school_id, class_id=schedule.class_id, academic_year=schedule.academic_year,
        fee_type=schedule.fee_type, amount=schedule.amount, due_date=schedule.due_date, created_at=schedule.created_at,
        records_generated=records_generated,
    )


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
    if db.query(School).filter(School.id == body.school_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown school_id {body.school_id}")
    if body.class_id is not None and db.query(SchoolClass).filter(SchoolClass.id == body.class_id).one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")

    schedule = FeeSchedule(
        school_id=body.school_id, class_id=body.class_id, academic_year=body.academic_year,
        fee_type=body.fee_type, amount=body.amount, due_date=body.due_date,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)

    # Auto-generates only if due soon (within AUTO_GENERATE_WINDOW_DAYS) - a fee
    # due months out shouldn't materialize the moment its schedule is created;
    # it'll generate on its own once the nightly job sees it inside the window,
    # or an admin can generate it early via POST .../generate on the schedule card.
    run_monthly_invoicing(db, body.school_id, body.academic_year, generate_only_due_within_days=AUTO_GENERATE_WINDOW_DAYS)

    return _schedule_out(db, schedule)


@router.post("/admin/fees/schedules/{schedule_id}/generate", response_model=ScheduleOut)
def generate_schedule_records(
    schedule_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """The per-schedule manual override - generates this ONE schedule's records
    right now regardless of due_date, for an admin who doesn't want to wait for
    the auto-generate window (or to backfill a student enrolled after the last
    run). Ungated, unlike the automatic paths."""
    schedule = (
        db.query(FeeSchedule).filter(FeeSchedule.id == schedule_id, FeeSchedule.school_id == user.school_id).one_or_none()
    )
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fee schedule not found")

    generate_fee_records_for_schedule(db, schedule)
    db.commit()
    return _schedule_out(db, schedule)


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
    # Ascending - soonest due date first, so what needs attention (approaching
    # the auto-generate window, or already overdue) surfaces at the top.
    return [_schedule_out(db, s) for s in query.order_by(FeeSchedule.due_date.asc()).all()]


# --- POST /admin/fees/invoicing/run --------------------------------------------------
# Bulk on-demand version of the same job the nightly scheduler now runs every night
# (app/scheduler.py::run_monthly_fee_invoicing_job, 02:45 UTC) - reuses the exact same
# pure function, but WITHOUT the auto-generate due-date window (unlike the nightly job
# and schedule creation, both of which pass generate_only_due_within_days). An explicit
# "generate everything for this school+year right now" - mainly useful for backfilling
# records for students enrolled after their class's schedule already existed. The
# per-schedule POST .../generate above is the narrower, more common version of this.


class RunInvoicingRequest(BaseModel):
    academic_year: str


class RunInvoicingResponse(BaseModel):
    records_created: int
    overdue_marked: int
    reminders_sent: int


@router.post("/admin/fees/invoicing/run", response_model=RunInvoicingResponse)
def run_invoicing(
    body: RunInvoicingRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    summary = run_monthly_invoicing(db, user.school_id, body.academic_year)
    write_audit_log(
        db, actor_id=user.id, action="run_fee_invoicing", entity_type="school", entity_id=user.school_id,
        detail={"academic_year": body.academic_year, **summary},
    )
    db.commit()
    return RunInvoicingResponse(**summary)


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
    # Scoped to the caller's own school - same fix as GET /admin/fees/status and
    # POST /admin/fees/records/{id}/payment above, and the same bug class fixed in
    # admissions.py/approvals.py/risk.py. FeeRecord has no school_id of its own
    # (only student_id), so the scoping has to go through User. Without this, an
    # admin from ANY school reminded EVERY school's overdue records - which was
    # merely invisible while a reminder was just a FeeReminder row nobody read, and
    # became a real cross-tenant leak the moment this endpoint started dispatching
    # notifications to actual parents (below).
    query = db.query(FeeRecord).join(User, FeeRecord.student_id == User.id).filter(User.school_id == user.school_id)
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
            # Reaches the parents the reminder is actually for - the FeeReminder row
            # on its own only records that a reminder was decided on, it never told
            # anyone. Commits atomically with that row via the db.commit() below.
            dispatch_bulk(
                db,
                user_ids=[
                    r.parent_id
                    for r in db.query(ParentStudent.parent_id).filter(ParentStudent.student_id == record.student_id)
                ],
                source_type="fee_reminder",
                title=f"Fee payment {'overdue' if record.status == 'overdue' else 'due'}",
                body=f"{record.fee_schedule.fee_type}: {record.amount_due - record.amount_paid:.2f} due {record.due_date.isoformat()}",
                priority="urgent" if record.status == "overdue" else "normal",
                source_id=record.id,
            )
            sent_count += 1

    db.commit()
    return RemindersResponse(sent_count=sent_count)


# --- GET /admin/fees/status -----------------------------------------------------------
# One shared endpoint across roles, scoped differently per caller - same pattern as
# routers/risk.py's GET /risk/flagged: admin/principal see their whole school, a
# teacher sees only their own class(es) (SchoolClass.class_teacher_id), a parent must
# name one of their own linked children, a student always sees only themselves. Kept
# at this same path (rather than splitting into /teacher/.../parent/.../student/...
# variants) so the existing admin frontend/tests/docs are untouched.


class StatusItemOut(BaseModel):
    student_id: int
    fee_record_id: int
    amount_due: float
    amount_paid: float
    due_date: date
    status: str
    fee_type: str
    """From the fee's FeeSchedule - without this, a student/parent sees "you owe
    ₹500 by 2026-09-20" with no way to tell tuition from an event fee."""


class StatusResponse(BaseModel):
    items: list[StatusItemOut]


@router.get("/admin/fees/status", response_model=StatusResponse)
def fee_status(
    class_id: int | None = None,
    student_id: int | None = None,
    status_filter: str | None = Query(None, alias="status"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(FeeRecord)

    if user.role in ("admin", "principal"):
        # Unchanged from before this session's fix: class_id filters by which class
        # the FeeSchedule itself was raised for (join through FeeSchedule), not by a
        # student's current Enrollment - a fee assigned to "Grade 8A" should still
        # show under Grade 8A even if the student later transfers classes. Only the
        # school_id scoping (via User) is new here - previously this branch had none
        # at all, a real cross-tenant leak matching the same bug class fixed
        # elsewhere in admissions.py/approvals.py.
        query = query.join(User, FeeRecord.student_id == User.id).filter(User.school_id == user.school_id)
        if class_id is not None:
            query = query.join(FeeSchedule, FeeRecord.fee_schedule_id == FeeSchedule.id).filter(FeeSchedule.class_id == class_id)
        if student_id is not None:
            query = query.filter(FeeRecord.student_id == student_id)
    elif user.role == "teacher":
        owned_class_ids = _teacher_class_ids(db, user.id)
        if class_id is not None:
            if class_id not in owned_class_ids:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your class")
            owned_class_ids = [class_id]
        allowed_students = _students_in_classes(db, owned_class_ids)
        if student_id is not None:
            allowed_students &= {student_id}
        query = query.filter(FeeRecord.student_id.in_(allowed_students or [-1]))
    elif user.role == "parent":
        if student_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "student_id is required for parent role")
        link = (
            db.query(ParentStudent)
            .filter(ParentStudent.parent_id == user.id, ParentStudent.student_id == student_id)
            .one_or_none()
        )
        if link is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not linked to this student")
        query = query.filter(FeeRecord.student_id == student_id)
    elif user.role == "student":
        query = query.filter(FeeRecord.student_id == user.id)
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view fee status")

    if status_filter is not None:
        query = query.filter(FeeRecord.status == status_filter)

    items = [
        StatusItemOut(
            student_id=r.student_id, fee_record_id=r.id, amount_due=r.amount_due, amount_paid=r.amount_paid,
            due_date=r.due_date, status=r.status, fee_type=r.fee_schedule.fee_type,
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

    record = (
        db.query(FeeRecord)
        .join(User, FeeRecord.student_id == User.id)
        .filter(FeeRecord.id == fee_record_id, User.school_id == user.school_id)
        .one_or_none()
    )
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


# --- PATCH /admin/fees/records/{id}/mark-paid -----------------------------------------
# The class teacher's lightweight counterpart to record_payment above: a plain
# paid/not-paid toggle, not an amount-reconciliation tool - a class teacher tracking
# "who in my class still owes the event fee" needs a checkbox, not to enter partial
# payment amounts (that stays admin/principal-only via the endpoint above). Scoped to
# the teacher's own class via SchoolClass.class_teacher_id, same ownership model as
# routers/risk.py's _teacher_class_ids.


class MarkPaidRequest(BaseModel):
    paid: bool


@router.patch("/admin/fees/records/{fee_record_id}/mark-paid", response_model=PaymentResponse)
def mark_fee_paid(
    fee_record_id: int,
    body: MarkPaidRequest,
    user: CurrentUser = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
):
    owned_class_ids = _teacher_class_ids(db, user.id)
    owned_students = _students_in_classes(db, owned_class_ids)

    record = (
        db.query(FeeRecord).filter(FeeRecord.id == fee_record_id, FeeRecord.student_id.in_(owned_students or [-1])).one_or_none()
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fee record not found")

    previous_status = record.status
    if body.paid:
        record.amount_paid = record.amount_due
        record.status = "paid"
    else:
        record.amount_paid = 0.0
        record.status = "overdue" if record.due_date < date.today() else "pending"

    write_audit_log(
        db, actor_id=user.id, action="teacher_mark_fee_paid" if body.paid else "teacher_mark_fee_unpaid",
        entity_type="fee_records", entity_id=record.id,
        detail={"previous_status": previous_status, "new_status": record.status},
    )
    db.commit()
    db.refresh(record)

    return PaymentResponse(fee_record_id=record.id, amount_paid=record.amount_paid, amount_due=record.amount_due, status=record.status)
