from datetime import date as date_
from datetime import datetime, time as time_, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attendance import AttendanceRecord, FaceEmbedding
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.subject import Subject
from app.models.timetable import TimetableSlot
from app.models.user import User
from app.services.attendance_cv import (
    FaceCVError,
    InvalidImageError,
    KnownFace,
    MultipleFacesDetectedError,
    NoFaceDetectedError,
    RecognitionResult,
    enroll_face,
    recognize_faces,
)
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.scoping import assert_parent_linked

router = APIRouter(prefix="/attendance", tags=["attendance"])

VALID_STATUSES = ("present", "absent", "late")


class EmbeddingOut(BaseModel):
    id: int
    student_id: int
    enrolled_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FaceMatchOut(BaseModel):
    student_id: int
    confidence: float
    needs_review: bool
    face_location: list[int]
    record_id: int
    already_marked: bool
    """True if a CV record for this student/slot/date already existed (idempotent
    re-run) - record_id points at the pre-existing row, nothing new was created."""


class UnmatchedFaceOut(BaseModel):
    face_location: list[int]
    best_confidence: float | None
    """Confidence of the closest known face, or null if no student in this class has
    an enrolled embedding at all."""


class RosterStudentOut(BaseModel):
    student_id: int
    name: str


class MarkResponse(BaseModel):
    timetable_slot_id: int
    class_id: int
    date: date_
    records_created: int
    matches: list[FaceMatchOut]
    unmatched_faces: list[UnmatchedFaceOut]
    class_roster: list[RosterStudentOut]
    """Every student enrolled in this slot's class - the same pool
    recognize_faces compared against. Lets the UI offer a "this was actually
    <student>" reassignment for a needs_review match without a second
    round-trip, and without letting an admin reassign to someone who was
    never even a candidate for this class."""


class AttendanceRecordOut(BaseModel):
    id: int
    student_id: int
    class_id: int
    timetable_slot_id: int | None
    date: date_
    status: str
    source: str
    marked_at: datetime
    confidence_score: float | None
    reviewed_by: int | None
    reviewed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ReviewRequest(BaseModel):
    status: str
    student_id: int | None = None
    """Set to correct a needs_review match's identity - "the system detected
    this face as student X, but it's actually student Y". Omitted/null keeps
    the record's existing student_id (the normal confirm/reject-only path).
    Only ever reassigns to a student actually enrolled in the record's own
    class - the pool recognize_faces compared against in the first place."""


class SummaryItemOut(BaseModel):
    student_id: int
    class_id: int
    present_count: int
    absent_count: int
    late_count: int
    total_records: int
    present_pct: float


class SummaryResponse(BaseModel):
    from_date: date_
    to_date: date_
    items: list[SummaryItemOut]


