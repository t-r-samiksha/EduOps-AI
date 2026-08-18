"""Assignment service - Person B (Classroom & Academics).

Handles assignment lifecycle, submission tracking, deadline validation,
grading calculation, and scheduled missing-submission detection.
Integrates with Person A (Risk Scoring) and Person C (Notifications).
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.assignment import Assignment, AssignmentSubmission
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.notification import Notification
from app.models.parent_student import ParentStudent
from app.models.subject import Subject
from app.models.user import User
from app.services.notify import dispatch_bulk, dispatch_notification


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_enrolled_student_ids(db: Session, class_id: int) -> list[int]:
    """Retrieve all student IDs enrolled in the given class section."""
    return [
        row.student_id
        for row in db.query(Enrollment.student_id)
        .filter(Enrollment.class_id == class_id)
        .distinct()
        .all()
    ]


def get_assignment_stats(db: Session, assignment: Assignment) -> dict:
    """Calculate submission counts and progress for an assignment."""
    enrolled_count = len(get_enrolled_student_ids(db, assignment.class_id))
    submissions = (
        db.query(AssignmentSubmission)
        .filter(AssignmentSubmission.assignment_id == assignment.id)
        .all()
    )

    submitted_count = sum(1 for s in submissions if s.status in ("submitted", "late", "graded"))
    late_count = sum(1 for s in submissions if s.status == "late")
    graded_count = sum(1 for s in submissions if s.status == "graded" or s.grade is not None)
    
    # Missing = enrolled students who either have a missing record or haven't submitted past deadline
    now = datetime.now(timezone.utc)
    is_past_deadline = _to_utc(assignment.deadline) <= now
    explicit_missing = sum(1 for s in submissions if s.status == "missing")
    missing_count = explicit_missing + (max(0, enrolled_count - len(submissions)) if is_past_deadline else 0)

    grades = [s.grade for s in submissions if s.grade is not None]
    average_grade = round(sum(grades) / len(grades), 1) if grades else None

    return {
        "enrolled_count": enrolled_count,
        "submitted_count": submitted_count,
        "late_count": late_count,
        "missing_count": missing_count,
        "graded_count": graded_count,
        "average_grade": average_grade,
    }


def get_student_academic_risk_factors(db: Session, student_id: int) -> dict:
    """Expose assignment stats for Person A Early-Warning / Risk scoring.
    Returns counts of missing assignments, submitted assignments, and average grade.
    """
    submissions = (
        db.query(AssignmentSubmission)
        .filter(AssignmentSubmission.student_id == student_id)
        .all()
    )

    missing_count = sum(1 for s in submissions if s.status == "missing")
    late_count = sum(1 for s in submissions if s.status == "late")
    graded = [s.grade for s in submissions if s.grade is not None]
    avg_grade = round(sum(graded) / len(graded), 1) if graded else None

    return {
        "student_id": student_id,
        "total_submissions": len(submissions),
        "missing_assignments": missing_count,
        "late_submissions": late_count,
        "average_assignment_grade": avg_grade,
    }


DEADLINE_SCAN_LOOKBACK_DAYS = 30
"""How far back to look for passed deadlines.

