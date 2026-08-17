import mimetypes
from datetime import date, datetime, timedelta, timezone
from datetime import date as date_

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.fees import (
    SETTLED_STATUSES,
    FeePaymentRequest,
    FeeRecord,
    FeeReminder,
    FeeSchedule,
    has_outstanding_balance,
)
from app.models.parent_student import ParentStudent
from app.models.school import School
from app.models.user import User
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.fee_payments import apply_payment_to_record, close_open_claim_if_paid, outstanding_balance
from app.services.fee_reminder_engine import REMINDER_TIERS, determine_reminder
from app.services.notify import dispatch_bulk, dispatch_notification
from app.services.supabase_admin import PAYMENT_PROOFS_BUCKET, download_file
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
    academic_year: str = Field(max_length=20)
    fee_type: str = Field(max_length=30)
    amount: float
    due_date: date

    # THE LENGTHS MIRROR THE COLUMNS, and they are here because their absence was a
    # live 500. fee_schedules.fee_type is String(30); a 31-character fee type reached
    # Postgres, raised StringDataRightTruncation, and surfaced as a bare
    # "Internal Server Error" with no field named and no message the UI could show -
    # so the create button just sat on "Creating…". Validating here returns a 422 that
    # names the field and states the limit.
    #
    # Worth generalising: any str field on a request model that maps to a String(n)
    # column needs its max_length, or the same 500 is one long paste away. These two
    # are the pair this endpoint writes.


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


def _reminder_scope_query(db: Session, school_id: int | None, *, class_id: int | None, overdue_only: bool):
    """The set of fee records a reminder run considers, shared by the preview and the
    trigger so the two can never disagree about what is in scope.

    Scoped to the caller's own school - same fix as GET /admin/fees/status and
    POST /admin/fees/records/{id}/payment, and the same bug class fixed in
    admissions.py/approvals.py/risk.py. FeeRecord has no school_id of its own (only
    student_id), so the scoping has to go through User. Without this, an admin from
    ANY school reminded EVERY school's overdue records - merely invisible while a
    reminder was a FeeReminder row nobody read, and a real cross-tenant leak the
    moment this started dispatching notifications to actual parents.
    """
    query = db.query(FeeRecord).join(User, FeeRecord.student_id == User.id).filter(User.school_id == school_id)
    if class_id is not None:
        # By ENROLLMENT, not by the schedule's own class - same fix and same reason as
        # GET /admin/fees/status. Matching FeeSchedule.class_id skipped every
        # school-wide fee (class_id NULL) that this class's students owe, so reminding
        # "just Grade 1-A" quietly reminded about a fraction of what they owed.
        query = query.filter(FeeRecord.student_id.in_(_students_in_classes(db, [class_id]) or [-1]))
    if overdue_only:
        # "Overdue" here means STILL OWED AND PAST DUE, not `status == "overdue"`.
        # Recording any payment flips a record to "partial", so the old status check
        # dropped a fee out of reminders the moment a parent paid part of it - 1 rupee
        # of 350 bought permanent silence. See models/fees.py::has_outstanding_balance.
        return query.filter(has_outstanding_balance(date.today()))
    # Widened scope additionally includes fees not yet past their due date, which the
    # day-tier gate then filters (see GET /admin/fees/reminders/preview's not_yet_due).
    return query.filter(
        ~FeeRecord.status.in_(SETTLED_STATUSES), FeeRecord.amount_paid < FeeRecord.amount_due
    )


# --- GET /admin/fees/reminders/preview -----------------------------------------------
# WHY THIS EXISTS: triggering reminders reported only "0 reminder(s) recorded as due",
# which is indistinguishable from a broken button. It sent an admin looking at ten red
# overdue cards and no reminders with nowhere to go. This answers "why zero" before you
# press anything, in the engine's own terms.


class ReminderBucketOut(BaseModel):
    cadence_reason: str
    severity: str
    count: int


