from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.role import Role
from app.models.subject import Subject
from app.models.timetable import (
    Room,
    TeacherProfile,
    TeacherSubject,
    TeacherUnavailability,
    TimetableSlot,
)
from app.models.user import User
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.timetable_preflight import ClassInfo, Finding, run_preflight_checks
from app.services.timetable_solver import (
    GenerationResult,
    SolverRequirement,
    SolverRoom,
    SolverSubject,
    SolverTeacher,
    UnsolvableError,
    diagnose_infeasibility,
    generate_timetable,
)

router = APIRouter(prefix="/timetable", tags=["timetable"])

# MVP period->wall-clock mapping (no per-school period configuration exists yet).
# period_number is 0-indexed, matching day_of_week's "0 = Monday" convention.
_PERIOD_START = time(8, 0)
_PERIOD_DURATION = timedelta(minutes=45)

# Matches Room.room_type/scripts/seed_demo_data.py's SCIENCE_ROOM_TYPE convention -
# a subject's lab_required=true maps to this room_type for the solver's per-run
# SolverSubject.required_room_type, same mechanism SubjectRoomRequirement used
# before this became a per-run request field instead of persisted master data.
_LAB_ROOM_TYPE = "lab"


def _period_times(period_number: int) -> tuple[time, time]:
    start = datetime.combine(date.today(), _PERIOD_START) + _PERIOD_DURATION * period_number
    end = start + _PERIOD_DURATION
    return start.time(), end.time()


class SlotOut(BaseModel):
    id: int
    day_of_week: int
    period_number: int
    start_time: time
    end_time: time
    subject_id: int
    teacher_id: int
    class_id: int
    room_id: int
    academic_year: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SubjectSelection(BaseModel):
    subject_id: int
    periods_per_week: int
    lab_required: bool = False
    """True maps to SolverSubject.required_room_type=_LAB_ROOM_TYPE for this run -
    NOT persisted to SubjectRoomRequirement, see GenerateRequest's own docstring."""


class TeacherSelection(BaseModel):
    teacher_id: int
    included: bool = True
    """False excludes this teacher from the run entirely - they are omitted from
    solver input, not passed in with an empty qualification set. A generation
    that would otherwise need them fails honestly (422/"no teacher qualified"),
    it never silently falls back to using them anyway."""
    max_periods_per_week_override: int | None = None
    """None = use this teacher's stored TeacherProfile.max_periods_per_week for
    this run. Never persisted back to TeacherProfile - scoped to this run only."""


class GenerateRequest(BaseModel):
    """Real generation input for one run. Built fresh from real Teacher/Room/
    Subject master data (seed-script-managed, see CLAUDE.md) plus this request's
    own selections/overrides every time this is called - no longer reads
    ClassSubjectRequirement/SubjectRoomRequirement at all (superseded by
    subjects[] below). Nothing here is persisted back into those tables; a
    per-run override only ever affects this one generation."""

    school_id: int
    academic_year: str
    grade_levels: list[int]
    """Resolved against EXISTING SchoolClass.grade_level rows only - a grade with
    fewer seeded sections than sections_per_grade is a 400, never auto-created."""
    sections_per_grade: int
    periods_per_day: int = 6
    days_per_week: int = 5
    subjects: list[SubjectSelection]
    teacher_selections: list[TeacherSelection]
    room_ids: list[int]


class RemedyOut(BaseModel):
    action: str
    quantity: int
    detail: str


class FindingOut(BaseModel):
    severity: str
    """"error" or "warning"."""
    code: str
    subject: str | None = None
    message: str
    numbers: dict[str, int]
    remedies: list[RemedyOut] = []
    details: dict | None = None


class PreflightResponse(BaseModel):
    """Also the shape of a 422's `detail` when generation fails - either at
    the pre-flight arithmetic stage (stage="preflight", milliseconds, before
    the solver ever runs) or because the CP-SAT model itself proved
    infeasible despite passing every pre-flight check (stage="solve")."""

    feasible: bool
    stage: str | None = None
    """"preflight" or "solve" - only set when feasible is False."""
    findings: list[FindingOut] = []


def _finding_out(f: Finding) -> FindingOut:
    return FindingOut(
        severity=f.severity,
        code=f.code,
        subject=f.subject,
        message=f.message,
        numbers=f.numbers,
        remedies=[RemedyOut(action=r.action, quantity=r.quantity, detail=r.detail) for r in f.remedies],
        details=f.details,
    )