@router.post("/enroll", response_model=EmbeddingOut)
async def enroll(
    student_id: int = Form(...),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_role("admin", "teacher")),
    db: Session = Depends(get_db),
):
    student = db.query(User).filter(User.id == student_id).one_or_none()
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    image_bytes = await file.read()
    try:
        embedding = enroll_face(image_bytes)
    except (NoFaceDetectedError, MultipleFacesDetectedError, InvalidImageError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    row = FaceEmbedding(student_id=student_id, embedding=embedding)
    db.add(row)
    db.commit()
    db.refresh(row)

    return EmbeddingOut.model_validate(row)


class EnrollmentListItemOut(BaseModel):
    id: int
    student_id: int
    student_name: str
    enrolled_at: datetime


@router.get("/enrollments", response_model=list[EnrollmentListItemOut])
def list_enrollments(
    school_id: int,
    user: CurrentUser = Depends(require_role("admin", "teacher")),
    db: Session = Depends(get_db),
):
    """Real, persisted enrollment state for a school - not client session
    memory. The Enroll tab's "Enrolled" list is backed by this (refetched on
    mount and after each successful enrollment), which is what makes it
    survive a full page reload: it's reading the actual DB truth fresh each
    time, not remembering what happened earlier in an in-memory list."""
    rows = (
        db.query(FaceEmbedding, User)
        .join(User, FaceEmbedding.student_id == User.id)
        .filter(User.school_id == school_id)
        .order_by(FaceEmbedding.enrolled_at.desc(), FaceEmbedding.id.desc())
        .all()
    )
    return [
        EnrollmentListItemOut(id=e.id, student_id=e.student_id, student_name=u.full_name or u.email, enrolled_at=e.enrolled_at)
        for e, u in rows
    ]


@router.post("/mark", response_model=MarkResponse)
async def mark(
    timetable_slot_id: int = Form(...),
    file: UploadFile = File(...),
    date: date_ | None = Form(None),
    user: CurrentUser = Depends(require_role("admin", "teacher")),
    db: Session = Depends(get_db),
):
    slot = db.query(TimetableSlot).filter(TimetableSlot.id == timetable_slot_id).one_or_none()
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Timetable slot not found")
    effective_date = date or date_.today()

    enrolled_student_ids = [
        row.student_id
        for row in db.query(Enrollment.student_id)
        .filter(Enrollment.class_id == slot.class_id, Enrollment.is_primary.is_(True))
        .all()
    ]
    embedding_rows = (
        db.query(FaceEmbedding).filter(FaceEmbedding.student_id.in_(enrolled_student_ids)).all()
        if enrolled_student_ids
        else []
    )
    known_faces = [KnownFace(student_id=row.student_id, embedding=list(row.embedding)) for row in embedding_rows]

    image_bytes = await file.read()
    try:
        result: RecognitionResult = recognize_faces(image_bytes, known_faces)
    except FaceCVError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    existing_by_student = {
        r.student_id: r
        for r in db.query(AttendanceRecord).filter(
            AttendanceRecord.timetable_slot_id == slot.id,
            AttendanceRecord.date == effective_date,
            AttendanceRecord.source == "cv",
        )
    }

    matches_out: list[FaceMatchOut] = []
    seen_students: set[int] = set()
    records_created = 0

    for match in sorted(result.matches, key=lambda m: -m.confidence):
        if match.student_id in seen_students:
            continue
        seen_students.add(match.student_id)

        existing = existing_by_student.get(match.student_id)
        if existing is not None:
            matches_out.append(
                FaceMatchOut(
                    student_id=match.student_id,
                    confidence=match.confidence,
                    needs_review=match.needs_review,
                    face_location=list(match.face_location),
                    record_id=existing.id,
                    already_marked=True,
                )
            )
            continue

        record = AttendanceRecord(
            student_id=match.student_id,
            class_id=slot.class_id,
            timetable_slot_id=slot.id,
            date=effective_date,
            status="present",
            source="cv",
            confidence_score=match.confidence,
        )
        db.add(record)
        db.flush()
        records_created += 1
        matches_out.append(
            FaceMatchOut(
                student_id=match.student_id,
                confidence=match.confidence,
                needs_review=match.needs_review,
                face_location=list(match.face_location),
                record_id=record.id,
                already_marked=False,
            )
        )

    db.commit()

    unmatched_out = [
        UnmatchedFaceOut(face_location=list(u.face_location), best_confidence=u.best_confidence)
        for u in result.unmatched
    ]

    roster_rows = (
        db.query(User.id, User.full_name, User.email).filter(User.id.in_(enrolled_student_ids)).all()
        if enrolled_student_ids
        else []
    )
    class_roster = [RosterStudentOut(student_id=r.id, name=r.full_name or r.email) for r in roster_rows]

    return MarkResponse(
        timetable_slot_id=slot.id,
        class_id=slot.class_id,
        date=effective_date,
        records_created=records_created,
        matches=matches_out,
        unmatched_faces=unmatched_out,
        class_roster=class_roster,
    )


def _teacher_class_ids(db: Session, teacher_id: int) -> list[int]:
    return [c.id for c in db.query(SchoolClass).filter(SchoolClass.class_teacher_id == teacher_id).all()]


@router.get("/summary", response_model=SummaryResponse)
def summary(
    from_date: date_,
    to_date: date_,
    class_id: int | None = None,
    student_id: int | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(AttendanceRecord).filter(AttendanceRecord.date >= from_date, AttendanceRecord.date <= to_date)

    if user.role in ("admin", "principal"):
        if class_id is not None:
            query = query.filter(AttendanceRecord.class_id == class_id)
        if student_id is not None:
            query = query.filter(AttendanceRecord.student_id == student_id)
    elif user.role == "teacher":
        owned_class_ids = _teacher_class_ids(db, user.id)
        if class_id is not None:
            if class_id not in owned_class_ids:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your class")
            query = query.filter(AttendanceRecord.class_id == class_id)
        else:
            query = query.filter(AttendanceRecord.class_id.in_(owned_class_ids or [-1]))
    elif user.role == "student":
        query = query.filter(AttendanceRecord.student_id == user.id)
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
        query = query.filter(AttendanceRecord.student_id == student_id)
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Unknown role")

    counts: dict[tuple[int, int], dict[str, int]] = {}
    for record in query.all():
        key = (record.student_id, record.class_id)
        bucket = counts.setdefault(key, {"present": 0, "absent": 0, "late": 0})
        if record.status in bucket:
            bucket[record.status] += 1

    items = []
    for (student_id_, class_id_), bucket in counts.items():
        total = sum(bucket.values())
        items.append(
            SummaryItemOut(
                student_id=student_id_,
                class_id=class_id_,
                present_count=bucket["present"],
                absent_count=bucket["absent"],
                late_count=bucket["late"],
                total_records=total,
                present_pct=round(100 * bucket["present"] / total, 1) if total else 0.0,
            )
        )

    return SummaryResponse(from_date=from_date, to_date=to_date, items=items)


@router.put("/{record_id}/review", response_model=AttendanceRecordOut)
def review(
    record_id: int,
    body: ReviewRequest,
    user: CurrentUser = Depends(require_role("admin", "principal", "teacher")),
    db: Session = Depends(get_db),
):
    if body.status not in VALID_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"status must be one of {VALID_STATUSES}")

    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attendance record not found")

    if user.role == "teacher" and record.class_id not in _teacher_class_ids(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your class")

    previous_student_id = record.student_id
    if body.student_id is not None and body.student_id != record.student_id:
        enrolled = (
            db.query(Enrollment)
            .filter(
                Enrollment.class_id == record.class_id,
                Enrollment.student_id == body.student_id,
                Enrollment.is_primary.is_(True),
            )
            .one_or_none()
        )
        if enrolled is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Student {body.student_id} is not enrolled in this record's class"
            )
        conflict = (
            db.query(AttendanceRecord)
            .filter(
                AttendanceRecord.id != record.id,
                AttendanceRecord.student_id == body.student_id,
                AttendanceRecord.timetable_slot_id == record.timetable_slot_id,
                AttendanceRecord.date == record.date,
                AttendanceRecord.source == record.source,
            )
            .one_or_none()
        )
        if conflict is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Student {body.student_id} already has an attendance record for this period",
            )
        record.student_id = body.student_id

    previous_status = record.status
    record.status = body.status
    record.reviewed_by = user.id
    record.reviewed_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        actor_id=user.id,
        action="review",
        entity_type="attendance_records",
        entity_id=record.id,
        detail={
            "previous_status": previous_status,
            "new_status": body.status,
            "previous_student_id": previous_student_id,
            "new_student_id": record.student_id,
        },
    )
    db.commit()
    db.refresh(record)

    return AttendanceRecordOut.model_validate(record)


