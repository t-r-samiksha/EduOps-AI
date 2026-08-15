from datetime import datetime, time

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    room_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default="classroom")
    """One of: classroom, lab, auditorium, ... — free-form, matched against
    SubjectRoomRequirement.room_type by the solver."""
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)

    school: Mapped["School"] = relationship()


class TeacherProfile(Base):
    """Scheduling-relevant profile data for a teacher, one row per teacher.
    Seed-populated the same way as TeacherSubject/TeacherUnavailability - no CRUD
    API exists for this (see CLAUDE.md's scope note on this deliberately staying
    seed-script-managed rather than becoming a general admin data-management
    feature nobody asked for)."""

    __tablename__ = "teacher_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    max_periods_per_week: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    """Default weekly teaching-load cap, overridable per-generation-run via
    POST /timetable/generate's teacher_selections[].max_periods_per_week_override."""

    teacher: Mapped["User"] = relationship()


class TeacherSubject(Base):
    """Which subjects a teacher is qualified to teach. Solver input: a class-subject
    period can only be assigned to a teacher who has a row here for that subject."""

    __tablename__ = "teacher_subjects"
    __table_args__ = (UniqueConstraint("teacher_id", "subject_id", name="uq_teacher_subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)

    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])
    subject: Mapped["Subject"] = relationship()


class SubjectRoomRequirement(Base):
    """Constrains which room_type a subject's periods must be scheduled in (e.g.
    Science -> lab). Absence of a row for a subject means any room type is fine."""

    __tablename__ = "subject_room_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), unique=True, nullable=False)
    room_type: Mapped[str] = mapped_column(String(30), nullable=False)

    subject: Mapped["Subject"] = relationship()


class TeacherUnavailability(Base):
    """Sparse exceptions to a teacher's default availability - a row here means the
    teacher is NOT available at that day/period. Absence of a row means available."""

    __tablename__ = "teacher_unavailabilities"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "day_of_week", "period_number", "academic_year", name="uq_teacher_unavailability_slot"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    """0 = Monday ... 6 = Sunday."""
    period_number: Mapped[int] = mapped_column(Integer, nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)

    teacher: Mapped["User"] = relationship()


class ClassSubjectRequirement(Base):
    """How many periods/week a class needs of a subject. Solver input: drives how
    many TimetableSlot rows must be generated per class-subject pair."""

    __tablename__ = "class_subject_requirements"
    __table_args__ = (
        UniqueConstraint("class_id", "subject_id", "academic_year", name="uq_class_subject_requirement"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    periods_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)

    school_class: Mapped["SchoolClass"] = relationship()
    subject: Mapped["Subject"] = relationship()


class TimetableSlot(Base):
    """A single scheduled period: one subject, taught by one teacher, to one class,
    in one room, on one day/period. Generated in bulk by the CP-SAT solver, or
    created/edited individually via manual admin edits."""

    __tablename__ = "timetable_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    """0 = Monday ... 6 = Sunday."""
    period_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(nullable=False)
    end_time: Mapped[time] = mapped_column(nullable=False)

    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    subject: Mapped["Subject"] = relationship()
    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])
    school_class: Mapped["SchoolClass"] = relationship()
    room: Mapped["Room"] = relationship()