class GenerateResponse(BaseModel):
    academic_year: str
    slots_created: int
    slots: list[SlotOut]
    warnings: list[str] = []
    """Non-fatal configuration gaps found while building this run - e.g. a
    resolved class with no home_room_id, whose non-lab periods therefore
    weren't pinned to one room for this run."""
    findings: list[FindingOut] = []
    """Any WARNING-severity pre-flight findings for this (successful) run -
    e.g. a tight teacher pool or intentionally-empty periods. ERROR-severity
    findings never reach this far - they short-circuit into a 422 before the
    solver is ever called (see PreflightResponse)."""
    objective_weights: dict[str, int] = {}
    """The solver's two soft-preference term weights, by name, as used for
    this run (see timetable_solver.py's own constants) - reported so they can
    be tuned later without reading the solver's source."""
    objective_values: dict[str, int] = {}
    """Each term's actual achieved value at the returned solution - 0 means
    that preference was fully satisfied (no same-day clustering / no day-to-
    day load variance at all)."""


class UpdateSlotRequest(BaseModel):
    slot_id: int
    day_of_week: int | None = None
    period_number: int | None = None
    teacher_id: int | None = None
    room_id: int | None = None
    subject_id: int | None = None


class ConflictOut(BaseModel):
    type: str
    """One of: teacher, room, class."""
    conflicting_slot_id: int
    message: str


class UpdateSlotResponse(BaseModel):
    slot: SlotOut | None
    conflicts: list[ConflictOut]


def _resolve_classes(
    db: Session, school_id: int, academic_year: str, grade_levels: list[int], sections_per_grade: int
) -> list[SchoolClass]:
    """Resolves grade_levels[]/sections_per_grade against EXISTING SchoolClass rows
    only - this deliberately never creates a missing section (that's real class-
    management functionality, explicitly out of scope for a generation endpoint;
    see docs/api-contract.md). A grade with fewer seeded sections than requested
    is a clear 400 naming exactly which grade(s) are short, never a silent
    partial result."""
    rows = (
        db.query(SchoolClass)
        .filter(
            SchoolClass.school_id == school_id,
            SchoolClass.academic_year == academic_year,
            SchoolClass.grade_level.in_(grade_levels),
            SchoolClass.is_active.is_(True),
        )
        .order_by(SchoolClass.grade_level, SchoolClass.section)
        .all()
    )
    by_grade: dict[int, list[SchoolClass]] = {}
    for c in rows:
        by_grade.setdefault(c.grade_level, []).append(c)

    resolved: list[SchoolClass] = []
    short = {grade: len(by_grade.get(grade, [])) for grade in grade_levels if len(by_grade.get(grade, [])) < sections_per_grade}
    if short:
        detail = ", ".join(f"grade {g} has {n} seeded section(s), {sections_per_grade} requested" for g, n in short.items())
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Not enough sections seeded for the requested grade(s): {detail}")
    for grade in grade_levels:
        resolved.extend(by_grade[grade][:sections_per_grade])
    return resolved


@dataclass(frozen=True)
class GenerationInput:
    teachers: list[SolverTeacher]
    rooms: list[SolverRoom]
    subjects: list[SolverSubject]
    requirements: list[SolverRequirement]
    existing_bookings_by_teacher: dict[int, int]
    """Count of periods each included teacher already has booked this
    academic year from a PREVIOUSLY generated run for a DIFFERENT class
    (generation happens one grade at a time, and earlier grades' slots
    persist) - used by Check F's cross-run-collision diagnostic. These same
    slots are also merged into each SolverTeacher.unavailable below, so the
    solver itself now treats them as blocked rather than silently allowing a
    later run to double-book a teacher across two separate generation calls
    (a real correctness gap this fixes, not just a diagnostics-layer one)."""


