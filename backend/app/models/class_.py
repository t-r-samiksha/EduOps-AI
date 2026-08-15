from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SchoolClass(Base):
    """A class/section, e.g. "Grade 8 - A". Named SchoolClass since `class` is reserved."""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)
    grade_level: Mapped[int | None] = mapped_column(Integer)
    """e.g. 8 for "Grade 8 - A". Nullable for rows predating this field; backfilled
    for existing seeded rows via migration. Real generation runs resolve
    grade_levels[]/sections_per_grade against this, not against `name` - this
    stays the primary field ALL resolution/sorting/generation logic uses, even
    for pre-Grade-1 levels (see grade_label below).

    Numeric convention for pre-Grade-1 levels, chosen so ordering by
    `grade_level` ascending still gives the real teaching sequence
    (Nursery < LKG < UKG < Grade 1 < Grade 2 < ...), and so `grade_levels:
    list[int]` in POST /timetable/generate needs no separate code path -
    negative ints resolve/generate exactly like positive ones:
        Nursery = -3, LKG = -2, UKG = -1, Grade 1 = 1, Grade 2 = 2, ...
    (0 is deliberately unused - keeps the pre-Grade-1 block obviously
    separated from Grade 1+ at a glance, e.g. in a sorted grade_levels[] list)."""
    grade_label: Mapped[str | None] = mapped_column(String(20))
    """Free-form display label for grade_level, e.g. "LKG"/"UKG"/"Nursery" for
    non-numeric-sounding levels. Purely cosmetic - every real resolution/
    generation code path still keys off grade_level, never this. Null for a
    numeric grade with no special name (e.g. Grade 8) - display code should
    fall back to f"Grade {grade_level}" when this is null, never show it as
    "Grade -2" etc."""
    section: Mapped[str | None] = mapped_column(String(10))
    """e.g. "A" for "Grade 8 - A". See grade_level's docstring."""
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_teacher_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    home_room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"))
    """This class's designated homeroom for non-lab subjects. POST /timetable/
    generate pins every non-lab-required period to this room as a hard
    constraint (real classes don't hop between arbitrary classrooms/
    auditoriums all day for no subject-level reason) - lab-required subjects
    still freely choose among lab-type rooms, unaffected. Null means not yet
    configured; generation falls back to today's free-choice-among-all-rooms
    behavior for that class only, and the response carries an explicit
    warning so this doesn't silently degrade with no signal."""

    school: Mapped["School"] = relationship(back_populates="classes")
    class_teacher: Mapped["User | None"] = relationship()
    home_room: Mapped["Room | None"] = relationship()
