from datetime import date as date_
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.role import Role
from app.models.staffing import LeaveRequest, StaffingForecast, Substitution
from app.models.subject import Subject
from app.models.timetable import TeacherSubject, TeacherUnavailability, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.staffing_forecast import HistoricalGapObservation, forecast_staffing_gaps
from app.services.substitute_solver import SubstituteCandidate, SubstituteSuggestion, find_substitutes

router = APIRouter(tags=["staffing"])


# --- shared helpers -----------------------------------------------------------


def _distinct_slots_for_leave(
    db: Session, teacher_id: int, start_date: date_, end_date: date_, academic_year: str
) -> list[TimetableSlot]:
    """Every distinct recurring weekly slot the teacher has on any weekday touched
    by [start_date, end_date] - one row per slot, not one per calendar occurrence
    (see Substitution's docstring for why)."""
    if (end_date - start_date).days >= 6:
        weekdays_touched = set(range(7))
    else:
        weekdays_touched = set()
        current = start_date
        while current <= end_date:
            weekdays_touched.add(current.weekday())
            current += timedelta(days=1)

    return (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.teacher_id == teacher_id,
            TimetableSlot.day_of_week.in_(weekdays_touched),
            TimetableSlot.academic_year == academic_year,
            TimetableSlot.is_active.is_(True),
        )
        .all()
    )


def _build_substitute_candidates(
    db: Session,
    *,
    subject_id: int,
    day_of_week: int,
    period_number: int,
    academic_year: str,
    exclude_teacher_id: int,
    leave_start: date_,
    leave_end: date_,
) -> list[SubstituteCandidate]:
    qualified_teacher_ids = {
        row.teacher_id
        for row in db.query(TeacherSubject.teacher_id).filter(TeacherSubject.subject_id == subject_id)
        if row.teacher_id != exclude_teacher_id
    }
    if not qualified_teacher_ids:
        return []

    busy_teacher_ids = {
        row.teacher_id
        for row in db.query(TimetableSlot.teacher_id).filter(
            TimetableSlot.teacher_id.in_(qualified_teacher_ids),
            TimetableSlot.day_of_week == day_of_week,
            TimetableSlot.period_number == period_number,
            TimetableSlot.academic_year == academic_year,
            TimetableSlot.is_active.is_(True),
        )
    }
    unavailable_teacher_ids = {
        row.teacher_id
        for row in db.query(TeacherUnavailability.teacher_id).filter(
            TeacherUnavailability.teacher_id.in_(qualified_teacher_ids),
            TeacherUnavailability.day_of_week == day_of_week,
            TeacherUnavailability.period_number == period_number,
            TeacherUnavailability.academic_year == academic_year,
        )
    }
    on_leave_teacher_ids = {
        row.teacher_id
        for row in db.query(LeaveRequest.teacher_id).filter(
            LeaveRequest.teacher_id.in_(qualified_teacher_ids),
            LeaveRequest.status == "approved",
            LeaveRequest.start_date <= leave_end,
            LeaveRequest.end_date >= leave_start,
        )
    }
    workload_by_teacher = dict(
        db.query(TimetableSlot.teacher_id, func.count(TimetableSlot.id))
        .filter(
            TimetableSlot.teacher_id.in_(qualified_teacher_ids),
            TimetableSlot.academic_year == academic_year,
            TimetableSlot.is_active.is_(True),
        )
        .group_by(TimetableSlot.teacher_id)
        .all()
    )

    return [
        SubstituteCandidate(
            teacher_id=teacher_id,
            qualified_subject_ids=frozenset({subject_id}),
            already_busy=teacher_id in busy_teacher_ids,
            unavailable=teacher_id in unavailable_teacher_ids,
            on_leave=teacher_id in on_leave_teacher_ids,
            current_workload=workload_by_teacher.get(teacher_id, 0),
        )
        for teacher_id in qualified_teacher_ids
    ]


class CandidateOut(BaseModel):
    teacher_id: int
    score: float
    reason: str


class SubstitutionOut(BaseModel):
    id: int | None
    """Null when this is a preview (no leave_request_id to attach to) - nothing persisted."""
    leave_request_id: int | None
    timetable_slot_id: int
    original_teacher_id: int
    substitute_teacher_id: int | None
    status: str | None
    suggested_score: float | None
    confirmed_at: datetime | None
    subject_id: int
    class_id: int
    day_of_week: int
    period_number: int
    candidates: list[CandidateOut]
    """Full ranked list the top pick was drawn from, so an admin can override with an alternative."""