# --- Reading, correcting and analysing what got marked -------------------------
#
# Everything below is the human-facing half of this router. POST /mark writes
# records from a photo; these four endpoints are how a teacher/principal/admin
# then reads a day back, fixes it by hand, analyses it across a range, and how a
# student/parent sees their own period-by-period history.
#
# Two conventions hold across all four, and differ from the older endpoints
# above on purpose:
#
# 1. EVERY class lookup is filtered by the caller's own school_id, not just by
#    the id in the query string. A bare `WHERE classes.id = :class_id` would let
#    an admin of school A read school B's register by guessing an integer, which
#    is a recurring shape of bug in this codebase's admin/principal endpoints.
#
# 2. "A teacher's classes" is WIDER here than in /summary and /review, which use
#    _teacher_class_ids (homeroom ownership only). The person who marks P3's
#    attendance is P3's subject teacher, who frequently is not the class
#    teacher, so _teacher_accessible_class_ids below also counts classes the
#    teacher actually teaches at least one active period to. /summary and
#    /review deliberately keep the older, stricter rule - widening them is a
#    behaviour change to tested endpoints and belongs in its own commit.


def _teacher_accessible_class_ids(db: Session, teacher_id: int) -> list[int]:
    """Classes this teacher may read/mark attendance for: ones they own as class
    teacher, plus ones they teach at least one active timetable period to."""
    owned = {row.id for row in db.query(SchoolClass.id).filter(SchoolClass.class_teacher_id == teacher_id)}
    taught = {
        row.class_id
        for row in db.query(TimetableSlot.class_id).filter(
            TimetableSlot.teacher_id == teacher_id, TimetableSlot.is_active.is_(True)
        )
    }
    return sorted(owned | taught)


def _require_school(user: CurrentUser) -> int:
    """School-scoped endpoints can't be scoped at all for a user with no school."""
    if user.school_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account is not linked to a school")
    return user.school_id


