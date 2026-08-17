"""Quiz and Auto-Grading Service - Person B (Classroom & Academics).

Handles quiz lifecycle, question validation, MCQ auto-grading, timer checks,
per-question performance breakdown, and Person C Teacher Assistant drafting hook.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from sqlalchemy.orm import Session

from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
from app.models.subject import Subject
from app.models.user import User


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def grade_quiz_attempt(
    quiz: Quiz,
    submitted_answers: dict[str, str],
) -> tuple[float, float, dict[str, Any]]:
    """Auto-grades multiple choice answers against quiz questions immediately.
    Returns: (score_obtained, total_marks, breakdown_dict)
    """
    total_marks = 0.0
    score = 0.0
    breakdown = {}

    for q in quiz.questions:
        q_id_str = str(q.id)
        chosen = submitted_answers.get(q_id_str, "").strip().upper()
        is_correct = chosen == q.correct_option.strip().upper()
        awarded = q.marks if is_correct else 0.0

        total_marks += q.marks
        score += awarded
        breakdown[q_id_str] = {
            "question_id": q.id,
            "chosen_option": chosen,
            "correct_option": q.correct_option,
            "is_correct": is_correct,
            "marks_awarded": awarded,
            "max_marks": q.marks,
        }

    return round(score, 2), round(total_marks, 2), breakdown


def get_quiz_results_breakdown(db: Session, quiz: Quiz) -> dict[str, Any]:
    """Calculates class results and per-question accuracy for teacher view."""
    attempts = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.quiz_id == quiz.id)
        .all()
    )

    enrolled_count = (
        db.query(Enrollment)
        .filter(Enrollment.class_id == quiz.class_id)
        .count()
    )

    scores = [a.score for a in attempts]
    avg_score = round(sum(scores) / len(scores), 1) if scores else None
    highest_score = max(scores) if scores else None
    lowest_score = min(scores) if scores else None

    # Per question analysis
    questions_data = []
    for q in quiz.questions:
        q_id_str = str(q.id)
        total_answered = 0
        correct_count = 0
        option_distribution = {"A": 0, "B": 0, "C": 0, "D": 0}

        for a in attempts:
            val = (a.answers or {}).get(q_id_str)
            if isinstance(val, dict):
                chosen = str(val.get("chosen_option") or "").upper()
            else:
                chosen = str(val or "").upper()

            if chosen in option_distribution:
                option_distribution[chosen] += 1
                total_answered += 1
                if chosen == q.correct_option.upper():
                    correct_count += 1

        accuracy = round((correct_count / total_answered) * 100, 1) if total_answered > 0 else 0.0

        questions_data.append({
            "id": q.id,
            "question_text": q.question_text,
            "correct_option": q.correct_option,
            "marks": q.marks,
            "total_answered": total_answered,
            "correct_count": correct_count,
            "accuracy_percentage": accuracy,
            "option_distribution": option_distribution,
        })

    return {
        "quiz_id": quiz.id,
        "title": quiz.title,
        "enrolled_count": enrolled_count,
        "attempts_count": len(attempts),
        "average_score": avg_score,
        "highest_score": highest_score,
        "lowest_score": lowest_score,
        "total_marks": sum(q.marks for q in quiz.questions),
        "questions_analysis": questions_data,
    }


def generate_draft_quiz_questions_hook(
    topic: str,
    num_questions: int = 5,
) -> list[dict[str, Any]]:
    """Clean service hook for Person C's Teacher Assistant Bot to generate/draft questions."""
    return [
        {
            "question_text": f"Sample question on {topic} #{i+1}?",
            "option_a": f"Option A for {topic}",
            "option_b": f"Option B for {topic}",
            "option_c": f"Option C for {topic}",
            "option_d": f"Option D for {topic}",
            "correct_option": "A",
            "marks": 1.0,
            "order_index": i,
        }
        for i in range(num_questions)
    ]
