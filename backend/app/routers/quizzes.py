"""Quizzes and Online Assessment Router - Person B (Classroom & Academics).

Implements teacher quiz builder with MCQ questions, student timed attempts,
instant auto-grading, and class accuracy results breakdown.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
from app.models.subject import Subject
from app.models.timetable import TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.notify import dispatch_bulk
from app.services.quiz_service import (
    _to_utc,
    get_quiz_results_breakdown,
    grade_quiz_attempt,
)
from app.services.scoping import teacher_class_ids

router = APIRouter(tags=["quizzes"])


# --- Pydantic Schemas ---------------------------------------------------------------


class QuestionCreate(BaseModel):
    question_text: str = Field(min_length=1)
    option_a: str = Field(min_length=1)
    option_b: str = Field(min_length=1)
    option_c: str = Field(min_length=1)
    option_d: str = Field(min_length=1)
    correct_option: str = Field(pattern="^[A-Da-d]$")
    marks: float = Field(default=1.0, gt=0)
    order_index: int = 0


class QuestionOut(BaseModel):
    id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    marks: float
    order_index: int
    correct_option: str | None = None  # Hidden for student before submission

    model_config = ConfigDict(from_attributes=True)


class QuizCreateRequest(BaseModel):
    class_id: int
    subject_id: int | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    duration_minutes: int = Field(default=30, gt=0)
    available_from: datetime | None = None
    available_until: datetime | None = None
    questions: list[QuestionCreate] = Field(min_length=1)


class QuizAttemptRequest(BaseModel):
    answers: dict[str, str]  # question_id -> chosen option ('A', 'B', 'C', 'D')


class QuizAttemptOut(BaseModel):
    id: int
    quiz_id: int
    student_id: int
    score: float
    total_marks: float
    percentage: float
    status: str
    answers: dict[str, Any]
    started_at: datetime
    submitted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class QuizOut(BaseModel):
    id: int
    school_id: int
    class_id: int
    class_name: str | None = None
    subject_id: int | None = None
    subject_name: str | None = None
    teacher_id: int
    teacher_name: str | None = None
    title: str
    description: str | None = None
    duration_minutes: int
    available_from: datetime | None = None
    available_until: datetime | None = None
    total_marks: float
    questions_count: int
    questions: list[QuestionOut] | None = None
    my_attempt: QuizAttemptOut | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Helper -------------------------------------------------------------------------


def _classes_taught_by(db: Session, teacher_id: int) -> set[int]:
    owned = set(teacher_class_ids(db, teacher_id))
    taught = {
        row.class_id
        for row in db.query(TimetableSlot.class_id).filter(TimetableSlot.teacher_id == teacher_id).distinct()
    }
    return owned | taught


def _format_quiz(quiz: Quiz, user: CurrentUser, db: Session, include_questions: bool = True) -> QuizOut:
    cls = db.query(SchoolClass).filter(SchoolClass.id == quiz.class_id).one_or_none()
    subj = db.query(Subject).filter(Subject.id == quiz.subject_id).one_or_none() if quiz.subject_id else None
    teacher = db.query(User).filter(User.id == quiz.teacher_id).one_or_none()

    total_marks = sum(q.marks for q in quiz.questions)
    questions_out = None
    my_attempt_out = None

    attempt = None
    if user.role == "student":
        attempt = (
            db.query(QuizAttempt)
            .filter(QuizAttempt.quiz_id == quiz.id, QuizAttempt.student_id == user.id)
            .first()
        )
        if attempt:
            pct = round((attempt.score / attempt.total_marks) * 100.0, 1) if attempt.total_marks > 0 else 0.0
            my_attempt_out = QuizAttemptOut(
                id=attempt.id,
                quiz_id=attempt.quiz_id,
                student_id=attempt.student_id,
                score=attempt.score,
                total_marks=attempt.total_marks,
                percentage=pct,
                status=attempt.status,
                answers=attempt.answers,
                started_at=attempt.started_at,
                submitted_at=attempt.submitted_at,
            )

    if include_questions:
        is_teacher = user.role in ("teacher", "admin", "principal")
        has_completed = attempt is not None and attempt.status == "completed"

        questions_out = []
        for q in quiz.questions:
            show_correct = is_teacher or has_completed
            questions_out.append(
                QuestionOut(
                    id=q.id,
                    question_text=q.question_text,
                    option_a=q.option_a,
                    option_b=q.option_b,
                    option_c=q.option_c,
                    option_d=q.option_d,
                    marks=q.marks,
                    order_index=q.order_index,
                    correct_option=q.correct_option if show_correct else None,
                )
            )

    return QuizOut(
        id=quiz.id,
        school_id=quiz.school_id,
        class_id=quiz.class_id,
        class_name=cls.name if cls else None,
        subject_id=quiz.subject_id,
        subject_name=subj.name if subj else None,
        teacher_id=quiz.teacher_id,
        teacher_name=teacher.full_name if teacher else None,
        title=quiz.title,
        description=quiz.description,
        duration_minutes=quiz.duration_minutes,
        available_from=quiz.available_from,
        available_until=quiz.available_until,
        total_marks=total_marks,
        questions_count=len(quiz.questions),
        questions=questions_out,
        my_attempt=my_attempt_out,
        created_at=quiz.created_at,
    )


# --- Endpoints ----------------------------------------------------------------------


@router.post("/quizzes", response_model=QuizOut, status_code=status.HTTP_201_CREATED)
def create_quiz(
    body: QuizCreateRequest,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Teacher creates an online MCQ quiz for a class section."""
    if user.school_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User account not linked to school")

    if user.role == "teacher":
        allowed = _classes_taught_by(db, user.id)
        if body.class_id not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to create quiz for this class")

    quiz = Quiz(
        school_id=user.school_id,
        class_id=body.class_id,
        subject_id=body.subject_id,
        teacher_id=user.id,
        title=body.title.strip(),
        description=body.description.strip() if body.description else None,
        duration_minutes=body.duration_minutes,
        available_from=body.available_from,
        available_until=body.available_until,
    )
    db.add(quiz)
    db.flush()

    for idx, q_data in enumerate(body.questions):
        question = QuizQuestion(
            quiz_id=quiz.id,
            question_text=q_data.question_text.strip(),
            option_a=q_data.option_a.strip(),
            option_b=q_data.option_b.strip(),
            option_c=q_data.option_c.strip(),
            option_d=q_data.option_d.strip(),
            correct_option=q_data.correct_option.strip().upper(),
            marks=q_data.marks,
            order_index=idx,
        )
        db.add(question)

    db.flush()

    # Notify enrolled students
    enrolled_ids = [
        row.student_id
        for row in db.query(Enrollment.student_id).filter(Enrollment.class_id == body.class_id).all()
    ]
    if enrolled_ids:
        dispatch_bulk(
            db,
            user_ids=enrolled_ids,
            source_type="quiz_published",
            title=f"New Quiz Available: {body.title}",
            body=f"Duration: {body.duration_minutes} mins · {len(body.questions)} questions.",
            priority="important",
            source_id=quiz.id,
        )

    db.commit()
    db.refresh(quiz)
    return _format_quiz(quiz, user, db)