def _substitution_out(
    slot: TimetableSlot,
    suggestions: list[SubstituteSuggestion],
    *,
    sub: Substitution | None = None,
    leave_request_id: int | None = None,
    original_teacher_id: int | None = None,
) -> SubstitutionOut:
    top = suggestions[0] if suggestions else None
    return SubstitutionOut(
        id=sub.id if sub else None,
        leave_request_id=sub.leave_request_id if sub else leave_request_id,
        timetable_slot_id=slot.id,
        original_teacher_id=sub.original_teacher_id if sub else original_teacher_id,
        substitute_teacher_id=sub.substitute_teacher_id if sub else (top.teacher_id if top else None),
        status=sub.status if sub else None,
        suggested_score=sub.suggested_score if sub else (top.score if top else None),
        confirmed_at=sub.confirmed_at if sub else None,
        subject_id=slot.subject_id,
        class_id=slot.class_id,
        day_of_week=slot.day_of_week,
        period_number=slot.period_number,
        candidates=[CandidateOut(teacher_id=s.teacher_id, score=s.score, reason=s.reason) for s in suggestions],
    )


# --- POST /staff/request_leave -------------------------------------------------


class LeaveRequestCreate(BaseModel):
    teacher_id: int | None = None
    """Required (and used) when an admin/principal files on behalf of a teacher; ignored for the teacher role, who can only file for themselves."""
    start_date: date_
    end_date: date_
    reason: str


class LeaveRequestOut(BaseModel):
    id: int
    teacher_id: int
    start_date: date_
    end_date: date_
    reason: str
    status: str
    requested_at: datetime
    decided_by: int | None
    decided_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


@router.post("/staff/request_leave", response_model=LeaveRequestOut)
def request_leave(
    body: LeaveRequestCreate,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    if user.role == "teacher":
        teacher_id = user.id
    else:
        if body.teacher_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "teacher_id is required when filing on behalf of a teacher")
        teacher_id = body.teacher_id

    if body.end_date < body.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_date must be on or after start_date")

    leave = LeaveRequest(
        teacher_id=teacher_id, start_date=body.start_date, end_date=body.end_date, reason=body.reason, status="pending"
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return LeaveRequestOut.model_validate(leave)


# --- PUT /staff/approve_leave ---------------------------------------------------


class ApproveLeaveRequest(BaseModel):
    leave_request_id: int
    decision: str
    """"approved" or "rejected"."""
    academic_year: str | None = None
    """Required when decision == "approved" - needed to resolve which timetable slots are affected."""


class ApproveLeaveResponse(BaseModel):
    leave_request: LeaveRequestOut
    substitutions: list[SubstitutionOut]


@router.put("/staff/approve_leave", response_model=ApproveLeaveResponse)
def approve_leave(
    body: ApproveLeaveRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "decision must be 'approved' or 'rejected'")

    leave = db.query(LeaveRequest).filter(LeaveRequest.id == body.leave_request_id).one_or_none()
    if leave is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found")

    leave.status = body.decision
    leave.decided_by = user.id
    leave.decided_at = datetime.now(timezone.utc)

    substitutions_out: list[SubstitutionOut] = []
    if body.decision == "approved":
        if not body.academic_year:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "academic_year is required to resolve affected timetable slots"
            )

        slots = _distinct_slots_for_leave(db, leave.teacher_id, leave.start_date, leave.end_date, body.academic_year)
        for slot in slots:
            candidates = _build_substitute_candidates(
                db,
                subject_id=slot.subject_id,
                day_of_week=slot.day_of_week,
                period_number=slot.period_number,
                academic_year=body.academic_year,
                exclude_teacher_id=leave.teacher_id,
                leave_start=leave.start_date,
                leave_end=leave.end_date,
            )
            suggestions = find_substitutes(
                subject_id=slot.subject_id, original_teacher_id=leave.teacher_id, candidates=candidates
            )
            top = suggestions[0] if suggestions else None

            sub = (
                db.query(Substitution)
                .filter(Substitution.leave_request_id == leave.id, Substitution.timetable_slot_id == slot.id)
                .one_or_none()
            )
            if sub is None:
                sub = Substitution(
                    leave_request_id=leave.id,
                    timetable_slot_id=slot.id,
                    original_teacher_id=leave.teacher_id,
                    substitute_teacher_id=top.teacher_id if top else None,
                    status="suggested",
                    suggested_score=top.score if top else None,
                )
                db.add(sub)
                db.flush()
            else:
                sub.substitute_teacher_id = top.teacher_id if top else None
                sub.suggested_score = top.score if top else None
                sub.status = "suggested"

            substitutions_out.append(_substitution_out(slot, suggestions, sub=sub))

    db.commit()
    db.refresh(leave)

    return ApproveLeaveResponse(leave_request=LeaveRequestOut.model_validate(leave), substitutions=substitutions_out)