def _resolve_class(db: Session, user: CurrentUser, class_id: int) -> SchoolClass:
    """Fetch a class the caller is actually allowed to see, or raise.

    404 rather than 403 for a class outside the caller's school - an admin
    probing ids shouldn't be able to tell "exists, not yours" from "doesn't
    exist".
    """
    school_id = _require_school(user)
    school_class = (
        db.query(SchoolClass)
        .filter(SchoolClass.id == class_id, SchoolClass.school_id == school_id)
        .one_or_none()
    )
    if school_class is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    if user.role == "teacher" and class_id not in _teacher_accessible_class_ids(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your class")
    return school_class


def _readable_class_ids(db: Session, user: CurrentUser, *, class_id: int | None = None) -> list[int]:
    """Every class the caller may aggregate over, optionally narrowed to one."""
    school_id = _require_school(user)
    query = db.query(SchoolClass.id).filter(SchoolClass.school_id == school_id)
    if class_id is not None:
        query = query.filter(SchoolClass.id == class_id)
    ids = [row.id for row in query]
    if user.role == "teacher":
        accessible = set(_teacher_accessible_class_ids(db, user.id))
        if class_id is not None and class_id not in accessible:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your class")
        ids = [i for i in ids if i in accessible]
    if class_id is not None and not ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    return ids


def _display_name(full_name: str | None, email: str | None) -> str:
    return full_name or email or "Unknown"


def _roster(db: Session, class_id: int) -> list[tuple[int, str]]:
    """(student_id, name) for every primary enrollment in a class, name-sorted."""
    rows = (
        db.query(User.id, User.full_name, User.email)
        .join(Enrollment, Enrollment.student_id == User.id)
        .filter(Enrollment.class_id == class_id, Enrollment.is_primary.is_(True))
        .all()
    )
    return sorted(((r.id, _display_name(r.full_name, r.email)) for r in rows), key=lambda p: p[1].lower())


def _pct(present: int, total: int) -> float:
    return round(100 * present / total, 1) if total else 0.0


# --- GET /attendance/register --------------------------------------------------


class RegisterPeriodOut(BaseModel):
    timetable_slot_id: int
    period_number: int
    start_time: time_
    end_time: time_
    subject_id: int
    subject_name: str
    teacher_id: int
    teacher_name: str
    is_marked: bool
    """False when this period has NO attendance records at all for the date.
    Without this, "the teacher never marked P5" and "every student was absent in
    P5" are indistinguishable in the UI, and the second is far rarer."""
    marked_count: int


class RegisterCellOut(BaseModel):
    timetable_slot_id: int
    record_id: int | None
    status: str | None
    """None means unmarked - no record exists for this student/period/date."""
    source: str | None
    confidence_score: float | None
    needs_review: bool
    """A cv-sourced record inside the 0.45-0.6 review band that no human has
    confirmed yet. Mirrors what POST /mark flagged, recomputed from the stored
    confidence so it survives a page reload."""
    reviewed_by_name: str | None


class RegisterStudentOut(BaseModel):
    student_id: int
    name: str
    cells: list[RegisterCellOut]
    present_count: int
    absent_count: int
    late_count: int
    unmarked_count: int
    present_pct: float
    """Of the periods actually marked for this student on this date - unmarked
    periods are excluded from the denominator rather than counted as absent."""


class RegisterTotalsOut(BaseModel):
    roster_size: int
    period_count: int
    marked_periods: int
    unmarked_periods: int
    present_cells: int
    absent_cells: int
    late_cells: int
    unmarked_cells: int
    present_pct: float


class RegisterResponse(BaseModel):
    class_id: int
    class_name: str
    grade_level: int | None
    grade_label: str | None
    section: str | None
    date: date_
    day_of_week: int
    academic_year: str
    periods: list[RegisterPeriodOut]
    students: list[RegisterStudentOut]
    totals: RegisterTotalsOut


# Recomputed from the stored confidence rather than persisted as a column, so it
# stays in lockstep with attendance_cv's own band if that band ever moves.
_REVIEW_CONFIDENCE_FLOOR = 1.0 - 0.6
_REVIEW_CONFIDENCE_CEILING = 1.0 - 0.45


def _needs_review(record: AttendanceRecord) -> bool:
    if record.source != "cv" or record.confidence_score is None or record.reviewed_at is not None:
        return False
    return _REVIEW_CONFIDENCE_FLOOR <= record.confidence_score < _REVIEW_CONFIDENCE_CEILING


@router.get("/register", response_model=RegisterResponse)
def register(
    class_id: int,
    date: date_,
    user: CurrentUser = Depends(require_role("admin", "principal", "teacher")),
    db: Session = Depends(get_db),
):
    """One class's whole day as a period x student grid - the day view a teacher
    reads back after the camera has run, and edits by hand via POST /manual."""
    school_class = _resolve_class(db, user, class_id)

    slots = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.class_id == class_id,
            TimetableSlot.day_of_week == date.weekday(),
            TimetableSlot.academic_year == school_class.academic_year,
            TimetableSlot.is_active.is_(True),
        )
        .order_by(TimetableSlot.period_number)
        .all()
    )
    slot_ids = [s.id for s in slots]

    subject_names = {
        row.id: row.name for row in db.query(Subject.id, Subject.name).filter(Subject.id.in_([s.subject_id for s in slots] or [-1]))
    }
    teacher_names = {
        row.id: _display_name(row.full_name, row.email)
        for row in db.query(User.id, User.full_name, User.email).filter(
            User.id.in_([s.teacher_id for s in slots] or [-1])
        )
    }

    records = (
        db.query(AttendanceRecord)
        .filter(
            AttendanceRecord.date == date,
            AttendanceRecord.timetable_slot_id.in_(slot_ids or [-1]),
        )
        .all()
        if slot_ids
        else []
    )
    by_student_slot = {(r.student_id, r.timetable_slot_id): r for r in records}
    reviewer_names = {
        row.id: _display_name(row.full_name, row.email)
        for row in db.query(User.id, User.full_name, User.email).filter(
            User.id.in_([r.reviewed_by for r in records if r.reviewed_by is not None] or [-1])
        )
    }

    roster = _roster(db, class_id)
    marked_per_slot = {sid: 0 for sid in slot_ids}
    for record in records:
        if record.timetable_slot_id in marked_per_slot:
            marked_per_slot[record.timetable_slot_id] += 1

    students_out: list[RegisterStudentOut] = []
    totals = {"present": 0, "absent": 0, "late": 0, "unmarked": 0}
    for student_id, name in roster:
        cells: list[RegisterCellOut] = []
        counts = {"present": 0, "absent": 0, "late": 0, "unmarked": 0}
        for slot in slots:
            record = by_student_slot.get((student_id, slot.id))
            if record is None:
                counts["unmarked"] += 1
                cells.append(
                    RegisterCellOut(
                        timetable_slot_id=slot.id,
                        record_id=None,
                        status=None,
                        source=None,
                        confidence_score=None,
                        needs_review=False,
                        reviewed_by_name=None,
                    )
                )
                continue
            if record.status in counts:
                counts[record.status] += 1
            cells.append(
                RegisterCellOut(
                    timetable_slot_id=slot.id,
                    record_id=record.id,
                    status=record.status,
                    source=record.source,
                    confidence_score=record.confidence_score,
                    needs_review=_needs_review(record),
                    reviewed_by_name=reviewer_names.get(record.reviewed_by) if record.reviewed_by else None,
                )
            )
        for key in totals:
            totals[key] += counts[key]
        marked = counts["present"] + counts["absent"] + counts["late"]
        students_out.append(
            RegisterStudentOut(
                student_id=student_id,
                name=name,
                cells=cells,
                present_count=counts["present"],
                absent_count=counts["absent"],
                late_count=counts["late"],
                unmarked_count=counts["unmarked"],
                present_pct=_pct(counts["present"], marked),
            )
        )

    periods_out = [
        RegisterPeriodOut(
            timetable_slot_id=slot.id,
            period_number=slot.period_number,
            start_time=slot.start_time,
            end_time=slot.end_time,
            subject_id=slot.subject_id,
            subject_name=subject_names.get(slot.subject_id, f"Subject #{slot.subject_id}"),
            teacher_id=slot.teacher_id,
            teacher_name=teacher_names.get(slot.teacher_id, f"Teacher #{slot.teacher_id}"),
            is_marked=marked_per_slot.get(slot.id, 0) > 0,
            marked_count=marked_per_slot.get(slot.id, 0),
        )
        for slot in slots
    ]
    marked_cells = totals["present"] + totals["absent"] + totals["late"]

    return RegisterResponse(
        class_id=class_id,
        class_name=school_class.name,
        grade_level=school_class.grade_level,
        grade_label=school_class.grade_label,
        section=school_class.section,
        date=date,
        day_of_week=date.weekday(),
        academic_year=school_class.academic_year,
        periods=periods_out,
        students=students_out,
        totals=RegisterTotalsOut(
            roster_size=len(roster),
            period_count=len(slots),
            marked_periods=sum(1 for p in periods_out if p.is_marked),
            unmarked_periods=sum(1 for p in periods_out if not p.is_marked),
            present_cells=totals["present"],
            absent_cells=totals["absent"],
            late_cells=totals["late"],
            unmarked_cells=totals["unmarked"],
            present_pct=_pct(totals["present"], marked_cells),
        ),
    )


