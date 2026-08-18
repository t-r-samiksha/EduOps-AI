from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base


class Quiz(Base):
    """An online MCQ quiz created by a teacher for a class section."""

    __tablename__ = "quizzes"
    __table_args__ = (
        Index("ix_quizzes_school_class", "school_id", "class_id"),
        Index("ix_quizzes_teacher_id", "teacher_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship()
    school_class: Mapped["SchoolClass"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])
    questions: Mapped[list["QuizQuestion"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", order_by="QuizQuestion.order_index.asc()"
    )
    attempts: Mapped[list["QuizAttempt"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", order_by="QuizAttempt.created_at.desc()"
    )


class QuizQuestion(Base):
    """A multiple-choice question in a quiz."""

    __tablename__ = "quiz_questions"
    __table_args__ = (
        Index("ix_quiz_questions_quiz_id", "quiz_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    option_a: Mapped[str] = mapped_column(String(500), nullable=False)
    option_b: Mapped[str] = mapped_column(String(500), nullable=False)
    option_c: Mapped[str] = mapped_column(String(500), nullable=False)
    option_d: Mapped[str] = mapped_column(String(500), nullable=False)
    correct_option: Mapped[str] = mapped_column(String(1), nullable=False)  # 'A', 'B', 'C', 'D'
    marks: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    quiz: Mapped["Quiz"] = relationship(back_populates="questions")


class QuizAttempt(Base):
    """A student's attempt and auto-graded score for a quiz."""

    __tablename__ = "quiz_attempts"
    __table_args__ = (
        UniqueConstraint("quiz_id", "student_id", name="uq_quiz_student_attempt"),
        Index("ix_quiz_attempts_student", "student_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Dict of question_id (str/int) -> chosen option ('A', 'B', 'C', 'D')
    answers: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_marks: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="completed", nullable=False)  # in_progress, completed, time_expired

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    quiz: Mapped["Quiz"] = relationship(back_populates="attempts")
    student: Mapped["User"] = relationship(foreign_keys=[student_id])
