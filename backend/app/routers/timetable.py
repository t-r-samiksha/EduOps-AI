from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.subject import Subject
from app.models.timetable import (
    ClassSubjectRequirement,
    Room,
    SubjectRoomRequirement,
    TeacherSubject,
    TeacherUnavailability,
    TimetableSlot,
)
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.timetable_solver import (
    ScheduledSlot,
    SolverRequirement,
    SolverRoom,
    SolverSubject,
    SolverTeacher,
    UnsolvableError,
    generate_timetable,
)

router = APIRouter(prefix="/timetable", tags=["timetable"])

# MVP period->wall-clock mapping (no per-school period configuration exists yet).
# period_number is 0-indexed, matching day_of_week's "0 = Monday" convention.
_PERIOD_START = time(8, 0)
_PERIOD_DURATION = timedelta(minutes=45)


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


class GenerateRequest(BaseModel):
    school_id: int
    academic_year: str
    class_ids: list[int] | None = None
    """Classes to generate for. Defaults to every class in the school."""
    days: int = 5
    periods_per_day: int = 6


class GenerateResponse(BaseModel):
    academic_year: str
    slots_created: int
    slots: list[SlotOut]


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


def _load_solver_input(
    db: Session, school_id: int, academic_year: str, class_ids: list[int]
) -> tuple[list[SolverTeacher], list[SolverRoom], list[SolverSubject], list[SolverRequirement]]:
    requirement_rows = (
        db.query(ClassSubjectRequirement)
        .filter(
            ClassSubjectRequirement.class_id.in_(class_ids),
            ClassSubjectRequirement.academic_year == academic_year,
        )
        .all()
    )
    if not requirement_rows:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No ClassSubjectRequirement rows found for the given class(es)/academic_year",
        )
    requirements = [
        SolverRequirement(class_id=r.class_id, subject_id=r.subject_id, periods_per_week=r.periods_per_week)
        for r in requirement_rows
    ]
    subject_ids = {r.subject_id for r in requirement_rows}

    subject_rows = db.query(Subject).filter(Subject.id.in_(subject_ids)).all()
    room_requirements = {
        row.subject_id: row.room_type
        for row in db.query(SubjectRoomRequirement).filter(SubjectRoomRequirement.subject_id.in_(subject_ids)).all()
    }
    subjects = [
        SolverSubject(id=s.id, required_room_type=room_requirements.get(s.id)) for s in subject_rows
    ]

    teacher_subject_rows = (
        db.query(TeacherSubject)
        .filter(TeacherSubject.subject_id.in_(subject_ids))
        .all()
    )
    subject_ids_by_teacher: dict[int, set[int]] = {}
    for row in teacher_subject_rows:
        subject_ids_by_teacher.setdefault(row.teacher_id, set()).add(row.subject_id)

    unavailability_rows = (
        db.query(TeacherUnavailability)
        .filter(
            TeacherUnavailability.teacher_id.in_(subject_ids_by_teacher.keys()),
            TeacherUnavailability.academic_year == academic_year,
        )
        .all()
    )
    unavailable_by_teacher: dict[int, set[tuple[int, int]]] = {}
    for row in unavailability_rows:
        unavailable_by_teacher.setdefault(row.teacher_id, set()).add((row.day_of_week, row.period_number))

    teachers = [
        SolverTeacher(
            id=teacher_id,
            subject_ids=frozenset(subject_ids_),
            unavailable=frozenset(unavailable_by_teacher.get(teacher_id, set())),
        )
        for teacher_id, subject_ids_ in subject_ids_by_teacher.items()
    ]

    room_rows = db.query(Room).filter(Room.school_id == school_id).all()
    rooms = [SolverRoom(id=r.id, room_type=r.room_type) for r in room_rows]

    return teachers, rooms, subjects, requirements


@router.post("/generate", response_model=GenerateResponse)
def generate(
    body: GenerateRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if body.class_ids is not None:
        class_ids = body.class_ids
    else:
        class_ids = [c.id for c in db.query(SchoolClass).filter(SchoolClass.school_id == body.school_id).all()]
    if not class_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No classes found for school_id")

    teachers, rooms, subjects, requirements = _load_solver_input(db, body.school_id, body.academic_year, class_ids)

    try:
        schedule: list[ScheduledSlot] = generate_timetable(
            teachers=teachers,
            rooms=rooms,
            subjects=subjects,
            requirements=requirements,
            days=body.days,
            periods_per_day=body.periods_per_day,
        )
    except UnsolvableError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

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

    day_of_week = body.day_of_week if body.day_of_week is not None else slot.day_of_week
    period_number = body.period_number if body.period_number is not None else slot.period_number
    teacher_id = body.teacher_id if body.teacher_id is not None else slot.teacher_id
    room_id = body.room_id if body.room_id is not None else slot.room_id
    subject_id = body.subject_id if body.subject_id is not None else slot.subject_id

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
