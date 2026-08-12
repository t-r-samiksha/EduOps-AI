from datetime import date as date_, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

FACE_EMBEDDING_DIM = 128
"""face_recognition's face_encodings() output size (dlib's ResNet embedding)."""


class AttendanceRecord(Base):
    """One student's attendance for one period. `source` distinguishes how it was
    captured; CV/RFID rows for the same student+slot+date are cross-referenced by
    AttendanceReconciliation when they disagree."""

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "timetable_slot_id", "date", "source", name="uq_attendance_student_slot_date_source"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    timetable_slot_id: Mapped[int | None] = mapped_column(ForeignKey("timetable_slots.id"))
    date: Mapped[date_] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    """One of: present, absent, late."""
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    """One of: cv, rfid, manual."""
    marked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confidence_score: Mapped[float | None] = mapped_column(Float)
    """Recognition confidence in [0, 1], set for source=cv rows only."""
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    school_class: Mapped["SchoolClass"] = relationship()
    timetable_slot: Mapped["TimetableSlot | None"] = relationship()
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by])


class FaceEmbedding(Base):
    """A reference face embedding for a student. A student may have several rows
    (re-enrollment, multiple reference photos) - recognize_faces matches against
    the best match across all of a class's enrolled embeddings."""

    __tablename__ = "face_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(FACE_EMBEDDING_DIM), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped["User"] = relationship()


class AttendanceReconciliation(Base):
    """Flags a student+slot+date where CV and RFID attendance disagree (or one
    source is missing entirely) for manual review. Populated by the reconciliation
    job - not written yet; RFID ingestion (and therefore reconciliation itself) is
    a later session, this table just exists so the schema doesn't need revisiting."""

    __tablename__ = "attendance_reconciliations"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    timetable_slot_id: Mapped[int] = mapped_column(ForeignKey("timetable_slots.id"), nullable=False)
    date: Mapped[date_] = mapped_column(nullable=False)
    cv_record_id: Mapped[int | None] = mapped_column(ForeignKey("attendance_records.id"))
    rfid_record_id: Mapped[int | None] = mapped_column(ForeignKey("attendance_records.id"))
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    """One of: status_mismatch, cv_only, rfid_only."""
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    """One of: pending, resolved."""
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    timetable_slot: Mapped["TimetableSlot"] = relationship()
    cv_record: Mapped["AttendanceRecord | None"] = relationship(foreign_keys=[cv_record_id])
    rfid_record: Mapped["AttendanceRecord | None"] = relationship(foreign_keys=[rfid_record_id])
    resolver: Mapped["User | None"] = relationship(foreign_keys=[resolved_by])
