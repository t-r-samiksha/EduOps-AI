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
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.staffing_forecast import HistoricalGapObservation, forecast_staffing_gaps, has_sufficient_data
from app.services.substitute_solver import SubstituteCandidate, SubstituteSuggestion, find_fallback_substitutes, find_substitutes

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


def _teachers_confirmed_substitutes_at(
    db: Session,
    *,
    day_of_week: int,
    period_number: int,
    academic_year: str,
    exclude_substitution_id: int | None = None,
) -> set[int]:
    """Teachers already CONFIRMED (Substitution.status == "confirmed") to cover a
    DIFFERENT class at this exact day/period/academic_year - the check that was
    missing everywhere (see substitute_solver.py's module docstring for the real
    double-booking this closes): a teacher confirmed as substitute for one class
    at a given day/period has nothing on their own real TimetableSlot at that
    time, so the pre-existing `already_busy` check (which only looks at
    TimetableSlot) never caught them being newly unavailable. `exclude_substitution_id`
    excludes a substitution's own row so re-evaluating candidates/conflicts for
    THAT row doesn't see its own already-confirmed substitute as "someone else
    already there"."""
    query = (
        db.query(Substitution.substitute_teacher_id)
        .join(TimetableSlot, Substitution.timetable_slot_id == TimetableSlot.id)
        .filter(
            Substitution.status == "confirmed",
            Substitution.substitute_teacher_id.isnot(None),
            TimetableSlot.day_of_week == day_of_week,
            TimetableSlot.period_number == period_number,
            TimetableSlot.academic_year == academic_year,
        )
    )
    if exclude_substitution_id is not None:
        query = query.filter(Substitution.id != exclude_substitution_id)
    return {row.substitute_teacher_id for row in query}


def _candidates_for_pool(
    db: Session,
    *,
    teacher_pool_ids: set[int],
    qualified_subject_ids: frozenset[int],
    day_of_week: int,
    period_number: int,
    academic_year: str,
    leave_start: date_,
    leave_end: date_,
    exclude_substitution_id: int | None,
) -> list[SubstituteCandidate]:
    """Shared busy/unavailable/on_leave/already_substituting/workload computation
    for any pool of teacher ids - used both for the real qualified-candidate pool
    (_build_substitute_candidates) and the broader "everyone in the school"
    fallback pool (_build_fallback_candidates), so "available" means the same
    thing in both places."""
    if not teacher_pool_ids:
        return []

    busy_teacher_ids = {
        row.teacher_id
        for row in db.query(TimetableSlot.teacher_id).filter(
            TimetableSlot.teacher_id.in_(teacher_pool_ids),
            TimetableSlot.day_of_week == day_of_week,
            TimetableSlot.period_number == period_number,
            TimetableSlot.academic_year == academic_year,
            TimetableSlot.is_active.is_(True),
        )
    }
    already_substituting_teacher_ids = _teachers_confirmed_substitutes_at(
        db,
        day_of_week=day_of_week,
        period_number=period_number,
        academic_year=academic_year,
        exclude_substitution_id=exclude_substitution_id,
    )
    unavailable_teacher_ids = {
        row.teacher_id
        for row in db.query(TeacherUnavailability.teacher_id).filter(
            TeacherUnavailability.teacher_id.in_(teacher_pool_ids),
            TeacherUnavailability.day_of_week == day_of_week,
            TeacherUnavailability.period_number == period_number,
            TeacherUnavailability.academic_year == academic_year,
        )
    }
    on_leave_teacher_ids = {
        row.teacher_id
        for row in db.query(LeaveRequest.teacher_id).filter(
            LeaveRequest.teacher_id.in_(teacher_pool_ids),
            LeaveRequest.status == "approved",
            LeaveRequest.start_date <= leave_end,
            LeaveRequest.end_date >= leave_start,
        )
    }
    workload_by_teacher = dict(
        db.query(TimetableSlot.teacher_id, func.count(TimetableSlot.id))
        .filter(
            TimetableSlot.teacher_id.in_(teacher_pool_ids),
            TimetableSlot.academic_year == academic_year,
            TimetableSlot.is_active.is_(True),
        )
        .group_by(TimetableSlot.teacher_id)
        .all()
    )

    return [
        SubstituteCandidate(
            teacher_id=teacher_id,
            qualified_subject_ids=qualified_subject_ids,
            already_busy=teacher_id in busy_teacher_ids,
            unavailable=teacher_id in unavailable_teacher_ids,
            on_leave=teacher_id in on_leave_teacher_ids,
            current_workload=workload_by_teacher.get(teacher_id, 0),
            already_substituting=teacher_id in already_substituting_teacher_ids,
        )
        for teacher_id in teacher_pool_ids
    ]


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
    exclude_substitution_id: int | None = None,
) -> list[SubstituteCandidate]:
    qualified_teacher_ids = {
        row.teacher_id
        for row in db.query(TeacherSubject.teacher_id).filter(TeacherSubject.subject_id == subject_id)
        if row.teacher_id != exclude_teacher_id
    }
    return _candidates_for_pool(
        db,
        teacher_pool_ids=qualified_teacher_ids,
        qualified_subject_ids=frozenset({subject_id}),
        day_of_week=day_of_week,
        period_number=period_number,
        academic_year=academic_year,
        leave_start=leave_start,
        leave_end=leave_end,
        exclude_substitution_id=exclude_substitution_id,
    )


