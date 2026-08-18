"""Academic Calendar and Homework Schedule Router - Person B (Classroom & Academics).

Implements academic homework deadlines, synchronized calendar events,
and timetable-to-calendar integration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.calendar import CalendarEvent
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user
from app.services.scoping import assert_can_view_student_record
from app.services.calendar_sync_service import (
    get_homework_calendar_events,
    sync_user_calendar,
)

router = APIRouter(tags=["calendar"])


class CalendarEventOut(BaseModel):
    id: int
    user_id: int
    event_type: str
    title: str
    subject_id: int | None = None
    start_time: datetime
    end_time: datetime
    source_id: int | None = None
    source_type: str | None = None

    model_config = ConfigDict(from_attributes=True)


class HomeworkEventOut(BaseModel):
    id: str
    title: str
    type: str  # assignment, quiz, exam
    subject: str
    start: str
    end: str
    status: str  # upcoming, overdue, completed
    details: str | None = None
    max_marks: float | None = None


@router.get("/calendar/homework/{student_id}", response_model=list[HomeworkEventOut])
def get_student_homework_calendar(
    student_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve normalized academic deadlines (assignments, quizzes, exams) for a user.

    Named `{student_id}` for backwards compatibility, but the id may be any user: the
    service already branches on role and returns a TEACHER's own taught-class deadlines and
    an admin's school-wide ones (see get_homework_calendar_events).
    """
    # YOUR OWN CALENDAR NEEDS NO STUDENT-RECORD CHECK.
    #
    # assert_can_view_student_record answers "may I see this STUDENT's record", and its
    # teacher branch tests `student_id in students_taught_by(...)`. A teacher's own user id is
    # not one of their students, so a teacher asking for their own deadlines was rejected with
    # 403 - the page rendered "Could not load the academic calendar" for every teacher. Admins
    # slipped through only because that branch returns early.
    #
    # Checked before the gate rather than inside it: this is not a claim about student
    # records, so widening the shared student gate to admit self-reads would loosen it for
    # gradebooks, report cards and analytics too.
    if student_id != user.id:
        assert_can_view_student_record(db, user, student_id, what="calendar")

    return get_homework_calendar_events(db, student_id)


@router.get("/calendar/{user_id}", response_model=list[CalendarEventOut])
def get_user_calendar_events(
    user_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve synchronized academic schedule and deadlines for a user."""
    # Same self-read exemption as GET /calendar/homework/{student_id} above.
    if user_id != user.id:
        assert_can_view_student_record(db, user, user_id, what="calendar")

    # Run idempotent sync
    sync_user_calendar(db, user_id, start, end)

    query = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id)
    if start:
        query = query.filter(CalendarEvent.end_time >= start)
    if end:
        query = query.filter(CalendarEvent.start_time <= end)

    return query.order_by(CalendarEvent.start_time.asc()).all()


@router.post("/calendar/sync")
def trigger_calendar_sync(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Idempotently sync current user's timetable, exams, assignments, and quizzes."""
    result = sync_user_calendar(db, user.id)
    return {"status": "synced", **result}