def _build_generation_input(db: Session, body: GenerateRequest, resolved_classes: list[SchoolClass]) -> GenerationInput:
    """Builds this run's solver input directly from the request + real master
    data - see GenerateRequest's docstring for why this no longer reads
    ClassSubjectRequirement/SubjectRoomRequirement at all."""
    subject_selection_by_id = {s.subject_id: s for s in body.subjects}
    real_subject_ids = {
        row.id
        for row in db.query(Subject.id)
        .filter(
            Subject.id.in_(subject_selection_by_id.keys()),
            Subject.is_active.is_(True),
            Subject.school_id == body.school_id,
        )
        .all()
    }
    missing_subjects = set(subject_selection_by_id) - real_subject_ids
    if missing_subjects:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown or inactive subject_id(s): {sorted(missing_subjects)}")

    subjects = [
        SolverSubject(id=sid, required_room_type=(_LAB_ROOM_TYPE if sel.lab_required else None))
        for sid, sel in subject_selection_by_id.items()
    ]
    requirements = [
        SolverRequirement(class_id=c.id, subject_id=sid, periods_per_week=sel.periods_per_week, home_room_id=c.home_room_id)
        for c in resolved_classes
        for sid, sel in subject_selection_by_id.items()
    ]

    included_selections = [t for t in body.teacher_selections if t.included]
    teacher_ids = [t.teacher_id for t in included_selections]

    real_active_teacher_ids = {
        row.id
        for row in db.query(User.id)
        .join(Role, User.role_id == Role.id)
        .filter(
            User.id.in_(teacher_ids),
            Role.name == "teacher",
            User.is_active.is_(True),
            User.school_id == body.school_id,
        )
        .all()
    }
    missing_teachers = set(teacher_ids) - real_active_teacher_ids
    if missing_teachers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown or inactive teacher_id(s): {sorted(missing_teachers)}")

    teacher_subject_rows = (
        db.query(TeacherSubject)
        .filter(TeacherSubject.teacher_id.in_(teacher_ids), TeacherSubject.subject_id.in_(subject_selection_by_id.keys()))
        .all()
    )
    subject_ids_by_teacher: dict[int, set[int]] = {}
    for row in teacher_subject_rows:
        subject_ids_by_teacher.setdefault(row.teacher_id, set()).add(row.subject_id)

    unavailability_rows = (
        db.query(TeacherUnavailability)
        .filter(TeacherUnavailability.teacher_id.in_(teacher_ids), TeacherUnavailability.academic_year == body.academic_year)
        .all()
    )
    unavailable_by_teacher: dict[int, set[tuple[int, int]]] = {}
    for row in unavailability_rows:
        unavailable_by_teacher.setdefault(row.teacher_id, set()).add((row.day_of_week, row.period_number))

    # Cross-run collisions: generation happens one grade/section-batch at a
    # time (the admin UI only lets one grade be selected per run), and a
    # PREVIOUSLY generated grade's active slots are not touched by this run
    # (only resolved_classes' own slots get superseded below) - so a teacher
    # qualified across multiple grades can already be committed elsewhere
    # this academic year. Excluding resolved_classes' own ids is what makes
    # this "elsewhere", not "this run's own about-to-be-superseded slots".
    resolved_class_ids = [c.id for c in resolved_classes]
    existing_booking_rows = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.teacher_id.in_(teacher_ids),
            TimetableSlot.academic_year == body.academic_year,
            TimetableSlot.is_active.is_(True),
            TimetableSlot.class_id.notin_(resolved_class_ids),
        )
        .all()
    )
    existing_bookings_by_teacher: dict[int, int] = defaultdict(int)
    for row in existing_booking_rows:
        # Merged directly into the SAME unavailable set the solver enforces -
        # without this, nothing stopped a later run from double-booking a
        # teacher into a slot an earlier grade's run already gave them.
        unavailable_by_teacher.setdefault(row.teacher_id, set()).add((row.day_of_week, row.period_number))
        existing_bookings_by_teacher[row.teacher_id] += 1

    default_max_by_teacher = {
        p.teacher_id: p.max_periods_per_week
        for p in db.query(TeacherProfile).filter(TeacherProfile.teacher_id.in_(teacher_ids)).all()
    }
    # A teacher included with neither a stored TeacherProfile row nor an override
    # gets the full theoretical week as their cap - equivalent to uncapped, not a
    # made-up restrictive number.
    uncapped = body.days_per_week * body.periods_per_day

    teachers = [
        SolverTeacher(
            id=sel.teacher_id,
            subject_ids=frozenset(subject_ids_by_teacher.get(sel.teacher_id, set())),
            unavailable=frozenset(unavailable_by_teacher.get(sel.teacher_id, set())),
            max_periods_per_week=(
                sel.max_periods_per_week_override
                if sel.max_periods_per_week_override is not None
                else default_max_by_teacher.get(sel.teacher_id, uncapped)
            ),
        )
        for sel in included_selections
    ]

    room_rows = (
        db.query(Room)
        .filter(Room.id.in_(body.room_ids), Room.school_id == body.school_id, Room.is_active.is_(True))
        .all()
    )
    found_room_ids = {r.id for r in room_rows}
    missing_rooms = set(body.room_ids) - found_room_ids
    if missing_rooms:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Unknown or inactive room_id(s) for this school: {sorted(missing_rooms)}"
        )
    rooms = [SolverRoom(id=r.id, room_type=r.room_type) for r in room_rows]

    return GenerationInput(
        teachers=teachers,
        rooms=rooms,
        subjects=subjects,
        requirements=requirements,
        existing_bookings_by_teacher=dict(existing_bookings_by_teacher),
    )