# --- POST /substitution/suggest -------------------------------------------------


class SuggestRequest(BaseModel):
    leave_request_id: int | None = None
    """Mode A: re-run the solver for every Substitution already tied to this leave and persist the refreshed suggestions."""
    teacher_id: int | None = None
    start_date: date_ | None = None
    end_date: date_ | None = None
    academic_year: str | None = None
    """Mode B (all four of teacher_id/start_date/end_date/academic_year, no leave_request_id): preview suggestions for a hypothetical date range with nothing persisted - no leave request exists yet to attach rows to."""


class SuggestResponse(BaseModel):
    substitutions: list[SubstitutionOut]


@router.post("/substitution/suggest", response_model=SuggestResponse)
def suggest_substitutions(
    body: SuggestRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if body.leave_request_id is not None:
        if not body.academic_year:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "academic_year is required")
        leave = db.query(LeaveRequest).filter(LeaveRequest.id == body.leave_request_id).one_or_none()
        if leave is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found")

        results = []
        for sub in db.query(Substitution).filter(Substitution.leave_request_id == leave.id).all():
            slot = db.query(TimetableSlot).filter(TimetableSlot.id == sub.timetable_slot_id).one()
            candidates = _build_substitute_candidates(
                db,
                subject_id=slot.subject_id,
                day_of_week=slot.day_of_week,
                period_number=slot.period_number,
                academic_year=body.academic_year,
                exclude_teacher_id=leave.teacher_id,
                leave_start=leave.start_date,
                leave_end=leave.end_date,
            )
            suggestions = find_substitutes(
                subject_id=slot.subject_id, original_teacher_id=leave.teacher_id, candidates=candidates
            )
            top = suggestions[0] if suggestions else None
            sub.substitute_teacher_id = top.teacher_id if top else None
            sub.suggested_score = top.score if top else None
            results.append(_substitution_out(slot, suggestions, sub=sub))

        db.commit()
        return SuggestResponse(substitutions=results)

    if body.teacher_id is None or body.start_date is None or body.end_date is None or body.academic_year is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Either leave_request_id, or teacher_id+start_date+end_date+academic_year, is required",
        )

    slots = _distinct_slots_for_leave(db, body.teacher_id, body.start_date, body.end_date, body.academic_year)
    results = []
    for slot in slots:
        candidates = _build_substitute_candidates(
            db,
            subject_id=slot.subject_id,
            day_of_week=slot.day_of_week,
            period_number=slot.period_number,
            academic_year=body.academic_year,
            exclude_teacher_id=body.teacher_id,
            leave_start=body.start_date,
            leave_end=body.end_date,
        )
        suggestions = find_substitutes(subject_id=slot.subject_id, original_teacher_id=body.teacher_id, candidates=candidates)
        results.append(_substitution_out(slot, suggestions, original_teacher_id=body.teacher_id))

    return SuggestResponse(substitutions=results)


# --- PUT /substitution/{id}/confirm ---------------------------------------------


class ConfirmRequest(BaseModel):
    substitute_teacher_id: int | None = None
    """Omit to confirm the currently-suggested substitute; provide to override with a different teacher."""


class ConflictOut(BaseModel):
    type: str
    """One of: not_qualified, already_busy, unavailable, on_leave, is_original_teacher."""
    message: str


class ConfirmResponse(BaseModel):
    substitution: SubstitutionOut | None
    conflicts: list[ConflictOut]
    # Alert-ready detail for the (not-yet-built) notification system - see module
    # docstring / summary note. Populated only when substitution is not null.
    class_id: int | None = None
    class_name: str | None = None
    subject_name: str | None = None
    original_teacher_name: str | None = None
    substitute_teacher_name: str | None = None
    affected_student_ids: list[int] = []
    leave_start_date: date_ | None = None
    leave_end_date: date_ | None = None


