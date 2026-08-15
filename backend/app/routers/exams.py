from collections import defaultdict
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enrollment import Enrollment
from app.models.exams import Exam, ExamRoomAssignment, InvigilationAssignment, SeatingAssignment
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest
from app.models.subject import Subject
from app.models.class_ import SchoolClass
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.exam_scheduler import (
    InsufficientCapacityError,
    InvigilatorCandidate,
    RoomCapacity,
    TimeRange,
    assign_invigilators_for_exam,
    generate_seating,
)

router = APIRouter(tags=["exams"])
DEFAULT_PAGE_SIZE = 20


# --- POST /admin/exams ---------------------------------------------------------------
# NOT in the original api-contract.md stub - added because POST /admin/exams/{id}/
# schedules has nothing to generate a schedule FOR without an Exam already existing.
# Flagged here and in docs, same pattern as prior sessions' necessary additions.


class ExamCreateRequest(BaseModel):
    school_id: int
    subject_id: int
    class_id: int
    academic_year: str
    exam_date: date
    start_time: time
    end_time: time
    total_marks: int | None = None


class ExamOut(BaseModel):
    id: int
    school_id: int
    subject_id: int
    class_id: int
    academic_year: str
    exam_date: date
    start_time: time
    end_time: time
    total_marks: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("/admin/exams", response_model=ExamOut)