# --- POST /attendance/manual --------------------------------------------------


class ManualEntry(BaseModel):
    student_id: int
    timetable_slot_id: int
    status: str


class ManualMarkRequest(BaseModel):
    class_id: int
    date: date_
    entries: list[ManualEntry]
    """Bulk on purpose: "mark all 40 present" is one request, not 40. Later
    entries for the same (student, slot) win, so a UI that batches a grid of
    local edits doesn't have to dedupe first."""


class ManualMarkResponse(BaseModel):
    created: int
    updated: int
    unchanged: int
    """Entries whose status already matched - no write, and no audit row."""
    records: list[AttendanceRecordOut]


@router.post("/manual", response_model=ManualMarkResponse)
def mark_manual(
    body: ManualMarkRequest,
    user: CurrentUser = Depends(require_role("admin", "principal", "teacher")),
    db: Session = Depends(get_db),
):
    """Mark/correct attendance by hand for any number of student-period cells.

    Upserts rather than inserting: if a record already exists for a
    (student, slot, date) in ANY source it is updated in place and stamped with
    reviewed_by/reviewed_at. It deliberately does NOT insert a second
    source='manual' row alongside a source='cv' one - the table's unique
    constraint includes `source`, so that would be allowed by the DB and would
    silently double-count that period in /summary and in the nightly risk
    scorer. `source` is left as-is on update, so a corrected camera record still
    reads as "the CV wrote this, then a human changed it"; reviewed_by is what
    proves the human touch. The before/after lands in the audit log.
    """
    _resolve_class(db, user, body.class_id)

    for entry in body.entries:
        if entry.status not in VALID_STATUSES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"status must be one of {VALID_STATUSES}")

    # Collapse duplicates, last one wins.
    wanted: dict[tuple[int, int], str] = {
        (e.student_id, e.timetable_slot_id): e.status for e in body.entries
    }
    if not wanted:
        return ManualMarkResponse(created=0, updated=0, unchanged=0, records=[])

    slot_ids = {slot_id for _, slot_id in wanted}
    student_ids = {student_id for student_id, _ in wanted}

    valid_slot_ids = {
        row.id
        for row in db.query(TimetableSlot.id).filter(
            TimetableSlot.id.in_(slot_ids),
            TimetableSlot.class_id == body.class_id,
            TimetableSlot.is_active.is_(True),
        )
    }
    unknown_slots = slot_ids - valid_slot_ids
    if unknown_slots:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Timetable slot(s) {sorted(unknown_slots)} are not active periods of class {body.class_id}",
        )

    enrolled_ids = {
        row.student_id
        for row in db.query(Enrollment.student_id).filter(
            Enrollment.student_id.in_(student_ids),
            Enrollment.class_id == body.class_id,
            Enrollment.is_primary.is_(True),
        )
    }
    unknown_students = student_ids - enrolled_ids
    if unknown_students:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Student(s) {sorted(unknown_students)} are not enrolled in class {body.class_id}",
        )

    existing = {
        (r.student_id, r.timetable_slot_id): r
        for r in db.query(AttendanceRecord).filter(
            AttendanceRecord.date == body.date,
            AttendanceRecord.timetable_slot_id.in_(slot_ids),
            AttendanceRecord.student_id.in_(student_ids),
        )
    }

    now = datetime.now(timezone.utc)
    created = updated = unchanged = 0
    touched: list[AttendanceRecord] = []

    for (student_id, slot_id), new_status in wanted.items():
        record = existing.get((student_id, slot_id))
        if record is None:
            record = AttendanceRecord(
                student_id=student_id,
                class_id=body.class_id,
                timetable_slot_id=slot_id,
                date=body.date,
                status=new_status,
                source="manual",
                reviewed_by=user.id,
                reviewed_at=now,
            )
            db.add(record)
            db.flush()
            created += 1
            write_audit_log(
                db,
                actor_id=user.id,
                action="manual_mark",
                entity_type="attendance_records",
                entity_id=record.id,
                detail={
                    "previous_status": None,
                    "new_status": new_status,
                    "student_id": student_id,
                    "timetable_slot_id": slot_id,
                    "date": body.date.isoformat(),
                    "source": "manual",
                },
            )
        elif record.status == new_status:
            unchanged += 1
        else:
            previous_status = record.status
            record.status = new_status
            record.reviewed_by = user.id
            record.reviewed_at = now
            updated += 1
            write_audit_log(
                db,
                actor_id=user.id,
                action="manual_mark",
                entity_type="attendance_records",
                entity_id=record.id,
                detail={
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "student_id": student_id,
                    "timetable_slot_id": slot_id,
                    "date": body.date.isoformat(),
                    "source": record.source,
                },
            )
        touched.append(record)

    db.commit()
    for record in touched:
        db.refresh(record)

    return ManualMarkResponse(
        created=created,
        updated=updated,
        unchanged=unchanged,
        records=[AttendanceRecordOut.model_validate(r) for r in touched],
    )


