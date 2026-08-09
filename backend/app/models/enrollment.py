from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Enrollment(Base):
    """Links a student (users.id) to a class. subject_id is null for a student's
    primary/homeroom enrollment in the class, and set for subject-specific/elective
    enrollment, so a student can have multiple rows for the same class_id."""

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "class_id", "subject_id", name="uq_enrollment_student_class_subject"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    school_class: Mapped["SchoolClass"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