def _resolve_names(db: Session, subject_ids: list[int], teacher_ids: list[int]) -> tuple[dict[int, str], dict[int, str]]:
    subject_names = {row.id: row.name for row in db.query(Subject.id, Subject.name).filter(Subject.id.in_(subject_ids)).all()}
    teacher_names = {
        row.id: (row.full_name or row.email)
        for row in db.query(User.id, User.full_name, User.email).filter(User.id.in_(teacher_ids)).all()
    }
    return subject_names, teacher_names


def _validate_generate_request(body: GenerateRequest, user: CurrentUser) -> None:
    if body.school_id != user.school_id:
        # Without this, the body's school_id was trusted outright - an admin
        # could generate (and thereby supersede/overwrite) another school's
        # real timetable just by naming that school's id, bypassing whatever
        # the frontend happens to auto-fill.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot generate a timetable for a different school")
    if not body.grade_levels:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "grade_levels must not be empty")
    if body.sections_per_grade < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "sections_per_grade must be at least 1")
    if not body.subjects:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "subjects must not be empty")
    if not body.room_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "room_ids must not be empty")


def _run_preflight_for_request(
    db: Session, body: GenerateRequest, user: CurrentUser
) -> tuple[list[SchoolClass], GenerationInput, list[Finding], dict[int, str], dict[int, str], dict[int, str]]:
    """Shared by POST /generate and POST /timetable/preflight so the two
    endpoints can never drift apart - the live-as-you-type dialog check and
    the one that actually gates generation run the exact same checks."""
    _validate_generate_request(body, user)
    resolved_classes = _resolve_classes(db, body.school_id, body.academic_year, body.grade_levels, body.sections_per_grade)
    gen_input = _build_generation_input(db, body, resolved_classes)
    subject_names, teacher_names = _resolve_names(
        db, [s.id for s in gen_input.subjects], [t.id for t in gen_input.teachers]
    )
    class_names = {c.id: c.name for c in resolved_classes}
    class_infos = [ClassInfo(id=c.id, name=c.name, home_room_id=c.home_room_id) for c in resolved_classes]

    findings = run_preflight_checks(
        teachers=gen_input.teachers,
        rooms=gen_input.rooms,
        subjects=gen_input.subjects,
        requirements=gen_input.requirements,
        classes=class_infos,
        days=body.days_per_week,
        periods_per_day=body.periods_per_day,
        subject_names=subject_names,
        teacher_names=teacher_names,
        existing_bookings_by_teacher=gen_input.existing_bookings_by_teacher,
    )
    return resolved_classes, gen_input, findings, subject_names, teacher_names, class_names