# --- GET /attendance/analytics ------------------------------------------------


class BucketOut(BaseModel):
    present_count: int
    absent_count: int
    late_count: int
    total_records: int
    present_pct: float


class PeriodBucketOut(BucketOut):
    period_number: int


class DayBucketOut(BucketOut):
    date: date_
    day_of_week: int


class ClassBucketOut(BucketOut):
    class_id: int
    class_name: str
    grade_level: int | None
    grade_label: str | None
    section: str | None


class SubjectBucketOut(BucketOut):
    subject_id: int
    subject_name: str


class StudentBucketOut(BucketOut):
    student_id: int
    name: str
    class_id: int
    class_name: str
    section: str | None
    trend_delta: float
    """present_pct over the newer half of the window minus the older half.
    Positive = improving. 0.0 when either half has no records."""
    trend: str
    """rising | flat | falling - trend_delta bucketed at +/-2 points."""


class AnalyticsResponse(BaseModel):
    from_date: date_
    to_date: date_
    overall: BucketOut
    by_period: list[PeriodBucketOut]
    by_day: list[DayBucketOut]
    by_class: list[ClassBucketOut]
    by_subject: list[SubjectBucketOut]
    students: list[StudentBucketOut]
    roster_size: int
    below_pct_count: int
    """How many students in `students` fall under the below_pct threshold. Equal
    to len(students) when below_pct was supplied, since the list is filtered."""


_TREND_BAND = 2.0


def _bucket(counts: dict[str, int]) -> dict:
    total = counts["present"] + counts["absent"] + counts["late"]
    return {
        "present_count": counts["present"],
        "absent_count": counts["absent"],
        "late_count": counts["late"],
        "total_records": total,
        "present_pct": _pct(counts["present"], total),
    }


def _new_counts() -> dict[str, int]:
    return {"present": 0, "absent": 0, "late": 0}


