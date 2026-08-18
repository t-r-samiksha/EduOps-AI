from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

CALENDAR_EVENT_TYPES = ("class", "exam", "assignment", "quiz", "school_event")


class CalendarEvent(Base):
    """A synchronized academic schedule, deadline, or exam event for a student or teacher."""

    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_type", "source_id", "start_time",
            name="uq_calendar_user_source_time",
        ),
        Index("ix_calendar_user_times", "user_id", "start_time", "end_time"),
        Index("ix_calendar_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # class, exam, assignment, quiz, school_event
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # timetable, exam, assignment, quiz, manual

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship()
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    subject: Mapped["Subject | None"] = relationship()