@router.post("/preflight", response_model=PreflightResponse)
def preflight(
    body: GenerateRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """Read-only: runs the exact same pre-flight checks POST /generate gates
    on, without touching the database or running the solver - meant to be
    called live as the admin edits the Generate dialog (debounced), so
    arithmetic problems surface before they click Generate, not 30s after."""
    _, _gen_input, findings, _subject_names, _teacher_names, _class_names = _run_preflight_for_request(db, body, user)
    error_findings = [f for f in findings if f.severity == "error"]
    return PreflightResponse(
        feasible=not error_findings,
        stage="preflight" if error_findings else None,
        findings=[_finding_out(f) for f in findings],
    )


@router.post("/generate", response_model=GenerateResponse)
def generate(
    body: GenerateRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    resolved_classes, gen_input, findings, subject_names, teacher_names, class_names = _run_preflight_for_request(
        db, body, user
    )
    class_ids = [c.id for c in resolved_classes]

    error_findings = [f for f in findings if f.severity == "error"]
    if error_findings:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PreflightResponse(feasible=False, stage="preflight", findings=[_finding_out(f) for f in error_findings]).model_dump(),
        )
    warning_findings = [f for f in findings if f.severity == "warning"]

    try:
        result: GenerationResult = generate_timetable(
            teachers=gen_input.teachers,
            rooms=gen_input.rooms,
            subjects=gen_input.subjects,
            requirements=gen_input.requirements,
            days=body.days_per_week,
            periods_per_day=body.periods_per_day,
        )
    except UnsolvableError:
        # Pre-flight passed, yet CP-SAT still proved infeasible - a genuine
        # constraint-interaction case pure arithmetic can't predict. Ask the
        # solver's own infeasibility core which specific requirements are
        # actually in conflict, instead of a generic message.
        diagnosis = diagnose_infeasibility(
            teachers=gen_input.teachers,
            rooms=gen_input.rooms,
            subjects=gen_input.subjects,
            requirements=gen_input.requirements,
            days=body.days_per_week,
            periods_per_day=body.periods_per_day,
            class_names=class_names,
            subject_names=subject_names,
            teacher_names=teacher_names,
        )
        finding = FindingOut(
            severity="error",
            code=diagnosis.code,
            subject=None,
            message=diagnosis.message,
            numbers={},
            remedies=[],
            details=diagnosis.details or None,
        )
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            PreflightResponse(feasible=False, stage="solve", findings=[finding]).model_dump(),
        )
    schedule = result.slots

    # Superseding a previous generation run for these classes/year, not stacking on top of it.
    db.query(TimetableSlot).filter(
        TimetableSlot.class_id.in_(class_ids),
        TimetableSlot.academic_year == body.academic_year,
        TimetableSlot.is_active.is_(True),
    ).update({TimetableSlot.is_active: False}, synchronize_session=False)

    created: list[TimetableSlot] = []
    for slot in schedule:
        start_time, end_time = _period_times(slot.period_number)
        row = TimetableSlot(
            day_of_week=slot.day_of_week,
            period_number=slot.period_number,
            start_time=start_time,
            end_time=end_time,
            subject_id=slot.subject_id,
            teacher_id=slot.teacher_id,
            class_id=slot.class_id,
            room_id=slot.room_id,
            academic_year=body.academic_year,
            is_active=True,
        )
        db.add(row)
        created.append(row)

    db.commit()
    for row in created:
        db.refresh(row)

    return GenerateResponse(
        academic_year=body.academic_year,
        slots_created=len(created),
        slots=[SlotOut.model_validate(r) for r in created],
        warnings=result.warnings,
        findings=[_finding_out(f) for f in warning_findings],
        objective_weights=result.objective_weights,
        objective_values=result.objective_values,
    )


def _resolve_student_class_id(db: Session, student_id: int) -> int:
    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == student_id, Enrollment.is_primary.is_(True))
        .one_or_none()
    )
    if enrollment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No primary class enrollment found for this student")
    return enrollment.class_id