def _check_confirm_conflicts(
    db: Session, *, slot: TimetableSlot, leave: LeaveRequest, target_teacher_id: int
) -> list[ConflictOut]:
    conflicts: list[ConflictOut] = []

    if target_teacher_id == leave.teacher_id:
        conflicts.append(ConflictOut(type="is_original_teacher", message="Cannot substitute the absent teacher for themselves"))

    qualified = (
        db.query(TeacherSubject)
        .filter(TeacherSubject.teacher_id == target_teacher_id, TeacherSubject.subject_id == slot.subject_id)
        .one_or_none()
    )
    if qualified is None:
        conflicts.append(ConflictOut(type="not_qualified", message="Teacher is not qualified for this subject"))

    busy = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.teacher_id == target_teacher_id,
            TimetableSlot.day_of_week == slot.day_of_week,
            TimetableSlot.period_number == slot.period_number,
            TimetableSlot.academic_year == slot.academic_year,
            TimetableSlot.is_active.is_(True),
        )
        .first()
    )
    if busy is not None:
        conflicts.append(ConflictOut(type="already_busy", message="Teacher already has a class at this day/period"))

    unavailable = (
        db.query(TeacherUnavailability)
        .filter(
            TeacherUnavailability.teacher_id == target_teacher_id,
            TeacherUnavailability.day_of_week == slot.day_of_week,
            TeacherUnavailability.period_number == slot.period_number,
            TeacherUnavailability.academic_year == slot.academic_year,
        )
        .first()
    )
    if unavailable is not None:
        conflicts.append(ConflictOut(type="unavailable", message="Teacher has marked themselves unavailable for this day/period"))

    on_leave = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.teacher_id == target_teacher_id,
            LeaveRequest.status == "approved",
            LeaveRequest.start_date <= leave.end_date,
            LeaveRequest.end_date >= leave.start_date,
        )
        .first()
    )
    if on_leave is not None:
        conflicts.append(ConflictOut(type="on_leave", message="Teacher is themselves on approved leave during this period"))

    return conflicts


@router.put("/substitution/{substitution_id}/confirm", response_model=ConfirmResponse)
def confirm_substitution(
    substitution_id: int,
    body: ConfirmRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    sub = db.query(Substitution).filter(Substitution.id == substitution_id).one_or_none()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Substitution not found")

    slot = db.query(TimetableSlot).filter(TimetableSlot.id == sub.timetable_slot_id).one()
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == sub.leave_request_id).one()

    target_teacher_id = body.substitute_teacher_id if body.substitute_teacher_id is not None else sub.substitute_teacher_id
    if target_teacher_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No substitute_teacher_id given and none currently suggested")

    conflicts = _check_confirm_conflicts(db, slot=slot, leave=leave, target_teacher_id=target_teacher_id)
    if conflicts:
        return ConfirmResponse(substitution=None, conflicts=conflicts)

    sub.substitute_teacher_id = target_teacher_id
    sub.status = "confirmed"
    sub.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sub)

    subject = db.query(Subject).filter(Subject.id == slot.subject_id).one()
    school_class = db.query(SchoolClass).filter(SchoolClass.id == slot.class_id).one()
    original_teacher = db.query(User).filter(User.id == sub.original_teacher_id).one()
    substitute_teacher = db.query(User).filter(User.id == sub.substitute_teacher_id).one()
    affected_student_ids = [
        row.student_id
        for row in db.query(Enrollment.student_id).filter(
            Enrollment.class_id == slot.class_id, Enrollment.is_primary.is_(True)
        )
    ]

    return ConfirmResponse(
        substitution=_substitution_out(slot, [], sub=sub),
        conflicts=[],
        class_id=school_class.id,
        class_name=school_class.name,
        subject_name=subject.name,
        original_teacher_name=original_teacher.full_name,
        substitute_teacher_name=substitute_teacher.full_name,
        affected_student_ids=affected_student_ids,
        leave_start_date=leave.start_date,
        leave_end_date=leave.end_date,
    )


# --- GET /staff/leave_requests --------------------------------------------------


