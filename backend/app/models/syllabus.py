from datetime import date as date_
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SyllabusPlan(Base):
    """The pacing plan for one class+subject+academic_year: a flat total_units count
    expected to be covered across [term_start_date, term_end_date]. Deliberately no
    week-by-week breakdown - matches how a syllabus is normally issued (a fixed list
    of topics to get through by a fixed date), not a detailed scheme-of-work with
    per-topic scheduling. See services/syllabus_pace.py for the pacing-curve math
    this implies (linear expected-progress, documented there as a real
    simplification)."""

    __tablename__ = "syllabus_plans"
    __table_args__ = (UniqueConstraint("class_id", "subject_id", "academic_year", name="uq_syllabus_plan_class_subject_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    total_units: Mapped[int] = mapped_column(Integer, nullable=False)
    """Total number of topics/units this class+subject's syllabus expects to cover."""
    term_start_date: Mapped[date_] = mapped_column(nullable=False)
    term_end_date: Mapped[date_] = mapped_column(nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    school_class: Mapped["SchoolClass"] = relationship()
    subject: Mapped["Subject"] = relationship()
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])


class SyllabusCheckpoint(Base):
    """One logged unit of ACTUAL progress against a SyllabusPlan - "this topic was
    covered". `sequence_number` is a human-readable position label only, NOT assumed
    contiguous or in-order - a teacher may legitimately log topics out of syllabus
    order (revisiting, reordering for exam prep, etc.). services/syllabus_pace.py
    therefore measures progress by COUNTING checkpoints logged against a plan, never
    by reading the max sequence_number reached."""

    __tablename__ = "syllabus_checkpoints"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("syllabus_plans.id"), nullable=False)
    topic_label: Mapped[str] = mapped_column(String(255), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    logged_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    plan: Mapped["SyllabusPlan"] = relationship()
    logger: Mapped["User"] = relationship(foreign_keys=[logged_by])


class AnomalyFlag(Base):
    """A detected operational anomaly, feeding the Admin Command Center as a 7th
    alert source (see services/alert_aggregator.py) - shaped to map cleanly onto that
    module's Alert dataclass. Populated by scripts/run_nightly_syllabus_anomaly_scan.py
    running services/anomaly_detector.py (playbook 11.4's four categories:
    submission_rate/attendance_drop/document_backlog/teacher_overload) AND
    services/syllabus_pace.py's drift detection (playbook 11.3) - both land in this
    one table rather than two parallel ones, since both are the same underlying
    concept ("an admin needs to know something operational is off"), and sharing a
    table means one detection job, one alert-source registration, and one resolve
    mechanism instead of two. This is a deliberate scope choice beyond the task's
    literal four-category list - documented here rather than silently done.

    `entity_id` is NOT a foreign key at the database level: which table it refers to
    depends on `entity_type` (documents/users/classes/...), i.e. it's genuinely
    polymorphic - the same reason Alert.entity_id in alert_aggregator.py is a plain
    dataclass field, not a typed reference. Referential integrity for it is enforced
    in application code (services/anomaly_detector.py, syllabus_pace.py), not the DB.

    Resolve mechanics deliberately mirror RiskFlag exactly (status/resolved_by/
    resolved_at) - see routers/admin_alerts.py's resolve routing, which treats
    risk_flag and anomaly_flag identically for exactly this reason."""

    __tablename__ = "anomaly_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    """One of: submission_rate, attendance_drop, document_backlog, teacher_overload,
    syllabus_drift."""
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    """Not a DB-enforced FK target - see class docstring. E.g. "classes", "users", "documents"."""
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    """One of: normal, urgent - matches alert_aggregator.SEVERITY_LEVELS exactly."""
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False)
    """Free-form structured detail, including a human-readable "message" key used
    directly by alert_aggregator.py rather than re-deriving one from `type`."""
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    """One of: open, resolved."""
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    resolver: Mapped["User | None"] = relationship(foreign_keys=[resolved_by])
