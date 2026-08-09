from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ParentStudent(Base):
    """Links a parent's user row to a student's user row. A parent can have
    multiple rows (multi-child support); a student can in principle have more
    than one linked parent/guardian row too."""

    __tablename__ = "parent_student"
    __table_args__ = (UniqueConstraint("parent_id", "student_id", name="uq_parent_student_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parent: Mapped["User"] = relationship(foreign_keys=[parent_id])
    student: Mapped["User"] = relationship(foreign_keys=[student_id])