@router.get("/staff/leave_requests", response_model=list[LeaveRequestOut])
def list_leave_requests(
    status_filter: str | None = Query(None, alias="status"),
    teacher_id: int | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(LeaveRequest)

    if user.role in ("admin", "principal"):
        if teacher_id is not None:
            query = query.filter(LeaveRequest.teacher_id == teacher_id)
    elif user.role == "teacher":
        query = query.filter(LeaveRequest.teacher_id == user.id)
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view leave requests")

    if status_filter is not None:
        query = query.filter(LeaveRequest.status == status_filter)

    return [LeaveRequestOut.model_validate(r) for r in query.order_by(LeaveRequest.requested_at.desc()).all()]


# --- GET /admin/staffing/forecast -----------------------------------------------


class ForecastDayOut(BaseModel):
    date: date_
    predicted_absences: float
    risk_level: str


class ForecastResponse(BaseModel):
    school_id: int
    week_start: date_
    forecast: list[ForecastDayOut]


@router.get("/admin/staffing/forecast", response_model=ForecastResponse)
def get_staffing_forecast(
    school_id: int,
    week_start: date_,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    forecast_dates = [week_start + timedelta(days=i) for i in range(7)]

    teacher_role_id = db.query(Role.id).filter(Role.name == "teacher").scalar_subquery()
    teacher_ids = [row.id for row in db.query(User.id).filter(User.school_id == school_id, User.role_id == teacher_role_id)]
    total_teacher_count = len(teacher_ids)

    history_rows = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.teacher_id.in_(teacher_ids or [-1]),
            LeaveRequest.status == "approved",
            LeaveRequest.start_date < week_start,
        )
        .all()
        if teacher_ids
        else []
    )

    gap_counts: dict[date_, int] = {}
    for leave in history_rows:
        d = max(leave.start_date, week_start - timedelta(days=90))  # cap lookback window, demo-scale dataset only
        while d <= leave.end_date and d < week_start:
            gap_counts[d] = gap_counts.get(d, 0) + 1
            d += timedelta(days=1)
    history = [HistoricalGapObservation(date=d, gap_count=c) for d, c in gap_counts.items()]

    daily_forecasts = forecast_staffing_gaps(history, forecast_dates, total_teacher_count)

    forecast_out = []
    for f in daily_forecasts:
        row = (
            db.query(StaffingForecast)
            .filter(StaffingForecast.school_id == school_id, StaffingForecast.date == f.date)
            .one_or_none()
        )
        if row is None:
            db.add(
                StaffingForecast(
                    school_id=school_id, date=f.date, predicted_gap_count=f.predicted_gap_count, risk_level=f.risk_level
                )
            )
        else:
            row.predicted_gap_count = f.predicted_gap_count
            row.risk_level = f.risk_level
        forecast_out.append(ForecastDayOut(date=f.date, predicted_absences=f.predicted_gap_count, risk_level=f.risk_level))

    db.commit()
    return ForecastResponse(school_id=school_id, week_start=week_start, forecast=forecast_out)


# --- GET /admin/staffing/substitute-suggestions ---------------------------------


class SlotSuggestionOut(BaseModel):
    timetable_slot_id: int
    subject_id: int
    class_id: int
    period_number: int
    suggestions: list[CandidateOut]


class SubstituteSuggestionsResponse(BaseModel):
    absent_teacher_id: int
    date: date_
    slots: list[SlotSuggestionOut]


@router.get("/admin/staffing/substitute-suggestions", response_model=SubstituteSuggestionsResponse)
def get_substitute_suggestions(
    teacher_id: int,
    date: date_,
    academic_year: str,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    day_of_week = date.weekday()
    slots = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.teacher_id == teacher_id,
            TimetableSlot.day_of_week == day_of_week,
            TimetableSlot.academic_year == academic_year,
            TimetableSlot.is_active.is_(True),
        )
        .all()
    )

    slot_outs = []
    for slot in slots:
        candidates = _build_substitute_candidates(
            db,
            subject_id=slot.subject_id,
            day_of_week=slot.day_of_week,
            period_number=slot.period_number,
            academic_year=academic_year,
            exclude_teacher_id=teacher_id,
            leave_start=date,
            leave_end=date,
        )
        suggestions = find_substitutes(subject_id=slot.subject_id, original_teacher_id=teacher_id, candidates=candidates)
        slot_outs.append(
            SlotSuggestionOut(
                timetable_slot_id=slot.id,
                subject_id=slot.subject_id,
                class_id=slot.class_id,
                period_number=slot.period_number,
                suggestions=[CandidateOut(teacher_id=s.teacher_id, score=s.score, reason=s.reason) for s in suggestions],
            )
        )

    return SubstituteSuggestionsResponse(absent_teacher_id=teacher_id, date=date, slots=slot_outs)
