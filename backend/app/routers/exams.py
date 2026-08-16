from collections import defaultdict
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, tuple_
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
    suggest_rooms,
)

router = APIRouter(tags=["exams"])
DEFAULT_PAGE_SIZE = 20


# --- POST /admin/exams ---------------------------------------------------------------
# NOT in the original api-contract.md stub - added because POST /admin/exams/{id}/
# schedules has nothing to generate a schedule FOR without an Exam already existing.
# Flagged here and in docs, same pattern as prior sessions' necessary additions.


EXAM_TYPES = ("class_test", "unit_test", "mid_term", "end_term")
"""Free text, not a DB enum - matches FeeSchedule.fee_type's convention - but the
API validates against this fixed preset list rather than accepting anything, since
(unlike a fee type) there's no real-world reason an admin would need an arbitrary
exam type name here."""


class ExamCreateRequest(BaseModel):
    school_id: int
    subject_id: int
    class_id: int
    academic_year: str
    exam_type: str | None = None
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
    exam_type: str | None
    exam_date: date
    start_time: time
    end_time: time
    total_marks: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


def _validate_exam_fields(db: Session, school_id: int, subject_id: int, exam_type: str | None, start_time: time, end_time: time) -> None:
    if end_time <= start_time:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_time must be after start_time")
    if exam_type is not None and exam_type not in EXAM_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"exam_type must be one of {EXAM_TYPES}")
    if db.query(School).filter(School.id == school_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown school_id {school_id}")
    if db.query(Subject).filter(Subject.id == subject_id).one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")


@router.post("/admin/exams", response_model=ExamOut)
def create_exam(
    body: ExamCreateRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if body.school_id != user.school_id:
        # Without this, the body's school_id was trusted outright - an admin
        # could create (and later generate/overwrite) an exam for another
        # school entirely, same class of gap fixed in timetable.py's
        # _validate_generate_request.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot create an exam for a different school")
    _validate_exam_fields(db, body.school_id, body.subject_id, body.exam_type, body.start_time, body.end_time)
    if db.query(SchoolClass).filter(SchoolClass.id == body.class_id).one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")

    exam = Exam(
        school_id=body.school_id, subject_id=body.subject_id, class_id=body.class_id, academic_year=body.academic_year,
        exam_type=body.exam_type, exam_date=body.exam_date, start_time=body.start_time, end_time=body.end_time,
        total_marks=body.total_marks,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return ExamOut.model_validate(exam)


# --- POST /admin/exams/bulk-by-grade --------------------------------------------------
# Grade-wide creation: one Exam per active section in the grade, same subject/date/
# time/type/marks - a separate endpoint (not a mode on POST /admin/exams) so the
# original single-class contract stays exactly as every existing caller/test expects;
# this only adds a new capability, never changes the old one's response shape.


class ExamBulkCreateRequest(BaseModel):
    school_id: int
    subject_id: int
    grade_level: int
    academic_year: str
    exam_type: str | None = None
    exam_date: date
    start_time: time
    end_time: time
    total_marks: int | None = None


class ExamBulkCreateResponse(BaseModel):
    created: list[ExamOut]


@router.post("/admin/exams/bulk-by-grade", response_model=ExamBulkCreateResponse)
def create_exams_for_grade(
    body: ExamBulkCreateRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if body.school_id != user.school_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot create an exam for a different school")
    _validate_exam_fields(db, body.school_id, body.subject_id, body.exam_type, body.start_time, body.end_time)

    classes = (
        db.query(SchoolClass)
        .filter(
            SchoolClass.school_id == body.school_id, SchoolClass.academic_year == body.academic_year,
            SchoolClass.grade_level == body.grade_level, SchoolClass.is_active.is_(True),
        )
        .all()
    )
    if not classes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No active class found for grade_level {body.grade_level} in {body.academic_year}")

    created = [
        Exam(
            school_id=body.school_id, subject_id=body.subject_id, class_id=c.id, academic_year=body.academic_year,
            exam_type=body.exam_type, exam_date=body.exam_date, start_time=body.start_time, end_time=body.end_time,
            total_marks=body.total_marks,
        )
        for c in classes
    ]
    db.add_all(created)
    db.commit()
    for e in created:
        db.refresh(e)
    return ExamBulkCreateResponse(created=[ExamOut.model_validate(e) for e in created])


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
    exam_type: str | None
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

    # Every role's exams are scoped to their own school first - without this an
    # admin/principal saw every OTHER school's exams too (a real cross-tenant leak,
    # same class of gap fixed elsewhere this session in fees.py/master_data.py).
    # Harmless no-op for teacher/student, whose own class/enrollment already only
    # ever resolves within their own school.
    query = db.query(Exam).filter(Exam.school_id == user.school_id)
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


# --- GET /admin/exams/{id}/room-suggestions --------------------------------------------
# "Room selection must suggest the best one based on availability" - a room is
# excluded if it's already booked (ExamRoomAssignment) for a DIFFERENT exam whose
# date+time overlaps this one; suggest_rooms() then picks the smallest-waste subset
# of what's left to seat this exam's real headcount. A suggestion, not a forced
# choice - the frontend still shows every available room so the admin can override.


def _times_overlap(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    return a_start < b_end and b_start < a_end


class RoomSuggestionItem(BaseModel):
    room_id: int
    room_name: str
    capacity: int


class RoomSuggestionsResponse(BaseModel):
    exam_id: int
    headcount: int
    available_rooms: list[RoomSuggestionItem]
    suggested_room_ids: list[int]


@router.get("/admin/exams/{exam_id}/room-suggestions", response_model=RoomSuggestionsResponse)
def get_room_suggestions(
    exam_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.school_id == user.school_id).one_or_none()
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exam not found")

    headcount = (
        db.query(Enrollment)
        .filter(Enrollment.class_id == exam.class_id, Enrollment.is_primary.is_(True))
        .count()
    )

    other_exams_same_day = (
        db.query(Exam)
        .filter(Exam.school_id == exam.school_id, Exam.exam_date == exam.exam_date, Exam.id != exam_id)
        .all()
    )
    overlapping_exam_ids = [
        e.id for e in other_exams_same_day if _times_overlap(e.start_time, e.end_time, exam.start_time, exam.end_time)
    ]
    booked_room_ids = (
        {
            row.room_id
            for row in db.query(ExamRoomAssignment.room_id).filter(ExamRoomAssignment.exam_id.in_(overlapping_exam_ids))
        }
        if overlapping_exam_ids
        else set()
    )

    all_rooms = db.query(Room).filter(Room.school_id == exam.school_id, Room.is_active.is_(True)).all()
    available = [r for r in all_rooms if r.id not in booked_room_ids]
    suggested = suggest_rooms([RoomCapacity(room_id=r.id, capacity=r.capacity) for r in available], headcount)

    return RoomSuggestionsResponse(
        exam_id=exam_id, headcount=headcount,
        available_rooms=[RoomSuggestionItem(room_id=r.id, room_name=r.name, capacity=r.capacity) for r in available],
        suggested_room_ids=[rc.room_id for rc in suggested],
    )


# --- POST /admin/exams/{id}/schedules --------------------------------------------------
# Path deviates from the original stub (`POST /admin/exams/seating/generate` with
# exam_id in the body) to match this session's explicit instruction - id-in-path is
# the convention every other .../{id}/... action endpoint in this codebase uses.
# Flagged in docs, not silently changed.
#
# HITL: dry_run defaults to False (unchanged persist-immediately behavior for every
# existing caller) - but the frontend now always calls dry_run=true first to get a
# PREVIEW (nothing written), shows the admin exactly what would happen (seating,
# invigilators, any unassigned rooms), and only calls again with dry_run=false to
# actually persist once the admin explicitly confirms. Same shape as
# /timetable/preflight -> /timetable/generate's existing split in this codebase.


class RoomInput(BaseModel):
    room_id: int
    capacity: int


class GenerateSchedulesRequest(BaseModel):
    rooms: list[RoomInput]
    dry_run: bool = False


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
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.school_id == user.school_id).one_or_none()
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
            busy_by_teacher[slot.teacher_id].add(
                TimeRange(day_of_week=slot.day_of_week, start_time=slot.start_time, end_time=slot.end_time, class_id=slot.class_id)
            )

    # 3-tier invigilator priority (see exam_scheduler.py's module docstring):
    # preferred = whoever normally has THIS exact class at this exact slot (any
    # subject); deprioritized = whoever normally teaches THIS exam's own subject
    # to this class (last resort, to avoid subject-teacher bias). Both derived
    # from this class's own active timetable, not the busy-conflict query above.
    class_slots = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.class_id == exam.class_id, TimetableSlot.academic_year == exam.academic_year, TimetableSlot.is_active.is_(True))
        .all()
    )
    preferred_teacher_ids = frozenset(
        slot.teacher_id for slot in class_slots
        if slot.day_of_week == day_of_week and _times_overlap(slot.start_time, slot.end_time, exam.start_time, exam.end_time)
    )
    deprioritized_teacher_ids = frozenset(slot.teacher_id for slot in class_slots if slot.subject_id == exam.subject_id)

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
        exam_class_id=exam.class_id, preferred_teacher_ids=preferred_teacher_ids,
        deprioritized_teacher_ids=deprioritized_teacher_ids,
    )
    unassigned_rooms = [room_id for room_id, teacher_id in assigned.items() if teacher_id is None]

    if body.dry_run:
        # HITL preview - nothing written. The admin reviews this exact result (same
        # seating/invigilator computation the real run would produce) and calls
        # again with dry_run=false to persist it.
        return GenerateSchedulesResponse(
            exam_id=exam_id, status="preview",
            seating=[SeatOut(student_id=s.student_id, room_id=s.room_id, seat_no=s.seat_no) for s in seats],
            invigilators=[InvigilatorAssignmentOut(room_id=room_id, teacher_id=teacher_id) for room_id, teacher_id in assigned.items()],
            unassigned_rooms=unassigned_rooms,
        )

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
    subject_id: int
    subject_name: str
    exam_type: str | None
    exam_date: date
    class_id: int
    class_name: str
    invigilator_teacher_id: int | None
    invigilator_name: str | None
    """None if this room has no invigilator assigned yet - a real, surfaced gap,
    same honesty as GenerateSchedulesResponse.unassigned_rooms."""


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

    if user.role == "student":
        # A student sees the FULL room they're seated in for each exam - not just
        # their own row - so the frontend can render the real layout with their own
        # seat highlighted, not an isolated single seat. Any student_id they pass
        # is still ignored in favor of their own id (same scoping pattern as
        # attendance/risk) - it only decides WHOSE room(s) to resolve, never lets
        # them view another student's.
        own_query = db.query(SeatingAssignment).filter(SeatingAssignment.student_id == user.id)
        if exam_id is not None:
            own_query = own_query.filter(SeatingAssignment.exam_id == exam_id)
        own_room_keys = {(r.exam_id, r.room_id) for r in own_query.all()}

        rows = (
            db.query(SeatingAssignment)
            .filter(tuple_(SeatingAssignment.exam_id, SeatingAssignment.room_id).in_(list(own_room_keys)))
            .all()
            if own_room_keys
            else []
        )
    else:
        # admin/principal/teacher - scoped to their own school via a join, same
        # gap class fixed above for POST /admin/exams and GET /admin/exams.
        query = db.query(SeatingAssignment).join(Exam, SeatingAssignment.exam_id == Exam.id).filter(Exam.school_id == user.school_id)
        if student_id is not None:
            query = query.filter(SeatingAssignment.student_id == student_id)
        if exam_id is not None:
            query = query.filter(SeatingAssignment.exam_id == exam_id)
        rows = query.all()
    room_names = {r.id: r.name for r in db.query(Room).filter(Room.id.in_({row.room_id for row in rows} or {-1}))}

    # Exam metadata (subject/date/type/class) and the room's invigilator, added
    # this session - "include the details about the test" and "view the
    # invigilator for a particular class", both surfaced right alongside the
    # seats instead of needing a separate lookup.
    exam_ids = {row.exam_id for row in rows}
    exams_by_id = {e.id: e for e in db.query(Exam).filter(Exam.id.in_(exam_ids or {-1}))}
    subject_ids = {e.subject_id for e in exams_by_id.values()}
    subject_names = {s.id: s.name for s in db.query(Subject).filter(Subject.id.in_(subject_ids or {-1}))}
    class_ids = {e.class_id for e in exams_by_id.values()}
    class_names = {c.id: c.name for c in db.query(SchoolClass).filter(SchoolClass.id.in_(class_ids or {-1}))}

    invigilator_teacher_by_key = {
        (inv.exam_id, inv.room_id): inv.teacher_id
        for inv in db.query(InvigilationAssignment).filter(InvigilationAssignment.exam_id.in_(exam_ids or {-1}))
    }
    invigilator_teacher_ids = {tid for tid in invigilator_teacher_by_key.values()}
    invigilator_names = {u.id: (u.full_name or u.email) for u in db.query(User).filter(User.id.in_(invigilator_teacher_ids or {-1}))}

    items = []
    for row in rows:
        exam = exams_by_id[row.exam_id]
        invigilator_teacher_id = invigilator_teacher_by_key.get((row.exam_id, row.room_id))
        items.append(
            SeatingItemOut(
                exam_id=row.exam_id, student_id=row.student_id, room_id=row.room_id, room_name=room_names.get(row.room_id, ""),
                seat_no=row.seat_no, subject_id=exam.subject_id, subject_name=subject_names.get(exam.subject_id, ""),
                exam_type=exam.exam_type, exam_date=exam.exam_date, class_id=exam.class_id, class_name=class_names.get(exam.class_id, ""),
                invigilator_teacher_id=invigilator_teacher_id,
                invigilator_name=invigilator_names.get(invigilator_teacher_id) if invigilator_teacher_id is not None else None,
            )
        )
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