Unbounded, this scanned EVERY assignment ever created on every run. Two problems beyond
the query cost: a student who joins a class in March would be marked missing - and
notified - for every assignment set since September, and the scan grows forever."""


def _already_notified(db: Session, *, user_id: int, source_type: str, source_id: int) -> bool:
    """Whether this exact notification has already been sent.

    IDEMPOTENCY GUARD. The missing-submission path is self-limiting (it writes a
    status="missing" row, so the student is no longer "without a submission" next run), but
    the 24h reminder path had nothing: it dispatched to every unsubmitted student on every
    invocation. Nightly cadence hid that, since a 24-hour window catches each assignment on
    exactly one run - but a manual run on the same night, or any cadence change, would
    re-notify the whole class. The failure mode of a nudge feature is spam, so the guard is
    on the notification itself rather than on the schedule.
    """
    return (
        db.query(Notification.id)
        .filter(
            Notification.user_id == user_id,
            Notification.source_type == source_type,
            Notification.source_id == source_id,
        )
        .first()
        is not None
    )


def detect_assignment_deadlines_and_missing(db: Session) -> dict:
    """Scheduled task to detect passed and approaching deadlines.
    - Marks missing submissions for passed deadlines.
    - Sends approaching deadline reminders (<= 24 hours).
    - Triggers notifications to students and parents.

    Idempotent: safe to run twice in one night. See _already_notified.
    """
    now = datetime.now(timezone.utc)
    one_day_ahead = now + timedelta(hours=24)
    scan_since = now - timedelta(days=DEADLINE_SCAN_LOOKBACK_DAYS)

    missing_marked = 0
    reminders_sent = 0

    # 1. Passed deadlines -> find missing students
    past_assignments = (
        db.query(Assignment)
        .filter(Assignment.deadline <= now, Assignment.deadline >= scan_since)
        .all()
    )

    for a in past_assignments:
        enrolled_ids = get_enrolled_student_ids(db, a.class_id)
        existing_sub_student_ids = {
            s.student_id
            for s in db.query(AssignmentSubmission.student_id)
            .filter(AssignmentSubmission.assignment_id == a.id)
            .all()
        }

        missing_ids = [sid for sid in enrolled_ids if sid not in existing_sub_student_ids]
        for sid in missing_ids:
            # Create missing record
            missing_sub = AssignmentSubmission(
                assignment_id=a.id,
                student_id=sid,
                status="missing",
            )
            db.add(missing_sub)
            missing_marked += 1

            # Dispatch missing alert to student
            dispatch_notification(
                db,
                user_id=sid,
                source_type="assignment_missing",
                title=f"Missing Assignment: {a.title}",
                body=f"The deadline for '{a.title}' has passed and no submission was received.",
                priority="urgent",
                source_id=a.id,
            )

            # Alert parents if linked
            parent_ids = [
                row.parent_id
                for row in db.query(ParentStudent.parent_id).filter(ParentStudent.student_id == sid).all()
            ]
            if parent_ids:
                dispatch_bulk(
                    db,
                    user_ids=parent_ids,
                    source_type="assignment_missing",
                    title=f"Alert: Missing Assignment ({a.title})",
                    body=f"Your child missed the submission deadline for '{a.title}'.",
                    priority="important",
                    source_id=a.id,
                )

    # 2. Approaching deadlines -> 24h reminder
    upcoming_assignments = (
        db.query(Assignment)
        .filter(Assignment.deadline > now, Assignment.deadline <= one_day_ahead)
        .all()
    )

    for a in upcoming_assignments:
        enrolled_ids = get_enrolled_student_ids(db, a.class_id)
        submitted_ids = {
            s.student_id
            for s in db.query(AssignmentSubmission.student_id)
            .filter(
                AssignmentSubmission.assignment_id == a.id,
                AssignmentSubmission.status.in_(("submitted", "late", "graded")),
            )
            .all()
        }

        unsubmitted_ids = [
            sid
            for sid in enrolled_ids
            if sid not in submitted_ids
            and not _already_notified(
                db, user_id=sid, source_type="assignment_reminder", source_id=a.id
            )
        ]
        if unsubmitted_ids:
            dispatch_bulk(
                db,
                user_ids=unsubmitted_ids,
                source_type="assignment_reminder",
                title=f"Deadline Approaching: {a.title}",
                body=f"Assignment '{a.title}' is due on {a.deadline.strftime('%b %d, %H:%M UTC')}. Please submit on time.",
                priority="important",
                source_id=a.id,
            )
            reminders_sent += len(unsubmitted_ids)

    db.commit()
    return {"missing_marked": missing_marked, "reminders_sent": reminders_sent}