def _build_fallback_candidates(
    db: Session,
    *,
    school_id: int | None,
    day_of_week: int,
    period_number: int,
    academic_year: str,
    exclude_teacher_id: int,
    leave_start: date_,
    leave_end: date_,
    exclude_substitution_id: int | None = None,
) -> list[SubstituteCandidate]:
    """The real-world escalation when NO qualified candidate exists at all
    (find_substitutes() returned nothing): every OTHER teacher in the school,
    regardless of subject qualification - a genuine "put anyone free in the room
    for supervision" pool. Only called as a fallback (see decide_leave_request/
    suggest_substitutions/get_substitute_suggestions), never instead of the real
    qualified pool. qualified_subject_ids is deliberately left empty for every
    candidate here - find_fallback_substitutes() never checks it, unlike
    find_substitutes()."""
    if school_id is None:
        return []
    teacher_role_id = db.query(Role.id).filter(Role.name == "teacher").scalar_subquery()
    school_teacher_ids = {
        row.id
        for row in db.query(User.id).filter(User.school_id == school_id, User.role_id == teacher_role_id)
        if row.id != exclude_teacher_id
    }
    return _candidates_for_pool(
        db,
        teacher_pool_ids=school_teacher_ids,
        qualified_subject_ids=frozenset(),
        day_of_week=day_of_week,
        period_number=period_number,
        academic_year=academic_year,
        leave_start=leave_start,
        leave_end=leave_end,
        exclude_substitution_id=exclude_substitution_id,
    )


def _school_id_for_teacher(db: Session, teacher_id: int) -> int | None:
    return db.query(User.school_id).filter(User.id == teacher_id).scalar()


def _find_substitutes_with_fallback(
    db: Session,
    *,
    subject_id: int,
    day_of_week: int,
    period_number: int,
    academic_year: str,
    exclude_teacher_id: int,
    leave_start: date_,
    leave_end: date_,
    exclude_substitution_id: int | None = None,
) -> list[SubstituteSuggestion]:
    """The real suggestion pipeline for one slot: try the qualified pool first;
    only when that's genuinely empty, automatically surface the broader
    "everyone free, regardless of subject" fallback tier (each one flagged
    qualified=False) instead of leaving the admin with nothing but a raw manual
    teacher picker. The raw picker (routers stay silent here; see
    frontend's StaffingPage) is the true last resort - only reached when even
    THIS fallback tier comes back empty."""
    candidates = _build_substitute_candidates(
        db,
        subject_id=subject_id,
        day_of_week=day_of_week,
        period_number=period_number,
        academic_year=academic_year,
        exclude_teacher_id=exclude_teacher_id,
        leave_start=leave_start,
        leave_end=leave_end,
        exclude_substitution_id=exclude_substitution_id,
    )
    suggestions = find_substitutes(subject_id=subject_id, original_teacher_id=exclude_teacher_id, candidates=candidates)
    if suggestions:
        return suggestions

    fallback_candidates = _build_fallback_candidates(
        db,
        school_id=_school_id_for_teacher(db, exclude_teacher_id),
        day_of_week=day_of_week,
        period_number=period_number,
        academic_year=academic_year,
        exclude_teacher_id=exclude_teacher_id,
        leave_start=leave_start,
        leave_end=leave_end,
        exclude_substitution_id=exclude_substitution_id,
    )
    return find_fallback_substitutes(original_teacher_id=exclude_teacher_id, candidates=fallback_candidates)


