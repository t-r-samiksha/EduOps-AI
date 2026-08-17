"""Academic Calendar and Timetable-to-Calendar Sync Service - Person B (Classroom & Academics).

Idempotently synchronizes:
1. Person A Timetable Slots (`TimetableSlot`)
2. Exam Schedules (`Exam`, `SeatingAssignment`)
3. Assignment Deadlines (`Assignment`)
4. Online Quiz Windows (`Quiz`)
into unified `calendar_events` for students and teachers.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from sqlalchemy.orm import Session

from app.models.assignment import Assignment
from app.models.calendar import CalendarEvent
from app.models.enrollment import Enrollment
from app.models.exams import Exam, SeatingAssignment
from app.models.quiz import Quiz
from app.models.timetable import TimetableSlot
from app.models.user import User


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sync_user_calendar(
    db: Session,
    user_id: int,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> dict[str, int]:
    """Idempotently syncs timetable slots, exams, assignments, and quizzes for a user."""
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        return {"created": 0, "updated": 0}

    now = datetime.now(timezone.utc)
    start = start_date or (now - timedelta(days=7))
    end = end_date or (now + timedelta(days=60))

    events_synced = 0

    # 1. Sync Assignment Deadlines
    if user.role.name == "student":
        student_class_ids = [
            row.class_id
            for row in db.query(Enrollment.class_id).filter(Enrollment.student_id == user.id).all()
        ]
        assignments = (
            db.query(Assignment)
            .filter(Assignment.class_id.in_(student_class_ids))
            .all()
        )
    else:
        assignments = (
            db.query(Assignment)
            .filter(Assignment.teacher_id == user.id)
            .all()
        )

    for a in assignments:
        dl_utc = _to_utc(a.deadline)
        # 1-hour event block for deadline
        existing = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user.id,
                CalendarEvent.source_type == "assignment",
                CalendarEvent.source_id == a.id,
            )
            .first()
        )
        if not existing:
            ev = CalendarEvent(
                school_id=user.school_id,
                user_id=user.id,
                event_type="assignment",
                title=f"Due: {a.title}",
                subject_id=a.subject_id,
                start_time=dl_utc - timedelta(hours=1),
                end_time=dl_utc,
                source_id=a.id,
                source_type="assignment",
            )
            db.add(ev)
            events_synced += 1

    # 2. Sync Quiz Windows
    if user.role.name == "student":
        quizzes = (
            db.query(Quiz)
            .filter(Quiz.class_id.in_(student_class_ids))
            .all()
        )
    else:
        quizzes = (
            db.query(Quiz)
            .filter(Quiz.teacher_id == user.id)
            .all()
        )

    for q in quizzes:
        start_t = _to_utc(q.available_from) if q.available_from else (now)
        end_t = _to_utc(q.available_until) if q.available_until else (start_t + timedelta(hours=2))

        existing = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user.id,
                CalendarEvent.source_type == "quiz",
                CalendarEvent.source_id == q.id,
            )
            .first()
        )
        if not existing:
            ev = CalendarEvent(
                school_id=user.school_id,
                user_id=user.id,
                event_type="quiz",
                title=f"Quiz: {q.title}",
                subject_id=q.subject_id,
                start_time=start_t,
                end_time=end_t,
                source_id=q.id,
                source_type="quiz",
            )
            db.add(ev)
            events_synced += 1

    # 3. Sync Exams
    exams = db.query(Exam).filter(Exam.school_id == user.school_id).all()
    for ex in exams:
        ex_start = _to_utc(ex.start_time)
        ex_end = _to_utc(ex.end_time)
        existing = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.user_id == user.id,
                CalendarEvent.source_type == "exam",
                CalendarEvent.source_id == ex.id,
            )
            .first()
        )
        if not existing:
            ev = CalendarEvent(
                school_id=user.school_id,
                user_id=user.id,
                event_type="exam",
                title=f"Exam: {ex.name}",
                subject_id=ex.subject_id,
                start_time=ex_start,
                end_time=ex_end,
                source_id=ex.id,
                source_type="exam",
            )
            db.add(ev)
            events_synced += 1

    db.commit()
    return {"synced_events": events_synced}


def get_homework_calendar_events(
    db: Session,
    student_id: int,
) -> list[dict[str, Any]]:
    """Aggregates normalized academic deadlines (assignments, quizzes, exams) for homework calendar."""
    student_class_ids = [
        row.class_id
        for row in db.query(Enrollment.class_id).filter(Enrollment.student_id == student_id).all()
    ]

    events = []
    now = datetime.now(timezone.utc)

    # Assignments
    assignments = (
        db.query(Assignment)
        .filter(Assignment.class_id.in_(student_class_ids))
        .all()
    )
    for a in assignments:
        dl_utc = _to_utc(a.deadline)
        is_overdue = dl_utc < now
        events.append({
            "id": f"assignment_{a.id}",
            "title": a.title,
            "type": "assignment",
            "subject": a.subject.name if a.subject else "General",
            "start": (dl_utc - timedelta(hours=1)).isoformat(),
            "end": dl_utc.isoformat(),
            "status": "overdue" if is_overdue else "upcoming",
            "details": a.description,
            "max_marks": a.max_marks,
        })

    # Quizzes
    quizzes = (
        db.query(Quiz)
        .filter(Quiz.class_id.in_(student_class_ids))
        .all()
    )
    for q in quizzes:
        start_t = _to_utc(q.available_from) if q.available_from else now
        end_t = _to_utc(q.available_until) if q.available_until else (start_t + timedelta(hours=2))
        events.append({
            "id": f"quiz_{q.id}",
            "title": q.title,
            "type": "quiz",
            "subject": q.subject.name if q.subject else "General",
            "start": start_t.isoformat(),
            "end": end_t.isoformat(),
            "status": "overdue" if end_t < now else "upcoming",
            "details": f"Duration: {q.duration_minutes} mins",
        })

    # Exams
    exams = db.query(Exam).filter(Exam.class_id.in_(student_class_ids)).all() if student_class_ids else []
    for ex in exams:
        ex_start = datetime.combine(ex.exam_date, ex.start_time).replace(tzinfo=timezone.utc)
        ex_end = datetime.combine(ex.exam_date, ex.end_time).replace(tzinfo=timezone.utc)
        events.append({
            "id": f"exam_{ex.id}",
            "title": f"{ex.subject.name if ex.subject else 'Subject'} Exam ({ex.exam_type or 'Final'})",
            "type": "exam",
            "subject": ex.subject.name if ex.subject else "Exam",
            "start": ex_start.isoformat(),
            "end": ex_end.isoformat(),
            "status": "completed" if ex_end < now else "upcoming",
            "details": f"Total marks: {ex.total_marks or 'N/A'}",
        })

    return events