@router.get("/quizzes", response_model=list[QuizOut])
def list_quizzes(
    class_id: int | None = None,
    subject_id: int | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return accessible quizzes for current user."""
    query = db.query(Quiz).filter(Quiz.school_id == user.school_id)

    if class_id is not None:
        query = query.filter(Quiz.class_id == class_id)
    elif user.role == "student":
        student_class_ids = [
            row.class_id
            for row in db.query(Enrollment.class_id).filter(Enrollment.student_id == user.id).all()
        ]
        if not student_class_ids:
            return []
        query = query.filter(Quiz.class_id.in_(student_class_ids))

    if subject_id is not None:
        query = query.filter(Quiz.subject_id == subject_id)

    quizzes = query.order_by(Quiz.created_at.desc()).all()
    return [_format_quiz(q, user, db, include_questions=False) for q in quizzes]


@router.get("/quizzes/detail/{quiz_id}", response_model=QuizOut)
def get_quiz_detail(
    quiz_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get full quiz details with questions."""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).one_or_none()
    if not quiz:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")

    if user.role == "student":
        is_enrolled = (
            db.query(Enrollment)
            .filter(Enrollment.student_id == user.id, Enrollment.class_id == quiz.class_id)
            .first()
        )
        if not is_enrolled:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not enrolled in this class")

    return _format_quiz(quiz, user, db, include_questions=True)


@router.post("/quizzes/{quiz_id}/attempt", response_model=QuizAttemptOut)
def submit_quiz_attempt(
    quiz_id: int,
    body: QuizAttemptRequest,
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    """Student submits quiz answers and gets auto-graded immediately."""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).one_or_none()
    if not quiz:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")

    is_enrolled = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == user.id, Enrollment.class_id == quiz.class_id)
        .first()
    )
    if not is_enrolled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not enrolled in this quiz's class section")

    existing_attempt = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.quiz_id == quiz_id, QuizAttempt.student_id == user.id)
        .first()
    )
    if existing_attempt:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "You have already attempted this quiz. Multiple attempts are not permitted.",
        )

    # Auto-grade immediately
    score, total_marks, breakdown = grade_quiz_attempt(quiz, body.answers)

    now = datetime.now(timezone.utc)
    attempt = QuizAttempt(
        quiz_id=quiz_id,
        student_id=user.id,
        answers=breakdown,
        score=score,
        total_marks=total_marks,
        started_at=now - timedelta(minutes=quiz.duration_minutes),
        submitted_at=now,
        status="completed",
    )
    db.add(attempt)

    # Auto-record into GradebookEntry for seamless integration!
    from app.models.gradebook import GradebookEntry
    gb_entry = (
        db.query(GradebookEntry)
        .filter(
            GradebookEntry.student_id == user.id,
            GradebookEntry.assessment_type == "quiz",
            GradebookEntry.assessment_id == quiz_id,
        )
        .first()
    )
    if gb_entry:
        gb_entry.score = score
        gb_entry.max_score = total_marks
    else:
        db.add(
            GradebookEntry(
                school_id=quiz.school_id,
                student_id=user.id,
                subject_id=quiz.subject_id or 1,
                class_id=quiz.class_id,
                term="Term 1",
                assessment_type="quiz",
                assessment_id=quiz_id,
                score=score,
                max_score=total_marks,
                weight=0.20,
            )
        )

    db.commit()
    db.refresh(attempt)

    pct = round((score / total_marks) * 100.0, 1) if total_marks > 0 else 0.0
    return QuizAttemptOut(
        id=attempt.id,
        quiz_id=attempt.quiz_id,
        student_id=attempt.student_id,
        score=attempt.score,
        total_marks=attempt.total_marks,
        percentage=pct,
        status=attempt.status,
        answers=attempt.answers,
        started_at=attempt.started_at,
        submitted_at=attempt.submitted_at,
    )


@router.get("/quizzes/{quiz_id}/results")
def get_quiz_results(
    quiz_id: int,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """Teacher views class results and per-question accuracy breakdown."""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).one_or_none()
    if not quiz:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")

    if user.role == "teacher":
        allowed = _classes_taught_by(db, user.id)
        if quiz.class_id not in allowed and quiz.teacher_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view results for this quiz")

    return get_quiz_results_breakdown(db, quiz)