class CandidateOut(BaseModel):
    teacher_id: int
    score: float
    reason: str
    qualified: bool = True
    """False only for fallback suggestions (see find_fallback_substitutes) -
    real teachers surfaced automatically when nobody qualified was available,
    for supervision-only cover. The frontend renders these with an explicit
    warning; confirming one still goes through the same not_qualified conflict
    check as any manually-picked unqualified teacher."""


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
        candidates=[
            CandidateOut(teacher_id=s.teacher_id, score=s.score, reason=s.reason, qualified=s.qualified) for s in suggestions
        ],
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
        teacher = (
            db.query(User).join(Role, User.role_id == Role.id).filter(User.id == body.teacher_id, Role.name == "teacher").one_or_none()
        )
        if teacher is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")
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


def decide_leave_request(
    db: Session, leave: LeaveRequest, decision: str, actor_id: int, academic_year: str | None
) -> list[SubstitutionOut]:
    """Applies an approve/reject decision to a LeaveRequest, including the
    substitute-finding side effect on approval. `decision` must already be
    "approved"/"rejected" (callers own their own input-vocabulary validation - see
    PUT /staff/approve_leave and POST /admin/approvals/{id}/decision, which accept
    different wording but both normalize to this before calling in).

    Shared by both of those endpoints so they produce IDENTICAL behavior -
    approving a leave through the unified approvals inbox must run the same
    substitute-matching PUT /staff/approve_leave always did, not a stripped-down
    parallel version that silently skips it. Does not commit or write an audit
    entry - callers do both, since they need the caller-specific action verb."""
    leave.status = decision
    leave.decided_by = actor_id
    leave.decided_at = datetime.now(timezone.utc)

    substitutions_out: list[SubstitutionOut] = []
    if decision == "approved":
        if not academic_year:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "academic_year is required to resolve affected timetable slots"
            )

        slots = _distinct_slots_for_leave(db, leave.teacher_id, leave.start_date, leave.end_date, academic_year)
        for slot in slots:
            existing_sub = (
                db.query(Substitution)
                .filter(Substitution.leave_request_id == leave.id, Substitution.timetable_slot_id == slot.id)
                .one_or_none()
            )
            suggestions = _find_substitutes_with_fallback(
                db,
                subject_id=slot.subject_id,
                day_of_week=slot.day_of_week,
                period_number=slot.period_number,
                academic_year=academic_year,
                exclude_teacher_id=leave.teacher_id,
                leave_start=leave.start_date,
                leave_end=leave.end_date,
                exclude_substitution_id=existing_sub.id if existing_sub else None,
            )
            top = suggestions[0] if suggestions else None

            sub = existing_sub
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

    return substitutions_out


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

    substitutions_out = decide_leave_request(db, leave, body.decision, user.id, body.academic_year)
    write_audit_log(
        db,
        actor_id=user.id,
        action="approve" if body.decision == "approved" else "reject",
        entity_type="leave_requests",
        entity_id=leave.id,
        detail={"academic_year": body.academic_year, "substitutions_affected": len(substitutions_out)},
    )
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
    user: CurrentUser = Depends(require_role("admin", "principal", "teacher")),
    db: Session = Depends(get_db),
):
    """`leave_request_id` mode is readable by the teacher who OWNS that leave
    request too (they should be able to see who's covering their own
    classes), not just admin/principal - this is what backs the Staffing
    page's inline substitutions view for both roles. The `teacher_id` +
    date-range preview mode (Mode B) stays admin/principal-only - it lets
    the caller probe ANY teacher's schedule/candidates, which a teacher
    shouldn't be able to do for a colleague."""
    if body.leave_request_id is not None:
        if not body.academic_year:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "academic_year is required")
        leave = db.query(LeaveRequest).filter(LeaveRequest.id == body.leave_request_id).one_or_none()
        if leave is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found")
        if user.role == "teacher" and leave.teacher_id != user.id:
            # Same 404 as a genuinely missing request - never confirms a
            # different teacher's leave request exists (that would itself be
            # a real information leak: "this id is valid, just not yours").
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found")

        results = []
        for sub in db.query(Substitution).filter(Substitution.leave_request_id == leave.id).all():
            slot = db.query(TimetableSlot).filter(TimetableSlot.id == sub.timetable_slot_id).one()
            suggestions = _find_substitutes_with_fallback(
                db,
                subject_id=slot.subject_id,
                day_of_week=slot.day_of_week,
                period_number=slot.period_number,
                academic_year=body.academic_year,
                exclude_teacher_id=leave.teacher_id,
                leave_start=leave.start_date,
                leave_end=leave.end_date,
                exclude_substitution_id=sub.id,
            )
            top = suggestions[0] if suggestions else None
            sub.substitute_teacher_id = top.teacher_id if top else None
            sub.suggested_score = top.score if top else None
            results.append(_substitution_out(slot, suggestions, sub=sub))

        db.commit()
        return SuggestResponse(substitutions=results)

    if user.role == "teacher":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this preview")

    if body.teacher_id is None or body.start_date is None or body.end_date is None or body.academic_year is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Either leave_request_id, or teacher_id+start_date+end_date+academic_year, is required",
        )

    slots = _distinct_slots_for_leave(db, body.teacher_id, body.start_date, body.end_date, body.academic_year)
    results = []
    for slot in slots:
        suggestions = _find_substitutes_with_fallback(
            db,
            subject_id=slot.subject_id,
            day_of_week=slot.day_of_week,
            period_number=slot.period_number,
            academic_year=body.academic_year,
            exclude_teacher_id=body.teacher_id,
            leave_start=body.start_date,
            leave_end=body.end_date,
        )
        results.append(_substitution_out(slot, suggestions, original_teacher_id=body.teacher_id))

    return SuggestResponse(substitutions=results)


