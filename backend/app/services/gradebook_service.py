"""Gradebook and GPA Calculation Service - Person B (Classroom & Academics).

Handles configurable assessment weighting, term average calculation,
4.0 GPA scale conversion, and grade summary aggregation for Person A risk scoring
and Person C Parent Assistant Bot.
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from app.models.gradebook import GradebookEntry, GradebookWeight
from app.models.subject import Subject
from app.models.user import User


def score_to_gpa(percentage: float) -> tuple[float, str]:
    """Convert numerical percentage to 4.0 scale GPA and letter grade.
    Standard academic conversion scale:
    >= 90: 4.0 (A+)
    85-89: 3.7 (A)
    80-84: 3.3 (B+)
    75-79: 3.0 (B)
    70-74: 2.7 (B-)
    65-69: 2.3 (C+)
    60-64: 2.0 (C)
    50-59: 1.0 (D)
    < 50: 0.0 (F)
    """
    p = round(percentage, 2)
    if p >= 90.0:
        return 4.0, "A+"
    elif p >= 85.0:
        return 3.7, "A"
    elif p >= 80.0:
        return 3.3, "B+"
    elif p >= 75.0:
        return 3.0, "B"
    elif p >= 70.0:
        return 2.7, "B-"
    elif p >= 65.0:
        return 2.3, "C+"
    elif p >= 60.0:
        return 2.0, "C"
    elif p >= 50.0:
        return 1.0, "D"
    else:
        return 0.0, "F"


def get_term_weights(
    db: Session,
    school_id: int,
    term: str,
    class_id: int | None = None,
    subject_id: int | None = None,
) -> dict[str, float]:
    """Retrieve configurable assessment category weights."""
    weight_row = (
        db.query(GradebookWeight)
        .filter(
            GradebookWeight.school_id == school_id,
            GradebookWeight.term == term,
        )
        .first()
    )
    if weight_row:
        return {
            "assignment": weight_row.assignment_weight,
            "quiz": weight_row.quiz_weight,
            "midterm": weight_row.midterm_weight,
            "final": weight_row.final_weight,
            "other": weight_row.other_weight,
        }

    # Default configurable baseline: 20% Assignment, 20% Quiz, 20% Midterm, 40% Final
    return {
        "assignment": 0.20,
        "quiz": 0.20,
        "midterm": 0.20,
        "final": 0.40,
        "other": 0.0,
    }


def calculate_subject_performance(
    entries: list[GradebookEntry],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Calculates weighted subject percentage and GPA from gradebook entries."""
    if not entries:
        return {
            "percentage": None,
            "gpa": None,
            "letter_grade": None,
            "total_entries": 0,
            "entries": [],
        }

    weights = weights or {"assignment": 0.20, "quiz": 0.20, "midterm": 0.20, "final": 0.40, "other": 0.0}

    # Group scores by assessment type
    by_type: dict[str, list[float]] = {}
    for e in entries:
        pct = (e.score / e.max_score) * 100.0 if e.max_score > 0 else 0.0
        pct = max(0.0, min(100.0, pct))
        by_type.setdefault(e.assessment_type.lower(), []).append(pct)

    total_weight_applied = 0.0
    weighted_sum = 0.0

    for cat, pcts in by_type.items():
        cat_avg = sum(pcts) / len(pcts)
        w = weights.get(cat, 0.10)
        weighted_sum += cat_avg * w
        total_weight_applied += w

    if total_weight_applied > 0:
        final_percentage = round(weighted_sum / total_weight_applied, 2)
    else:
        all_pcts = [
            (e.score / e.max_score) * 100.0 for e in entries if e.max_score > 0
        ]
        final_percentage = round(sum(all_pcts) / len(all_pcts), 2) if all_pcts else 0.0

    gpa, letter = score_to_gpa(final_percentage)

    return {
        "percentage": final_percentage,
        "gpa": gpa,
        "letter_grade": letter,
        "total_entries": len(entries),
        "by_category": {cat: round(sum(p) / len(p), 1) for cat, p in by_type.items()},
    }


def get_student_gradebook_summary(
    db: Session,
    student_id: int,
    term: str = "Term 1",
) -> dict[str, Any]:
    """Aggregates all subject grades, term average, and GPA for a student."""
    entries = (
        db.query(GradebookEntry)
        .filter(
            GradebookEntry.student_id == student_id,
            GradebookEntry.term == term,
        )
        .all()
    )

    student = db.query(User).filter(User.id == student_id).one_or_none()
    weights = get_term_weights(db, student.school_id if student else 1, term)

    # Group by subject
    subjects_map: dict[int, list[GradebookEntry]] = {}
    for e in entries:
        subjects_map.setdefault(e.subject_id, []).append(e)

    subjects_summary = []
    subject_percentages = []

    for subj_id, subj_entries in subjects_map.items():
        subj = db.query(Subject).filter(Subject.id == subj_id).one_or_none()
        perf = calculate_subject_performance(subj_entries, weights)
        if perf["percentage"] is not None:
            subject_percentages.append(perf["percentage"])

        subjects_summary.append({
            "subject_id": subj_id,
            "subject_name": subj.name if subj else f"Subject #{subj_id}",
            "percentage": perf["percentage"],
            "gpa": perf["gpa"],
            "letter_grade": perf["letter_grade"],
            "entries_count": perf["total_entries"],
            "categories": perf.get("by_category", {}),
        })

    if subject_percentages:
        term_average = round(sum(subject_percentages) / len(subject_percentages), 2)
        overall_gpa, overall_letter = score_to_gpa(term_average)
    else:
        term_average = None
        overall_gpa = None
        overall_letter = None

    return {
        "student_id": student_id,
        "student_name": student.full_name if student else None,
        "term": term,
        "term_average": term_average,
        "gpa": overall_gpa,
        "letter_grade": overall_letter,
        "subjects": subjects_summary,
        "total_assessments": len(entries),
    }
