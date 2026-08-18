"""Student Personal Analytics Service - Person B (Classroom & Academics).

Aggregates:
- Attendance percentage (Person A AttendanceRecord)
- Subject-wise scores and GPA (Gradebook)
- Coursework assignment metrics
- Quiz performance metrics
- Person A Early-Warning Risk Flag status (`RiskFlag`)
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from app.models.assignment import AssignmentSubmission
from app.models.attendance import AttendanceRecord
from app.models.gradebook import GradebookEntry
from app.models.quiz import QuizAttempt
from app.models.risk import RiskFlag
from app.models.subject import Subject
from app.models.user import User
from app.services.attendance_stats import lookback_snapshot
from app.services.gradebook_service import get_student_gradebook_summary
from scripts.run_nightly_risk_scoring import ATTENDANCE_LOOKBACK_DAYS


def get_student_personal_analytics(
    db: Session,
    student_id: int,
    term: str = "Term 1",
) -> dict[str, Any]:
    """Generates a multi-dimensional analytics profile for a student."""
    student = db.query(User).filter(User.id == student_id).one_or_none()
    if not student:
        raise ValueError("Student not found")

    # 1. Attendance Metrics (Person A)
    # M-2: was ALL-time with `late` counted as present and 100.0 for a student with no
    # records - three ways to disagree with the parent portal about the same child. Now
    # the shared helper on the same 30-day window the portal and risk scorer use.
    att = lookback_snapshot(db, student_id, ATTENDANCE_LOOKBACK_DAYS)
    total_days = att.total_records
    present_days = att.present_count
    absent_days = att.absent_count
    attendance_pct = att.present_pct  # None when there are no records - not 100.0

    # 2. Gradebook & Subject-wise Performance
    gradebook_summary = get_student_gradebook_summary(db, student_id, term)

    # 3. Assignment Performance
    submissions = (
        db.query(AssignmentSubmission)
        .filter(AssignmentSubmission.student_id == student_id)
        .all()
    )
    submitted_count = sum(1 for s in submissions if s.status in ("submitted", "graded"))
    late_count = sum(1 for s in submissions if s.status == "late")
    missing_count = sum(1 for s in submissions if s.status == "missing")
    assignment_grades = [s.grade for s in submissions if s.grade is not None]
    avg_assignment_score = (
        round(sum(assignment_grades) / len(assignment_grades), 1) if assignment_grades else None
    )

    # 4. Quiz Performance
    quiz_attempts = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.student_id == student_id)
        .all()
    )
    quiz_scores = [a.score for a in quiz_attempts]
    avg_quiz_score = round(sum(quiz_scores) / len(quiz_scores), 1) if quiz_scores else None

    # 5. Person A Risk Flag Status
    risk_flags = (
        db.query(RiskFlag)
        .filter(RiskFlag.student_id == student_id, RiskFlag.resolved_at.is_(None))
        .all()
    )
    is_at_risk = len(risk_flags) > 0
    # RiskFlag.reasons is a JSONB list[str] (one flag can carry several reasons),
    # not a scalar - flatten so this stays list[str] for the client.
    risk_reasons = [r for f in risk_flags for r in (f.reasons or [])] if is_at_risk else []

    # 6. Trend data (simulated month-by-month progress curve)
    trend_data = [
        {"month": "Sep", "score": 74, "attendance": 95},
        {"month": "Oct", "score": 78, "attendance": 92},
        {"month": "Nov", "score": 82, "attendance": 96},
        {"month": "Dec", "score": 85, "attendance": 90},
        {"month": "Jan", "score": round(gradebook_summary["term_average"] or 84, 1), "attendance": attendance_pct or 0},
    ]

    return {
        "student_id": student_id,
        "student_name": student.full_name or student.email,
        "term": term,
        "attendance": {
            "percentage": attendance_pct,
            "total_days": total_days,
            "present_days": present_days,
            "absent_days": absent_days,
            "late_days": att.late_count,
            # The window this figure covers, so the UI can label it rather than showing
            # a bare percentage that looks like it disagrees with the report card.
            "window_label": att.label,
        },
        "gradebook": gradebook_summary,
        "assignments": {
            "total_submissions": len(submissions),
            "submitted_count": submitted_count,
            "late_count": late_count,
            "missing_count": missing_count,
            "average_score": avg_assignment_score,
        },
        "quizzes": {
            "total_attempts": len(quiz_attempts),
            "average_score": avg_quiz_score,
        },
        "risk_status": {
            "is_at_risk": is_at_risk,
            "flags_count": len(risk_flags),
            "reasons": risk_reasons,
            "banner_message": (
                "⚠️ Your academic performance may need attention."
                if is_at_risk
                else "✅ Academic performance is in good standing."
            ),
        },
        "trend": trend_data,
    }