# --- PUT /substitution/{id}/confirm ---------------------------------------------


class ConfirmRequest(BaseModel):
    substitute_teacher_id: int | None = None
    """Omit to confirm the currently-suggested substitute; provide to override with a different teacher."""
    override_qualification: bool = False
    """Explicit admin acknowledgment to confirm a teacher NOT qualified for this
    subject anyway (real-world escalation when there's genuinely no qualified
    substitute left - supervision-only cover). This is the ONE conflict type
    that's a preference/quality concern rather than a scheduling/physical
    impossibility, so it's the only one this flag can waive - already_busy,
    already_substituting, unavailable, on_leave, and is_original_teacher stay
    absolute hard blocks regardless of this flag; a teacher genuinely can't be
    in two places at once no matter how badly a school needs coverage."""


class ConflictOut(BaseModel):
    type: str
    """One of: not_qualified, already_busy, unavailable, on_leave, is_original_teacher,
    already_substituting."""
    message: str
    overridable: bool = False
    """True only for not_qualified - see ConfirmRequest.override_qualification.
    Lets the frontend show an acknowledgment control for exactly this one
    conflict type without hardcoding the string "not_qualified" a second time."""


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
    db: Session, *, slot: TimetableSlot, leave: LeaveRequest, target_teacher_id: int, substitution_id: int
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
        conflicts.append(
            ConflictOut(type="not_qualified", message="Teacher is not qualified for this subject", overridable=True)
        )

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

    already_substituting_ids = _teachers_confirmed_substitutes_at(
        db,
        day_of_week=slot.day_of_week,
        period_number=slot.period_number,
        academic_year=slot.academic_year,
        exclude_substitution_id=substitution_id,
    )
    if target_teacher_id in already_substituting_ids:
        # The real double-booking gap this closes: `busy` above only looks at the
        # teacher's own real TimetableSlot rows, which is empty for a substitute -
        # nothing previously checked whether they were ALREADY CONFIRMED to cover
        # a DIFFERENT class at this exact day/period, so the same teacher could be
        # confirmed twice for two simultaneous slots with no error at all.
        conflicts.append(
            ConflictOut(
                type="already_substituting",
                message="Teacher is already confirmed as a substitute for a different class at this exact day/period",
            )
        )

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

    conflicts = _check_confirm_conflicts(db, slot=slot, leave=leave, target_teacher_id=target_teacher_id, substitution_id=sub.id)
    hard_conflicts = [c for c in conflicts if not c.overridable]
    if hard_conflicts:
        # A real impossibility (double-booked, on leave, etc.) - never waivable,
        # regardless of override_qualification.
        return ConfirmResponse(substitution=None, conflicts=conflicts)
    if conflicts and not body.override_qualification:
        # Only the not_qualified conflict remains, but the admin hasn't explicitly
        # acknowledged it yet - still block, so an accidental unqualified pick
        # doesn't silently go through. The frontend uses `overridable` on the
        # returned conflict to show an acknowledgment control at this point.
        return ConfirmResponse(substitution=None, conflicts=conflicts)

    sub.substitute_teacher_id = target_teacher_id
    sub.status = "confirmed"
    sub.confirmed_at = datetime.now(timezone.utc)
    write_audit_log(
        db,
        actor_id=user.id,
        action="confirm",
        entity_type="substitutions",
        entity_id=sub.id,
        detail={"substitute_teacher_id": target_teacher_id, "qualification_overridden": bool(conflicts)},
    )
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


