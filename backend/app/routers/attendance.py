from datetime import date as date_
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attendance import AttendanceRecord, FaceEmbedding
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
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


class MarkResponse(BaseModel):
    timetable_slot_id: int
    class_id: int
    date: date_
    records_created: int
    matches: list[FaceMatchOut]
    unmatched_faces: list[UnmatchedFaceOut]


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

    return MarkResponse(
        timetable_slot_id=slot.id,
        class_id=slot.class_id,
        date=effective_date,
        records_created=records_created,
        matches=matches_out,
        unmatched_faces=unmatched_out,
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
    user: CurrentUser = Depends(require_role("admin", "teacher")),
    db: Session = Depends(get_db),
):
    if body.status not in VALID_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"status must be one of {VALID_STATUSES}")

    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attendance record not found")

    if user.role == "teacher" and record.class_id not in _teacher_class_ids(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your class")

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
        detail={"previous_status": previous_status, "new_status": body.status},
    )
    db.commit()
    db.refresh(record)

    return AttendanceRecordOut.model_validate(record)