@router.get("/active", response_model=list[SlotOut])
def get_active(
    academic_year: str,
    class_id: int | None = None,
    teacher_id: int | None = None,
    student_id: int | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(TimetableSlot).filter(
        TimetableSlot.academic_year == academic_year, TimetableSlot.is_active.is_(True)
    )

    if user.role in ("admin", "principal"):
        # Scoped to the caller's own school via the slot's class - without this,
        # any admin/principal saw every school's slots for a matching
        # academic_year (a real cross-tenant leak this fixes; only visible once
        # two real schools existed in the same DB at once).
        query = query.join(SchoolClass, TimetableSlot.class_id == SchoolClass.id).filter(
            SchoolClass.school_id == user.school_id
        )
        if class_id is not None:
            query = query.filter(TimetableSlot.class_id == class_id)
        if teacher_id is not None:
            query = query.filter(TimetableSlot.teacher_id == teacher_id)
    elif user.role == "teacher":
        query = query.filter(TimetableSlot.teacher_id == user.id)
        if class_id is not None:
            query = query.filter(TimetableSlot.class_id == class_id)
    elif user.role == "student":
        query = query.filter(TimetableSlot.class_id == _resolve_student_class_id(db, user.id))
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
        query = query.filter(TimetableSlot.class_id == _resolve_student_class_id(db, student_id))
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Unknown role")

    return [SlotOut.model_validate(r) for r in query.all()]


def _find_conflicts(
    db: Session, slot: TimetableSlot, day_of_week: int, period_number: int, teacher_id: int, room_id: int, class_id: int
) -> list[ConflictOut]:
    candidates = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.id != slot.id,
            TimetableSlot.academic_year == slot.academic_year,
            TimetableSlot.is_active.is_(True),
            TimetableSlot.day_of_week == day_of_week,
            TimetableSlot.period_number == period_number,
        )
        .all()
    )
    conflicts: list[ConflictOut] = []
    for other in candidates:
        if other.teacher_id == teacher_id:
            conflicts.append(
                ConflictOut(type="teacher", conflicting_slot_id=other.id, message="Teacher already booked in this period")
            )
        if other.room_id == room_id:
            conflicts.append(
                ConflictOut(type="room", conflicting_slot_id=other.id, message="Room already booked in this period")
            )
        if other.class_id == class_id:
            conflicts.append(
                ConflictOut(type="class", conflicting_slot_id=other.id, message="Class already has a period scheduled")
            )
    return conflicts


@router.put("/update", response_model=UpdateSlotResponse)
def update_slot(
    body: UpdateSlotRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    slot = db.query(TimetableSlot).filter(TimetableSlot.id == body.slot_id).one_or_none()
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Timetable slot not found")

    slot_school_id = db.query(SchoolClass.school_id).filter(SchoolClass.id == slot.class_id).scalar()
    if slot_school_id != user.school_id:
        # Same 404 as a genuinely missing slot - never confirms a slot exists in
        # a different school (that would itself be a cross-tenant leak). A real
        # cross-tenant reschedule was possible here before this fix: this
        # endpoint accepted ANY slot_id with no ownership check at all.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Timetable slot not found")

    day_of_week = body.day_of_week if body.day_of_week is not None else slot.day_of_week
    period_number = body.period_number if body.period_number is not None else slot.period_number
    teacher_id = body.teacher_id if body.teacher_id is not None else slot.teacher_id
    room_id = body.room_id if body.room_id is not None else slot.room_id
    subject_id = body.subject_id if body.subject_id is not None else slot.subject_id

    # Overridable FK fields must be validated BEFORE the conflict check / commit -
    # an unknown id here would otherwise reach the UPDATE and raise an unhandled
    # IntegrityError instead of a clean 4xx (a gap this session's reliability
    # audit found and this fixes). Also must belong to the caller's OWN school -
    # a real id from a different school is rejected the same way an unknown id
    # is, never silently cross-assigned (the cross-tenant write gap this fixes).
    if body.teacher_id is not None and db.query(User.id).filter(User.id == body.teacher_id, User.school_id == user.school_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown teacher_id {body.teacher_id}")
    if body.room_id is not None and db.query(Room.id).filter(Room.id == body.room_id, Room.school_id == user.school_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown room_id {body.room_id}")
    if body.subject_id is not None and db.query(Subject.id).filter(Subject.id == body.subject_id, Subject.school_id == user.school_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown subject_id {body.subject_id}")

    conflicts = _find_conflicts(db, slot, day_of_week, period_number, teacher_id, room_id, slot.class_id)
    if conflicts:
        return UpdateSlotResponse(slot=None, conflicts=conflicts)

    slot.day_of_week = day_of_week
    slot.period_number = period_number
    slot.teacher_id = teacher_id
    slot.room_id = room_id
    slot.subject_id = subject_id
    slot.start_time, slot.end_time = _period_times(period_number)

    write_audit_log(
        db,
        actor_id=user.id,
        action="update",
        entity_type="timetable_slots",
        entity_id=slot.id,
        detail={"day_of_week": day_of_week, "period_number": period_number, "teacher_id": teacher_id, "room_id": room_id, "subject_id": subject_id},
    )
    db.commit()
    db.refresh(slot)

    return UpdateSlotResponse(slot=SlotOut.model_validate(slot), conflicts=[])