# --- GET /staff/my-substitute-duties ---------------------------------------------


class MySubstituteDutyOut(BaseModel):
    substitution_id: int
    leave_request_id: int
    original_teacher_id: int
    subject_id: int
    class_id: int
    day_of_week: int
    period_number: int
    status: str
    """"suggested" or "confirmed" - a teacher should be able to tell the
    difference (a suggestion isn't a real commitment yet)."""
    leave_start_date: date_
    leave_end_date: date_


@router.get("/staff/my-substitute-duties", response_model=list[MySubstituteDutyOut])
def my_substitute_duties(
    user: CurrentUser = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
):
    """Real gap this closes: a teacher confirmed as someone else's substitute
    had NO way to discover it anywhere in their own UI - Substitution rows
    were only ever surfaced to the leave-taker and admin/principal, never to
    the substitute themselves. Scoped to still-relevant leave (end_date not
    already past) so old, resolved coverage doesn't clutter this indefinitely."""
    today = date_.today()
    rows = (
        db.query(Substitution, TimetableSlot, LeaveRequest)
        .join(TimetableSlot, Substitution.timetable_slot_id == TimetableSlot.id)
        .join(LeaveRequest, Substitution.leave_request_id == LeaveRequest.id)
        .filter(
            Substitution.substitute_teacher_id == user.id,
            LeaveRequest.status == "approved",
            LeaveRequest.end_date >= today,
        )
        .order_by(LeaveRequest.start_date, TimetableSlot.day_of_week, TimetableSlot.period_number)
        .all()
    )
    return [
        MySubstituteDutyOut(
            substitution_id=sub.id,
            leave_request_id=sub.leave_request_id,
            original_teacher_id=sub.original_teacher_id,
            subject_id=slot.subject_id,
            class_id=slot.class_id,
            day_of_week=slot.day_of_week,
            period_number=slot.period_number,
            status=sub.status,
            leave_start_date=leave.start_date,
            leave_end_date=leave.end_date,
        )
        for sub, slot, leave in rows
    ]


# --- GET /admin/staffing/forecast -----------------------------------------------


class ForecastDayOut(BaseModel):
    date: date_
    predicted_absences: float
    risk_level: str


class ForecastResponse(BaseModel):
    school_id: int
    week_start: date_
    forecast: list[ForecastDayOut]
    data_sufficient: bool
    """False when fewer than staffing_forecast.MIN_SOURCE_LEAVE_EVENTS_FOR_
    CONFIDENCE real approved leave requests exist in the lookback window - a
    school with e.g. exactly one ever-approved leave can mathematically
    produce a full week of numbers (see forecast_staffing_gaps), but that's
    one data point, not a real pattern. The frontend shows an explicit
    "insufficient historical data" state instead of a flat, confidently-
    styled risk_level when this is false."""


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
    return ForecastResponse(
        school_id=school_id,
        week_start=week_start,
        forecast=forecast_out,
        data_sufficient=has_sufficient_data(len(history_rows)),
    )


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
        suggestions = _find_substitutes_with_fallback(
            db,
            subject_id=slot.subject_id,
            day_of_week=slot.day_of_week,
            period_number=slot.period_number,
            academic_year=academic_year,
            exclude_teacher_id=teacher_id,
            leave_start=date,
            leave_end=date,
        )
        slot_outs.append(
            SlotSuggestionOut(
                timetable_slot_id=slot.id,
                subject_id=slot.subject_id,
                class_id=slot.class_id,
                period_number=slot.period_number,
                suggestions=[
                    CandidateOut(teacher_id=s.teacher_id, score=s.score, reason=s.reason, qualified=s.qualified)
                    for s in suggestions
                ],
            )
        )

    return SubstituteSuggestionsResponse(absent_teacher_id=teacher_id, date=date, slots=slot_outs)
