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


def _norm(value):
    """Compares stored vs derived field values across the naive/aware boundary.

    calendar_events.start_time is timestamptz, so Postgres hands back aware datetimes
    while a freshly-derived value can be naive (Exam combines a date with a time-of-day
    column). Comparing those raises TypeError; comparing them as strings would report every
    event as changed on every sync. Naive is treated as UTC, which is what _to_utc assumes.
    """
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _reconcile(
    db: Session, user: User, source_type: str, desired: dict[int, dict]
) -> tuple[int, int, int]:
    """Makes this user's events for one source_type match `desired` exactly.

    THREE-WAY, not insert-only. The previous version only ever added rows, so:
      - a rescheduled deadline kept its OLD calendar slot forever (the row existed, so the
        `if not existing` branch was skipped and nothing updated it);
      - a deleted assignment or quiz left its event behind permanently;
      - a student unenrolled from a class kept seeing that class's work, because
        entitlement is expressed by `desired` being rebuilt from current enrollment.

    Only rows matching this exact (user, source_type) are considered, so manually-created
    events - which carry no source_type this function owns - are never touched.
    """
    existing = {
        ev.source_id: ev
        for ev in db.query(CalendarEvent)
        .filter(CalendarEvent.user_id == user.id, CalendarEvent.source_type == source_type)
        .all()
    }
    created = updated = deleted = 0

    for source_id, fields in desired.items():
        ev = existing.pop(source_id, None)
        if ev is None:
            db.add(
                CalendarEvent(
                    school_id=user.school_id,
                    user_id=user.id,
                    source_id=source_id,
                    source_type=source_type,
                    **fields,
                )
            )
            created += 1
            continue
        drift = [k for k, v in fields.items() if _norm(getattr(ev, k)) != _norm(v)]
        if drift:
            for k in drift:
                setattr(ev, k, fields[k])
            updated += 1

    # Whatever is left in `existing` has no live source row (or the user lost access to
    # it), so it is stale by definition.
    for ev in existing.values():
        db.delete(ev)
        deleted += 1

    return created, updated, deleted


def sync_user_calendar(
    db: Session,
    user_id: int,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> dict[str, int]:
    """Reconciles a user's calendar against assignments, quizzes and exams.

    Idempotent AND convergent: reruns after a source row is edited or deleted bring the
    calendar back in line, rather than only ever adding. See _reconcile.
    """
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        # Same keys as the success path. This used to return {"created","updated"} while
        # the success path returned {"synced_events"}, so a caller reading either key
        # raised KeyError on whichever branch it did not expect.
        return {"synced_events": 0, "created": 0, "updated": 0, "deleted": 0}

    now = datetime.now(timezone.utc)
    # start_date/end_date are accepted for call-site compatibility but deliberately do NOT
    # filter the source queries. GET /calendar/{user_id} already windows its own read, and
    # narrowing the sources here would make _reconcile treat every event outside the window
    # as stale and delete it - so a default-window sync would erase the far-future events a
    # wider sync had just created.
    _ = (start_date, end_date)

    created = updated = deleted = 0

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

    desired_assignments = {}
    for a in assignments:
        dl_utc = _to_utc(a.deadline)
        desired_assignments[a.id] = {
            "event_type": "assignment",
            "title": f"Due: {a.title}",
            "subject_id": a.subject_id,
            "start_time": dl_utc - timedelta(hours=1),  # 1-hour block before the deadline
            "end_time": dl_utc,
        }
    c, u, d = _reconcile(db, user, "assignment", desired_assignments)
    created += c
    updated += u
    deleted += d

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

    desired_quizzes = {}
    for q in quizzes:
        start_t = _to_utc(q.available_from) if q.available_from else now
        end_t = _to_utc(q.available_until) if q.available_until else (start_t + timedelta(hours=2))
        desired_quizzes[q.id] = {
            "event_type": "quiz",
            "title": f"Quiz: {q.title}",
            "subject_id": q.subject_id,
            "start_time": start_t,
            "end_time": end_t,
        }
    c, u, d = _reconcile(db, user, "quiz", desired_quizzes)
    created += c
    updated += u
    deleted += d

    # 3. Sync Exams
    exams = db.query(Exam).filter(Exam.school_id == user.school_id).all()
    desired_exams = {}
    for ex in exams:
        # Exam.start_time/end_time are TIME-of-day columns and exam_date holds the
        # day; calendar_events.start_time is timestamptz. Combine them, or the INSERT
        # fails with a DatatypeMismatch (time vs timestamp with time zone).
        desired_exams[ex.id] = {
            "event_type": "exam",
            # Exam has no `name` column - the readable identity is its
            # subject plus exam_type ("mid_term"/"unit_test"/...).
            "title": (
                f"Exam: {ex.subject.name if ex.subject else 'Unknown subject'}"
                + (f" ({ex.exam_type.replace('_', ' ')})" if ex.exam_type else "")
            ),
            "subject_id": ex.subject_id,
            "start_time": _to_utc(datetime.combine(ex.exam_date, ex.start_time)),
            "end_time": _to_utc(datetime.combine(ex.exam_date, ex.end_time)),
        }
    c, u, d = _reconcile(db, user, "exam", desired_exams)
    created += c
    updated += u
    deleted += d

    db.commit()
    # synced_events is retained as the created-count for callers that already read it.
    return {
        "synced_events": created,
        "created": created,
        "updated": updated,
        "deleted": deleted,
    }


def get_homework_calendar_events(
    db: Session,
    user_id: int,
) -> list[dict[str, Any]]:
    """Aggregates normalized academic deadlines (assignments, quizzes, exams) for homework calendar."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return []

    from app.models.class_ import SchoolClass
    from app.models.parent_student import ParentStudent
    from app.routers.assignments import _classes_taught_by
    from sqlalchemy import or_

    class_ids = []
    if user.role.name == "student":
        class_ids = [
            row.class_id
            for row in db.query(Enrollment.class_id).filter(Enrollment.student_id == user.id).all()
        ]
    elif user.role.name == "teacher":
        class_ids = list(_classes_taught_by(db, user.id))
    elif user.role.name == "parent":
        child_ids = [row.student_id for row in db.query(ParentStudent.student_id).filter(ParentStudent.parent_id == user.id).all()]
        class_ids = [row.class_id for row in db.query(Enrollment.class_id).filter(Enrollment.student_id.in_(child_ids)).all()]
    else:
        class_ids = [c.id for c in db.query(SchoolClass.id).filter(SchoolClass.school_id == user.school_id).all()]

    events = []
    now = datetime.now(timezone.utc)

    # Assignments
    assign_query = db.query(Assignment)
    if user.role.name == "teacher":
        conds = [Assignment.teacher_id == user.id]
        if class_ids:
            conds.append(Assignment.class_id.in_(class_ids))
        assignments = assign_query.filter(or_(*conds)).all()
    else:
        assignments = assign_query.filter(Assignment.class_id.in_(class_ids)).all() if class_ids else []
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
    quiz_query = db.query(Quiz)
    if user.role.name == "teacher":
        conds = [Quiz.teacher_id == user.id]
        if class_ids:
            conds.append(Quiz.class_id.in_(class_ids))
        quizzes = quiz_query.filter(or_(*conds)).all()
    else:
        quizzes = quiz_query.filter(Quiz.class_id.in_(class_ids)).all() if class_ids else []
        
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
    exams = db.query(Exam).filter(Exam.class_id.in_(class_ids)).all() if class_ids else []
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