@router.get("/analytics", response_model=AnalyticsResponse)
def analytics(
    from_date: date_,
    to_date: date_,
    class_id: int | None = None,
    grade_level: int | None = None,
    section: str | None = None,
    period_number: int | None = None,
    subject_id: int | None = None,
    below_pct: float | None = None,
    user: CurrentUser = Depends(require_role("admin", "principal", "teacher")),
    db: Session = Depends(get_db),
):
    """Attendance sliced by period, day, class/section, subject and student over
    a date range, for the sort-and-analyse view.

    by_period and by_subject only cover records attached to a timetable slot -
    `overall`, `by_day`, `by_class` and `students` count every record in range.
    Today every record written by this router has a slot, so the two agree; a
    future holiday/ad-hoc record with a null slot would show up in the latter
    and not the former, which is the honest way round.
    """
    if from_date > to_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "from_date must be on or before to_date")

    class_ids = _readable_class_ids(db, user, class_id=class_id)
    class_rows = (
        db.query(SchoolClass).filter(SchoolClass.id.in_(class_ids)).all() if class_ids else []
    )
    if grade_level is not None:
        class_rows = [c for c in class_rows if c.grade_level == grade_level]
    if section is not None:
        class_rows = [c for c in class_rows if (c.section or "") == section]
    classes_by_id = {c.id: c for c in class_rows}
    scoped_class_ids = list(classes_by_id)

    records = (
        db.query(AttendanceRecord)
        .filter(
            AttendanceRecord.date >= from_date,
            AttendanceRecord.date <= to_date,
            AttendanceRecord.class_id.in_(scoped_class_ids),
        )
        .all()
        if scoped_class_ids
        else []
    )

    slot_ids = {r.timetable_slot_id for r in records if r.timetable_slot_id is not None}
    slots_by_id = {
        s.id: s for s in db.query(TimetableSlot).filter(TimetableSlot.id.in_(slot_ids or [-1]))
    } if slot_ids else {}

    if period_number is not None:
        records = [
            r
            for r in records
            if r.timetable_slot_id is not None
            and slots_by_id.get(r.timetable_slot_id) is not None
            and slots_by_id[r.timetable_slot_id].period_number == period_number
        ]
    if subject_id is not None:
        records = [
            r
            for r in records
            if r.timetable_slot_id is not None
            and slots_by_id.get(r.timetable_slot_id) is not None
            and slots_by_id[r.timetable_slot_id].subject_id == subject_id
        ]

    overall = _new_counts()
    per_period: dict[int, dict[str, int]] = {}
    per_day: dict[date_, dict[str, int]] = {}
    per_class: dict[int, dict[str, int]] = {}
    per_subject: dict[int, dict[str, int]] = {}
    per_student: dict[int, dict[str, int]] = {}
    # Split the window in half by date to derive a direction-of-travel per
    # student without a second query.
    midpoint = from_date + (to_date - from_date) / 2
    per_student_halves: dict[int, tuple[dict[str, int], dict[str, int]]] = {}

    for record in records:
        if record.status not in overall:
            continue
        overall[record.status] += 1
        per_day.setdefault(record.date, _new_counts())[record.status] += 1
        per_class.setdefault(record.class_id, _new_counts())[record.status] += 1
        per_student.setdefault(record.student_id, _new_counts())[record.status] += 1
        halves = per_student_halves.setdefault(record.student_id, (_new_counts(), _new_counts()))
        halves[1 if record.date > midpoint else 0][record.status] += 1
        slot = slots_by_id.get(record.timetable_slot_id) if record.timetable_slot_id else None
        if slot is not None:
            per_period.setdefault(slot.period_number, _new_counts())[record.status] += 1
            per_subject.setdefault(slot.subject_id, _new_counts())[record.status] += 1

    subject_names = {
        row.id: row.name for row in db.query(Subject.id, Subject.name).filter(Subject.id.in_(list(per_subject) or [-1]))
    }
    student_rows = {
        row.id: _display_name(row.full_name, row.email)
        for row in db.query(User.id, User.full_name, User.email).filter(
            User.id.in_(list(per_student) or [-1])
        )
    }
    student_class = {
        row.student_id: row.class_id
        for row in db.query(Enrollment.student_id, Enrollment.class_id).filter(
            Enrollment.student_id.in_(list(per_student) or [-1]),
            Enrollment.class_id.in_(scoped_class_ids or [-1]),
            Enrollment.is_primary.is_(True),
        )
    }

    students_out: list[StudentBucketOut] = []
    for student_id, counts in per_student.items():
        older, newer = per_student_halves[student_id]
        older_total = sum(older.values())
        newer_total = sum(newer.values())
        delta = (
            round(_pct(newer["present"], newer_total) - _pct(older["present"], older_total), 1)
            if older_total and newer_total
            else 0.0
        )
        cls_id = student_class.get(student_id)
        cls = classes_by_id.get(cls_id) if cls_id else None
        students_out.append(
            StudentBucketOut(
                student_id=student_id,
                name=student_rows.get(student_id, f"Student #{student_id}"),
                class_id=cls_id or 0,
                class_name=cls.name if cls else "—",
                section=cls.section if cls else None,
                trend_delta=delta,
                trend="rising" if delta > _TREND_BAND else "falling" if delta < -_TREND_BAND else "flat",
                **_bucket(counts),
            )
        )
    students_out.sort(key=lambda s: (s.present_pct, s.name.lower()))
    if below_pct is not None:
        students_out = [s for s in students_out if s.present_pct < below_pct]

    roster_size = (
        db.query(Enrollment.student_id)
        .filter(Enrollment.class_id.in_(scoped_class_ids or [-1]), Enrollment.is_primary.is_(True))
        .distinct()
        .count()
        if scoped_class_ids
        else 0
    )

    return AnalyticsResponse(
        from_date=from_date,
        to_date=to_date,
        overall=BucketOut(**_bucket(overall)),
        by_period=[
            PeriodBucketOut(period_number=p, **_bucket(c)) for p, c in sorted(per_period.items())
        ],
        by_day=[
            DayBucketOut(date=d, day_of_week=d.weekday(), **_bucket(c)) for d, c in sorted(per_day.items())
        ],
        by_class=[
            ClassBucketOut(
                class_id=cid,
                class_name=classes_by_id[cid].name if cid in classes_by_id else f"Class #{cid}",
                grade_level=classes_by_id[cid].grade_level if cid in classes_by_id else None,
                grade_label=classes_by_id[cid].grade_label if cid in classes_by_id else None,
                section=classes_by_id[cid].section if cid in classes_by_id else None,
                **_bucket(c),
            )
            for cid, c in sorted(per_class.items(), key=lambda kv: _pct(kv[1]["present"], sum(kv[1].values())))
        ],
        by_subject=[
            SubjectBucketOut(subject_id=sid, subject_name=subject_names.get(sid, f"Subject #{sid}"), **_bucket(c))
            for sid, c in sorted(per_subject.items())
        ],
        students=students_out,
        roster_size=roster_size,
        below_pct_count=len(students_out) if below_pct is not None else sum(
            1 for s in students_out if s.present_pct < 75
        ),
    )


