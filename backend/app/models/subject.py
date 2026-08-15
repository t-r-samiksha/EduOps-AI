from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    periods_per_week: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    """Default weekly period count for this subject - the School Management
    page's real, persisted master-data value. POST /timetable/generate's
    per-run SubjectSelection.periods_per_week still exists and still wins for
    that one run (a one-off override, e.g. exam term), but now DEFAULTS from
    this field instead of an arbitrary hardcoded "3" every single time."""
    lab_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    """Default lab-room requirement for this subject - same relationship to
    SubjectSelection.lab_required as periods_per_week above: a real stored
    default, still overridable per generation run."""

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)

    school: Mapped["School"] = relationship(back_populates="subjects")
