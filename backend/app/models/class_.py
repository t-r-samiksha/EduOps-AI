from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SchoolClass(Base):
    """A class/section, e.g. "Grade 8 - A". Named SchoolClass since `class` is reserved."""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_teacher_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    school: Mapped["School"] = relationship(back_populates="classes")
    class_teacher: Mapped["User | None"] = relationship()