def create_exam(
    body: ExamCreateRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if body.end_time <= body.start_time:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_time must be after start_time")
    if db.query(School).filter(School.id == body.school_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown school_id {body.school_id}")
    if db.query(Subject).filter(Subject.id == body.subject_id).one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    if db.query(SchoolClass).filter(SchoolClass.id == body.class_id).one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")

    exam = Exam(
        school_id=body.school_id, subject_id=body.subject_id, class_id=body.class_id, academic_year=body.academic_year,
        exam_date=body.exam_date, start_time=body.start_time, end_time=body.end_time, total_marks=body.total_marks,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return ExamOut.model_validate(exam)


# --- GET /admin/exams -------------------------------------------------------------------
# NOT in the original stub - added because the frontend's exam management screen had no
# real way to browse existing exams, only remember ids from this session's own creates.
# Real RBAC-scoped list, not admin-only: a teacher only sees exams for (class, subject)
# pairs they actually teach; a student only sees exams for their own primary-enrollment
# class - same scoping precedents as syllabus.py's _teacher_class_subject_pairs and
# timetable.py's _resolve_student_class_id, duplicated locally per this codebase's
# per-router convention (see parent.py's identical duplication) rather than
# cross-importing a one-query helper.


def _teacher_class_subject_pairs(db: Session, teacher_id: int) -> set[tuple[int, int]]:
    rows = (
        db.query(TimetableSlot.class_id, TimetableSlot.subject_id)
        .filter(TimetableSlot.teacher_id == teacher_id, TimetableSlot.is_active.is_(True))
        .distinct()
        .all()
    )
    return {(r.class_id, r.subject_id) for r in rows}


def _resolve_student_class_id(db: Session, student_id: int) -> int | None:
    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == student_id, Enrollment.is_primary.is_(True))
        .one_or_none()
    )
    return enrollment.class_id if enrollment else None


class ExamListItemOut(BaseModel):
    id: int
    subject_id: int
    class_id: int
    academic_year: str
    exam_date: date
    start_time: time
    end_time: time

    model_config = ConfigDict(from_attributes=True)


class ExamsListResponse(BaseModel):
    items: list[ExamListItemOut]
    total: int
    page: int
    page_size: int


@router.get("/admin/exams", response_model=ExamsListResponse)
def list_exams(
    class_id: int | None = None,
    subject_id: int | None = None,
    academic_year: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("admin", "principal", "teacher", "student"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")
    if page < 1 or page_size < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "page and page_size must be positive")

    query = db.query(Exam)
    if class_id is not None:
        query = query.filter(Exam.class_id == class_id)
    if subject_id is not None:
        query = query.filter(Exam.subject_id == subject_id)
    if academic_year is not None:
        query = query.filter(Exam.academic_year == academic_year)
    # Secondary sort by id: exam_date/start_time alone can tie across distinct
    # exams (e.g. same day, same slot, different class), which makes pagination
    # non-deterministic - rows could be skipped or duplicated across pages.
    query = query.order_by(Exam.exam_date.desc(), Exam.start_time.desc(), Exam.id.desc())

    if user.role == "student":
        student_class_id = _resolve_student_class_id(db, user.id)
        query = query.filter(Exam.class_id == (student_class_id if student_class_id is not None else -1))
        total = query.count()
        rows = query.offset((page - 1) * page_size).limit(page_size).all()
    elif user.role == "teacher":
        # Pair-based scoping isn't a simple column filter, so (matching
        # syllabus.py's identical precedent) it's applied in Python after fetching
        # the admin-filtered rows, with pagination applied to the filtered list.
        owned_pairs = _teacher_class_subject_pairs(db, user.id)
        all_matching = query.all()
        filtered = [e for e in all_matching if (e.class_id, e.subject_id) in owned_pairs]
        total = len(filtered)
        rows = filtered[(page - 1) * page_size : (page - 1) * page_size + page_size]
    else:
        total = query.count()
        rows = query.offset((page - 1) * page_size).limit(page_size).all()

    return ExamsListResponse(
        items=[ExamListItemOut.model_validate(e) for e in rows], total=total, page=page, page_size=page_size
    )


# --- POST /admin/exams/{id}/schedules --------------------------------------------------
# Path deviates from the original stub (`POST /admin/exams/seating/generate` with
# exam_id in the body) to match this session's explicit instruction - id-in-path is
# the convention every other .../{id}/... action endpoint in this codebase uses.
# Flagged in docs, not silently changed.


class RoomInput(BaseModel):
    room_id: int
    capacity: int


class GenerateSchedulesRequest(BaseModel):
    rooms: list[RoomInput]


class SeatOut(BaseModel):
    student_id: int
    room_id: int
    seat_no: int


class InvigilatorAssignmentOut(BaseModel):
    room_id: int
    teacher_id: int | None
    """Null if no eligible candidate was found for this room - a real, surfaced
    gap, not silently dropped. See exam_scheduler.py's module docstring for why
    this is handled here rather than as a Command Center alert."""


class GenerateSchedulesResponse(BaseModel):
    exam_id: int
    status: str
    seating: list[SeatOut]
    invigilators: list[InvigilatorAssignmentOut]
    unassigned_rooms: list[int]


@router.post("/admin/exams/{exam_id}/schedules", response_model=GenerateSchedulesResponse)
def generate_schedules(
    exam_id: int,
    body: GenerateSchedulesRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    exam = db.query(Exam).filter(Exam.id == exam_id).one_or_none()
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exam not found")
    if not body.rooms:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one room is required")
    for r in body.rooms:
        if db.query(Room).filter(Room.id == r.room_id).one_or_none() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Room {r.room_id} not found")

    student_ids = [
        row.student_id
        for row in db.query(Enrollment.student_id).filter(Enrollment.class_id == exam.class_id, Enrollment.is_primary.is_(True))
    ]

    room_capacities = [RoomCapacity(room_id=r.room_id, capacity=r.capacity) for r in body.rooms]
    try:
        seats = generate_seating(student_ids, room_capacities)
    except InsufficientCapacityError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    teacher_role = db.query(Role).filter(Role.name == "teacher").one()
    teacher_ids = [row.id for row in db.query(User.id).filter(User.school_id == exam.school_id, User.role_id == teacher_role.id)]

    day_of_week = exam.exam_date.weekday()

    busy_by_teacher: dict[int, set[TimeRange]] = defaultdict(set)
    if teacher_ids:
        slots = (
            db.query(TimetableSlot)
            .filter(TimetableSlot.teacher_id.in_(teacher_ids), TimetableSlot.academic_year == exam.academic_year, TimetableSlot.is_active.is_(True))
            .all()
        )
        for slot in slots:
            busy_by_teacher[slot.teacher_id].add(TimeRange(day_of_week=slot.day_of_week, start_time=slot.start_time, end_time=slot.end_time))

    on_leave_teacher_ids = (
        {
            row.teacher_id
            for row in db.query(LeaveRequest.teacher_id).filter(
                LeaveRequest.teacher_id.in_(teacher_ids), LeaveRequest.status == "approved",
                LeaveRequest.start_date <= exam.exam_date, LeaveRequest.end_date >= exam.exam_date,
            )
        }
        if teacher_ids
        else set()
    )

    workload_by_teacher = (
        dict(
            db.query(InvigilationAssignment.teacher_id, func.count(InvigilationAssignment.id))
            .filter(InvigilationAssignment.teacher_id.in_(teacher_ids))
            .group_by(InvigilationAssignment.teacher_id)
            .all()
        )
        if teacher_ids
        else {}
    )

    candidates = [
        InvigilatorCandidate(
            teacher_id=tid, busy_ranges=frozenset(busy_by_teacher.get(tid, set())),
            on_leave=tid in on_leave_teacher_ids, current_invigilation_count=workload_by_teacher.get(tid, 0),
        )
        for tid in teacher_ids
    ]

    assigned = assign_invigilators_for_exam(
        room_ids=[r.room_id for r in body.rooms], day_of_week=day_of_week,
        start_time=exam.start_time, end_time=exam.end_time, candidates=candidates,
    )
    unassigned_rooms = [room_id for room_id, teacher_id in assigned.items() if teacher_id is None]

    # Supersedes any previous generation for this exam, not additive - same
    # convention as POST /timetable/generate.
    db.query(SeatingAssignment).filter(SeatingAssignment.exam_id == exam_id).delete()
    db.query(InvigilationAssignment).filter(InvigilationAssignment.exam_id == exam_id).delete()
    db.query(ExamRoomAssignment).filter(ExamRoomAssignment.exam_id == exam_id).delete()

    for r in body.rooms:
        db.add(ExamRoomAssignment(exam_id=exam_id, room_id=r.room_id, capacity=r.capacity))
    for s in seats:
        db.add(SeatingAssignment(exam_id=exam_id, student_id=s.student_id, room_id=s.room_id, seat_no=s.seat_no))
    for room_id, teacher_id in assigned.items():
        if teacher_id is not None:
            db.add(InvigilationAssignment(exam_id=exam_id, room_id=room_id, teacher_id=teacher_id, status="assigned"))

    write_audit_log(
        db, actor_id=user.id, action="generate", entity_type="exams", entity_id=exam_id,
        detail={"seats_assigned": len(seats), "rooms": len(body.rooms), "unassigned_rooms": unassigned_rooms},
    )
    db.commit()

    return GenerateSchedulesResponse(
        exam_id=exam_id, status="generated",
        seating=[SeatOut(student_id=s.student_id, room_id=s.room_id, seat_no=s.seat_no) for s in seats],
        invigilators=[InvigilatorAssignmentOut(room_id=room_id, teacher_id=teacher_id) for room_id, teacher_id in assigned.items()],
        unassigned_rooms=unassigned_rooms,
    )


# --- GET /admin/exams/seating ---------------------------------------------------------


class SeatingItemOut(BaseModel):
    exam_id: int
    student_id: int
    room_id: int
    room_name: str
    seat_no: int


class SeatingResponse(BaseModel):
    exam_id: int | None
    items: list[SeatingItemOut]


@router.get("/admin/exams/seating", response_model=SeatingResponse)
def get_seating(
    exam_id: int | None = None,
    student_id: int | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("admin", "principal", "teacher", "student"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")

    query = db.query(SeatingAssignment)
    if user.role == "student":
        # A student can only ever see their own seat - any student_id they pass is
        # ignored in favor of their own id, same scoping pattern as attendance/risk.
        query = query.filter(SeatingAssignment.student_id == user.id)
    elif student_id is not None:
        query = query.filter(SeatingAssignment.student_id == student_id)

    if exam_id is not None:
        query = query.filter(SeatingAssignment.exam_id == exam_id)

    rows = query.all()
    room_names = {r.id: r.name for r in db.query(Room).filter(Room.id.in_({row.room_id for row in rows} or {-1}))}

    items = [
        SeatingItemOut(exam_id=row.exam_id, student_id=row.student_id, room_id=row.room_id, room_name=room_names.get(row.room_id, ""), seat_no=row.seat_no)
        for row in rows
    ]
    return SeatingResponse(exam_id=exam_id, items=items)


# --- GET /admin/exams/invigilations/me ------------------------------------------------
# Backend for the playbook's "invigilator self-lookup" frontend note - built even
# though the frontend itself is deferred, per this session's instructions. Strictly
# self-scoped (the caller's own duties, via their own user.id) - "self-lookup" per
# the playbook's own wording, not a general admin-queries-any-teacher endpoint.


class InvigilationDutyOut(BaseModel):
    exam_id: int
    room_id: int
    room_name: str
    subject_id: int
    subject_name: str
    class_id: int
    class_name: str
    exam_date: date
    start_time: time
    end_time: time
    status: str


@router.get("/admin/exams/invigilations/me", response_model=list[InvigilationDutyOut])
def my_invigilation_duties(
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(InvigilationAssignment, Exam, Room, Subject, SchoolClass)
        .join(Exam, InvigilationAssignment.exam_id == Exam.id)
        .join(Room, InvigilationAssignment.room_id == Room.id)
        .join(Subject, Exam.subject_id == Subject.id)
        .join(SchoolClass, Exam.class_id == SchoolClass.id)
        .filter(InvigilationAssignment.teacher_id == user.id)
        .order_by(Exam.exam_date, Exam.start_time)
        .all()
    )
    return [
        InvigilationDutyOut(
            exam_id=exam.id, room_id=room.id, room_name=room.name, subject_id=subject.id, subject_name=subject.name,
            class_id=school_class.id, class_name=school_class.name, exam_date=exam.exam_date,
            start_time=exam.start_time, end_time=exam.end_time, status=invigilation.status,
        )
        for invigilation, exam, room, subject, school_class in rows
    ]