class RemindersPreviewResponse(BaseModel):
    in_scope: int
    """Fee records matching the status filter, before the day-tier gate."""
    due_now: int
    """How many would actually log a reminder if triggered right now."""
    by_tier: list[ReminderBucketOut]
    """Which tiers those due_now records would fire, so "10 due" is legible as
    "10 first notices" rather than an unexplained number."""
    not_yet_due: int
    """due_date is today or later - can never produce a reminder, whatever the
    status filter says. This is what makes the "pending" scope option look like it
    should help when it can't."""
    waiting_for_next_tier: int
    """Overdue, has already had every tier it has reached - waiting to cross the
    next threshold."""
    fully_escalated: int
    """Has had all tiers including the last. Nothing further will ever fire."""
    next_due_date: date_ | None
    """The earliest date any in-scope record next becomes eligible, or null if none
    ever will. Turns "0 reminders" into "0 today, 10 on the 23rd"."""
    next_due_count: int


@router.get("/admin/fees/reminders/preview", response_model=RemindersPreviewResponse)
def preview_reminders(
    class_id: int | None = None,
    overdue_only: bool = True,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """Dry run: what triggering reminders with these filters would do, and why.

    Read-only - it writes no FeeReminder rows and dispatches no notifications. Uses
    the same scope query and the same determine_reminder() call as the POST, so the
    two can't drift into disagreeing about what is due.
    """
    today = date.today()
    query = _reminder_scope_query(db, user.school_id, class_id=class_id, overdue_only=overdue_only)
    records = query.all()

    reminders_by_record: dict[int, set[str]] = {}
    if records:
        for row in db.query(FeeReminder).filter(FeeReminder.fee_record_id.in_([r.id for r in records])):
            reminders_by_record.setdefault(row.fee_record_id, set()).add(row.cadence_reason)

    tier_severity = {reason: severity for _, severity, reason in REMINDER_TIERS}
    due_counts: dict[str, int] = {}
    not_yet_due = waiting = fully_escalated = 0
    # (date a record next becomes eligible) -> how many share that date.
    next_dates: dict[date_, int] = {}

    for record in records:
        days_overdue = (today - record.due_date).days
        already = reminders_by_record.get(record.id, set())
        decision = determine_reminder(days_overdue, already)

        if decision.should_send and decision.cadence_reason is not None:
            due_counts[decision.cadence_reason] = due_counts.get(decision.cadence_reason, 0) + 1
            continue

        if len(already) >= len(REMINDER_TIERS):
            fully_escalated += 1
            continue

        # Not due now: find the next threshold it hasn't already fired, and the date
        # it reaches it. Mirrors determine_reminder's own index guard so the two
        # never disagree about what "next" means.
        highest_sent = max(
            (i for i, (_, _, reason) in enumerate(REMINDER_TIERS) if reason in already), default=-1
        )
        upcoming = [
            threshold
            for i, (threshold, _, _) in enumerate(REMINDER_TIERS)
            if i > highest_sent and threshold > days_overdue
        ]
        if upcoming:
            eligible_on = record.due_date + timedelta(days=min(upcoming))
            next_dates[eligible_on] = next_dates.get(eligible_on, 0) + 1
        else:
            fully_escalated += 1
            continue

        if days_overdue <= 0:
            not_yet_due += 1
        else:
            waiting += 1

    next_due_date = min(next_dates) if next_dates else None
    return RemindersPreviewResponse(
        in_scope=len(records),
        due_now=sum(due_counts.values()),
        by_tier=[
            ReminderBucketOut(cadence_reason=reason, severity=tier_severity.get(reason, "normal"), count=count)
            for reason, count in sorted(due_counts.items(), key=lambda kv: -kv[1])
        ],
        not_yet_due=not_yet_due,
        waiting_for_next_tier=waiting,
        fully_escalated=fully_escalated,
        next_due_date=next_due_date,
        next_due_count=next_dates.get(next_due_date, 0) if next_due_date is not None else 0,
    )


@router.post("/admin/fees/reminders", response_model=RemindersResponse)
def trigger_reminders(
    body: RemindersRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    today = date.today()
    query = _reminder_scope_query(db, user.school_id, class_id=body.class_id, overdue_only=body.overdue_only)

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
                title=f"Fee payment {'overdue' if days_overdue > 0 else 'due'}",
                body=(
                    f"{record.fee_schedule.fee_type}: "
                    f"{record.amount_due - record.amount_paid:.2f} due {record.due_date.isoformat()}"
                    # A parent who has paid part of it needs to see that this is the
                    # REMAINDER, not the school having lost their payment.
                    + (
                        f" (remaining after {record.amount_paid:.2f} already paid)"
                        if record.amount_paid > 0
                        else ""
                    )
                ),
                # PRIORITY COMES FROM THE TIER, not from record.status. It used to be
                # `urgent if status == "overdue"`, which meant a part payment
                # downgraded a 30-days-late reminder to "normal" - the escalated tier
                # fired but arrived quietly, so the tier's own severity and the
                # notification disagreed. determine_reminder already decided how
                # serious this is; deferring to it keeps one answer.
                priority=decision.severity or "normal",
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


class StatusClaimOut(BaseModel):
    """The payment claim attached to a fee record, if any."""

    id: int
    status: str
    """pending | confirmed | rejected."""
    amount: float
    payment_method: str
    payment_reference: str
    submitted_at: datetime
    rejection_reason: str | None
    has_proof: bool


class StatusItemOut(BaseModel):
    student_id: int
    fee_record_id: int
    amount_due: float
    amount_paid: float
    outstanding: float
    due_date: date
    status: str
    fee_type: str
    """From the fee's FeeSchedule - without this, a student/parent sees "you owe
    ₹500 by 2026-09-20" with no way to tell tuition from an event fee."""
    claim: StatusClaimOut | None
    """The open payment claim against this fee, else the most recent closed one.

    WITHOUT THIS the admin's own fee list contradicted the parent's. `status` here
    is the canonical fee_records.status, which knows nothing about claims - so a
    fee a parent had already reported paying still read plainly "overdue", and an
    admin could send a reminder chasing a parent who was in fact waiting on the
    school to confirm. The parent's view (GET /parent/child/{id}/fees) surfaced
    `payment_pending`; this one didn't. Same row, two screens, two stories."""


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
        # class_id filters by WHO OWES - the students enrolled in that class - not by
        # which class the FeeSchedule was raised for.
        #
        # THIS CHANGED, and the previous behaviour was a real bug. It used to join
        # through FeeSchedule and match `FeeSchedule.class_id == class_id`, on the
        # reasoning that a fee raised for "Grade 8A" should stay filed under 8A even if
        # a student later transferred. But a SCHOOL-WIDE schedule has class_id NULL
        # while still generating a FeeRecord for every student in the school - so
        # picking "Grade 1 - A" returned only fees whose schedule was scoped to 1-A and
        # silently hid every school-wide fee those same 1-A students owed. An admin
        # filtering to a class to chase its unpaid fees saw a fraction of them.
        #
        # It also disagreed with the teacher branch immediately below, which has always
        # filtered by enrollment (_students_in_classes) - so "Grade 1 - A" meant two
        # different things depending on who asked. Enrollment is the right answer for
        # both: the question a class filter answers is "who in this room owes money".
        query = query.join(User, FeeRecord.student_id == User.id).filter(User.school_id == user.school_id)
        if class_id is not None:
            query = query.filter(FeeRecord.student_id.in_(_students_in_classes(db, [class_id]) or [-1]))
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

    records = query.order_by(FeeRecord.due_date.desc()).all()

    # One batched query for every record's claims rather than one per row - this
    # endpoint serves a whole school's fee list for an admin.
    claims_by_record: dict[int, list[FeePaymentRequest]] = {}
    if records:
        for claim in (
            db.query(FeePaymentRequest)
            .filter(FeePaymentRequest.fee_record_id.in_([r.id for r in records]))
            .order_by(FeePaymentRequest.submitted_at.desc(), FeePaymentRequest.id.desc())
        ):
            claims_by_record.setdefault(claim.fee_record_id, []).append(claim)

    def _claim_for(record_id: int) -> StatusClaimOut | None:
        history = claims_by_record.get(record_id, [])
        if not history:
            return None
        # The open one matters most; otherwise the latest, so a rejection stays visible.
        claim = next((c for c in history if c.status == "pending"), history[0])
        return StatusClaimOut(
            id=claim.id,
            status=claim.status,
            amount=claim.amount,
            payment_method=claim.payment_method,
            payment_reference=claim.payment_reference,
            submitted_at=claim.submitted_at,
            rejection_reason=claim.rejection_reason,
            has_proof=claim.proof_url is not None,
        )

    items = [
        StatusItemOut(
            student_id=r.student_id, fee_record_id=r.id, amount_due=r.amount_due, amount_paid=r.amount_paid,
            outstanding=outstanding_balance(r),
            due_date=r.due_date, status=r.status, fee_type=r.fee_schedule.fee_type,
            claim=_claim_for(r.id),
        )
        for r in records
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

    # The amount/status arithmetic and its audit row now live in
    # services/fee_payments.py, because PUT /admin/fee-payment-requests/{id}/confirm
    # performs the identical write when an admin confirms a parent's payment claim.
    # Behaviour here is unchanged - same audit action and detail keys as before.
    apply_payment_to_record(db, record, body.amount, actor_id=user.id)

    # If a parent had an open claim against this fee, paying it in full here closes
    # that claim too - otherwise it sits pending forever and the admin's pending
    # badge never returns to zero. The caller is already an admin/principal, so no
    # authority is granted that they didn't have; the audit row marks it indirect.
    closed = close_open_claim_if_paid(db, record, actor_id=user.id, via="record_payment")
    if closed is not None:
        dispatch_notification(
            db,
            user_id=closed.parent_id,
            source_type="fee_payment_confirmed",
            title="Payment confirmed",
            body=(
                f"Your reported payment of {closed.amount:.2f} (reference "
                f"{closed.payment_reference}) has been confirmed and this fee is now fully paid."
            ),
            priority="normal",
            source_id=closed.id,
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


# --- Fee payment confirmation loop: the admin half ------------------------------------
#
# The review side of the parent claim flow in routers/parent.py. A parent records
# "I paid this by UPI, reference X"; an admin checks it against the bank statement
# and confirms or rejects. Confirmation is the ONLY thing that writes to fee_records,
# and it does so through services/fee_payments.py::apply_payment_to_record - the same
# function POST /admin/fees/records/{id}/payment uses, so the amount/status
# derivation exists in exactly one place.
#
# THE TRUST MODEL: confirm and reject are require_role("admin", "principal"). A
# parent cannot confirm their own claim - if they could, the whole review step would
# be decorative and a parent could mark their own fees paid.
#
# SCOPING: fee_payment_requests has no school_id of its own, so every query below
# joins fee_records -> users to filter on the caller's school. Same bug class already
# fixed in this router's own trigger_reminders/record_payment/status endpoints, and in
# admissions.py, approvals.py and risk.py. Four routers carry comments about leaks
# they already fixed; this one is scoped from the start.


class PaymentRequestItemOut(BaseModel):
    id: int
    fee_record_id: int
    student_id: int
    student_name: str
    class_name: str | None
    parent_id: int
    parent_name: str
    fee_type: str
    amount: float
    """What the parent claims to have paid."""
    amount_due: float
    amount_paid: float
    outstanding: float
    payment_method: str
    payment_reference: str
    has_proof: bool
    status: str
    submitted_at: datetime
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None


class PaymentRequestQueueResponse(BaseModel):
    items: list[PaymentRequestItemOut]
    pending_count: int
    """The school's TOTAL pending count, ignoring the `status` filter - so the admin
    dashboard badge and a filtered queue view can share one request."""


class ConfirmPaymentRequestResponse(BaseModel):
    request: PaymentRequestItemOut
    fee_record: PaymentResponse


class RejectPaymentRequestBody(BaseModel):
    rejection_reason: str


def _payment_request_query(db: Session, school_id: int):
    """Every payment request in one school, with the rows needed to describe it.

    The join through User is the tenant boundary - see this section's header.
    """
    return (
        db.query(FeePaymentRequest, FeeRecord, FeeSchedule, User)
        .join(FeeRecord, FeePaymentRequest.fee_record_id == FeeRecord.id)
        .join(FeeSchedule, FeeRecord.fee_schedule_id == FeeSchedule.id)
        .join(User, FeePaymentRequest.student_id == User.id)
        .filter(User.school_id == school_id)
    )


def _request_item_out(
    db: Session,
    request: FeePaymentRequest,
    record: FeeRecord,
    schedule: FeeSchedule,
    student: User,
) -> PaymentRequestItemOut:
    parent = db.query(User).filter(User.id == request.parent_id).one_or_none()
    reviewer = (
        db.query(User).filter(User.id == request.reviewed_by).one_or_none()
        if request.reviewed_by is not None
        else None
    )
    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == student.id, Enrollment.is_primary.is_(True))
        .first()
    )
    school_class = (
        db.query(SchoolClass).filter(SchoolClass.id == enrollment.class_id).one_or_none()
        if enrollment is not None
        else None
    )
    return PaymentRequestItemOut(
        id=request.id,
        fee_record_id=request.fee_record_id,
        student_id=student.id,
        student_name=student.full_name or student.email,
        class_name=school_class.name if school_class else None,
        parent_id=request.parent_id,
        parent_name=(parent.full_name or parent.email) if parent else f"User #{request.parent_id}",
        fee_type=schedule.fee_type,
        amount=request.amount,
        amount_due=record.amount_due,
        amount_paid=record.amount_paid,
        outstanding=outstanding_balance(record),
        payment_method=request.payment_method,
        payment_reference=request.payment_reference,
        has_proof=request.proof_url is not None,
        status=request.status,
        submitted_at=request.submitted_at,
        reviewed_by_name=(reviewer.full_name or reviewer.email) if reviewer else None,
        reviewed_at=request.reviewed_at,
        rejection_reason=request.rejection_reason,
    )


def _load_request_for_review(db: Session, request_id: int, school_id: int):
    """Fetch a request the caller may act on, or 404.

    404 rather than 403 for another school's request: an admin probing ids must not
    be able to tell "exists, not yours" from "doesn't exist".
    """
    row = _payment_request_query(db, school_id).filter(FeePaymentRequest.id == request_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment request not found")
    return row


@router.get("/admin/fee-payment-requests", response_model=PaymentRequestQueueResponse)
def list_payment_requests(
    status_filter: str | None = Query(None, alias="status"),
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if user.school_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account is not linked to a school")
    if status_filter is not None and status_filter not in ("pending", "confirmed", "rejected"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "status must be one of pending, confirmed, rejected"
        )

    query = _payment_request_query(db, user.school_id)
    if status_filter is not None:
        query = query.filter(FeePaymentRequest.status == status_filter)

    rows = query.order_by(FeePaymentRequest.submitted_at.desc(), FeePaymentRequest.id.desc()).all()
    items = [_request_item_out(db, req, rec, sch, stu) for req, rec, sch, stu in rows]
    # Pending first, then newest - a queue is a work list, not a log.
    items.sort(key=lambda i: (i.status != "pending", -i.submitted_at.timestamp()))

    pending_count = (
        _payment_request_query(db, user.school_id)
        .filter(FeePaymentRequest.status == "pending")
        .count()
    )
    return PaymentRequestQueueResponse(items=items, pending_count=pending_count)


@router.get("/admin/fee-payment-requests/{request_id}/proof")
def get_payment_request_proof(
    request_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """Stream a stored proof back. Exists because proof_url is a path into a private
    bucket - there is no public URL for the admin UI to link to, deliberately."""
    if user.school_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account is not linked to a school")
    request, _record, _schedule, _student = _load_request_for_review(db, request_id, user.school_id)
    if request.proof_url is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This request has no proof attached")

    data = download_file(request.proof_url, bucket=PAYMENT_PROOFS_BUCKET)
    media_type = mimetypes.guess_type(request.proof_url)[0] or "application/octet-stream"
    return Response(content=data, media_type=media_type)


@router.put("/admin/fee-payment-requests/{request_id}/confirm", response_model=ConfirmPaymentRequestResponse)
def confirm_payment_request(
    request_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """Approve a parent's claim and write it through to the canonical fee record."""
    if user.school_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account is not linked to a school")
    request, record, schedule, student = _load_request_for_review(db, request_id, user.school_id)
    if request.status != "pending":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"This request has already been {request.status}"
        )

    request.status = "confirmed"
    request.reviewed_by = user.id
    request.reviewed_at = datetime.now(timezone.utc)

    # THE write-through. Same function POST /admin/fees/records/{id}/payment calls -
    # the amount/status derivation is not duplicated here.
    outcome = apply_payment_to_record(
        db,
        record,
        request.amount,
        actor_id=user.id,
        audit_detail_extra={"fee_payment_request_id": request.id, "payment_method": request.payment_method},
    )

    write_audit_log(
        db,
        actor_id=user.id,
        action="confirm_fee_payment_request",
        entity_type="fee_payment_requests",
        entity_id=request.id,
        detail={
            "fee_record_id": record.id,
            "amount": request.amount,
            "payment_method": request.payment_method,
            "payment_reference": request.payment_reference,
            "fee_record_status": outcome.status,
        },
    )

    dispatch_notification(
        db,
        user_id=request.parent_id,
        source_type="fee_payment_confirmed",
        title=f"Payment confirmed for {student.full_name or student.email}",
        body=(
            f"{schedule.fee_type}: {request.amount:.2f} confirmed against reference "
            f"{request.payment_reference}. "
            + (
                "This fee is now fully paid."
                if outcome.status == "paid"
                else f"Remaining balance: {outstanding_balance(record):.2f}."
            )
        ),
        priority="normal",
        source_id=request.id,
    )

    db.commit()
    db.refresh(request)
    db.refresh(record)

    return ConfirmPaymentRequestResponse(
        request=_request_item_out(db, request, record, schedule, student),
        fee_record=PaymentResponse(
            fee_record_id=record.id,
            amount_paid=record.amount_paid,
            amount_due=record.amount_due,
            status=record.status,
        ),
    )


@router.put("/admin/fee-payment-requests/{request_id}/reject", response_model=PaymentRequestItemOut)
def reject_payment_request(
    request_id: int,
    body: RejectPaymentRequestBody,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """Decline a claim. The fee record is deliberately NOT touched, so it stays
    overdue and keeps attracting reminders - and the parent can submit a fresh
    request, which the PARTIAL uniqueness index is what permits."""
    if user.school_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account is not linked to a school")
    reason = body.rejection_reason.strip()
    if not reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "rejection_reason is required")

    request, record, schedule, student = _load_request_for_review(db, request_id, user.school_id)
    if request.status != "pending":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"This request has already been {request.status}"
        )

    request.status = "rejected"
    request.reviewed_by = user.id
    request.reviewed_at = datetime.now(timezone.utc)
    request.rejection_reason = reason

    write_audit_log(
        db,
        actor_id=user.id,
        action="reject_fee_payment_request",
        entity_type="fee_payment_requests",
        entity_id=request.id,
        detail={
            "fee_record_id": record.id,
            "amount": request.amount,
            "payment_reference": request.payment_reference,
            "rejection_reason": reason,
        },
    )

    dispatch_notification(
        db,
        user_id=request.parent_id,
        source_type="fee_payment_rejected",
        title=f"Payment could not be confirmed for {student.full_name or student.email}",
        body=(
            f"{schedule.fee_type}: the school could not confirm {request.amount:.2f} against "
            f"reference {request.payment_reference}. Reason: {reason}. "
            "You can submit a corrected payment request from the fees page."
        ),
        priority="important",
        source_id=request.id,
    )

    db.commit()
    db.refresh(request)
    return _request_item_out(db, request, record, schedule, student)