# --- GET /attendance/my-records ----------------------------------------------


class MyRecordPeriodOut(BaseModel):
    timetable_slot_id: int | None
    period_number: int | None
    start_time: time_ | None
    end_time: time_ | None
    subject_name: str | None
    teacher_name: str | None
    status: str
    source: str
    marked_at: datetime


class MyRecordDayOut(BaseModel):
    date: date_
    day_of_week: int
    periods: list[MyRecordPeriodOut]
    present_count: int
    total_count: int
    present_pct: float


class MyRecordsResponse(BaseModel):
    student_id: int
    student_name: str
    class_id: int | None
    class_name: str | None
    from_date: date_
    to_date: date_
    summary: BucketOut
    days: list[MyRecordDayOut]
    """Newest day first - a student opening this wants today, not the start of
    the range."""


@router.get("/my-records", response_model=MyRecordsResponse)
def my_records(
    from_date: date_,
    to_date: date_,
    student_id: int | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One student's period-by-period attendance over a range.

    This is the student and parent portal view. A student always reads
    themselves and `student_id` is ignored for them; a parent must name one of
    their own linked children; a teacher is limited to students in classes they
    can access; admin/principal may read any student in their own school.
    """
    if from_date > to_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "from_date must be on or before to_date")

    if user.role == "student":
        target_id = user.id
    elif user.role == "parent":
        target_id = assert_parent_linked(db, user.id, student_id)
    elif user.role in ("admin", "principal", "teacher"):
        if student_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "student_id is required for staff roles")
        target_id = student_id
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Unknown role")

    student = db.query(User).filter(User.id == target_id).one_or_none()
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    # Staff may only read inside their own school, and a teacher only inside the
    # classes they can access - a student/parent has already been pinned to a
    # single id above, so this can't widen their access.
    if user.role in ("admin", "principal", "teacher"):
        if student.school_id != _require_school(user):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
        if user.role == "teacher":
            accessible = set(_teacher_accessible_class_ids(db, user.id))
            enrolled_in = {
                row.class_id
                for row in db.query(Enrollment.class_id).filter(
                    Enrollment.student_id == target_id, Enrollment.is_primary.is_(True)
                )
            }
            if not (accessible & enrolled_in):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your student")

    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == target_id, Enrollment.is_primary.is_(True))
        .first()
    )
    school_class = (
        db.query(SchoolClass).filter(SchoolClass.id == enrollment.class_id).one_or_none()
        if enrollment is not None
        else None
    )

    records = (
        db.query(AttendanceRecord)
        .filter(
            AttendanceRecord.student_id == target_id,
            AttendanceRecord.date >= from_date,
            AttendanceRecord.date <= to_date,
        )
        .all()
    )

    slot_ids = {r.timetable_slot_id for r in records if r.timetable_slot_id is not None}
    slots_by_id = {
        s.id: s for s in db.query(TimetableSlot).filter(TimetableSlot.id.in_(slot_ids or [-1]))
    } if slot_ids else {}
    subject_names = {
        row.id: row.name
        for row in db.query(Subject.id, Subject.name).filter(
            Subject.id.in_([s.subject_id for s in slots_by_id.values()] or [-1])
        )
    }
    teacher_names = {
        row.id: _display_name(row.full_name, row.email)
        for row in db.query(User.id, User.full_name, User.email).filter(
            User.id.in_([s.teacher_id for s in slots_by_id.values()] or [-1])
        )
    }

    overall = _new_counts()
    per_day: dict[date_, list[MyRecordPeriodOut]] = {}
    for record in records:
        if record.status in overall:
            overall[record.status] += 1
        slot = slots_by_id.get(record.timetable_slot_id) if record.timetable_slot_id else None
        per_day.setdefault(record.date, []).append(
            MyRecordPeriodOut(
                timetable_slot_id=record.timetable_slot_id,
                period_number=slot.period_number if slot else None,
                start_time=slot.start_time if slot else None,
                end_time=slot.end_time if slot else None,
                subject_name=subject_names.get(slot.subject_id) if slot else None,
                teacher_name=teacher_names.get(slot.teacher_id) if slot else None,
                status=record.status,
                source=record.source,
                marked_at=record.marked_at,
            )
        )

    days_out: list[MyRecordDayOut] = []
    for day in sorted(per_day, reverse=True):
        periods = sorted(per_day[day], key=lambda p: (p.period_number is None, p.period_number or 0))
        present = sum(1 for p in periods if p.status == "present")
        days_out.append(
            MyRecordDayOut(
                date=day,
                day_of_week=day.weekday(),
                periods=periods,
                present_count=present,
                total_count=len(periods),
                present_pct=_pct(present, len(periods)),
            )
        )

    return MyRecordsResponse(
        student_id=target_id,
        student_name=_display_name(student.full_name, student.email),
        class_id=school_class.id if school_class else None,
        class_name=school_class.name if school_class else None,
        from_date=from_date,
        to_date=to_date,
        summary=BucketOut(**_bucket(overall)),
        days=days_out,
    )
