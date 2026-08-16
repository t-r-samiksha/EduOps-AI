from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.role import Role
from app.models.subject import Subject
from app.models.timetable import Room, TeacherProfile, TeacherSubject
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/reference", tags=["reference"])

# Not part of any Person A/B/C feature - Phase 0 built the users/school/class/subject
# schema but never exposed a way to resolve their ids to display names. Every
# Person A endpoint that returns a TimetableSlot/AttendanceMatch/etc only carries
# subject_id/teacher_id/room_id/class_id (see docs/api-contract.md), so a frontend
# has no way to show "Math" instead of "Subject #3" without this. Added here as a
# small, read-only, non-role-gated lookup - any authenticated user may read names,
# consistent with these entities carrying no sensitive data themselves.


class NamedItem(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class SubjectItem(NamedItem):
    periods_per_week: int
    lab_required: bool
    """Real, persisted master-data defaults (School Management's Subjects tab)
    - POST /timetable/generate's per-run SubjectSelection can still override
    either for that one run, but now defaults from these instead of an
    arbitrary hardcoded value."""


class TeacherItem(NamedItem):
    max_periods_per_week: int | None = None
    """From TeacherProfile - None only if a teacher somehow has no profile row
    (seed_demo_data.py gives every seeded teacher one)."""
    subject_ids: list[int] = []
    """This teacher's TeacherSubject qualifications - which subjects they're
    eligible to teach, real seed-managed data (see CLAUDE.md)."""


class RoomItem(NamedItem):
    room_type: str


class ClassItem(NamedItem):
    grade_level: int | None = None
    grade_label: str | None = None
    """Display label for grade_level (e.g. "LKG") - null for a plain numeric
    grade. See SchoolClass.grade_label's docstring - display code should show
    this when present, falling back to f"Grade {grade_level}" otherwise."""
    section: str | None = None
    class_teacher_id: int | None = None
    """So a teacher viewing this lookup can tell which class(es), if any, they
    are the class teacher of (e.g. the Fees page's teacher view) without needing
    the admin-only /admin/classes endpoint."""


class LookupResponse(BaseModel):
    subjects: list[SubjectItem]
    teachers: list[TeacherItem]
    students: list[NamedItem]
    rooms: list[RoomItem]
    classes: list[ClassItem]


def _users_by_role(db: Session, school_id: int, role_name: str) -> list[User]:
    return (
        db.query(User)
        .join(Role, User.role_id == Role.id)
        .filter(User.school_id == school_id, Role.name == role_name, User.is_active.is_(True))
        .all()
    )


@router.get("/lookup", response_model=LookupResponse)
def get_lookup(
    school_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Deactivated master-data rows are excluded everywhere below - this is what
    # makes master_data.py/teachers.py's "deactivate" endpoints actually mean
    # something end to end, rather than just flipping a column nothing reads.
    subjects = db.query(Subject).filter(Subject.school_id == school_id, Subject.is_active.is_(True)).all()
    teachers = _users_by_role(db, school_id, "teacher")
    students = _users_by_role(db, school_id, "student")
    rooms = db.query(Room).filter(Room.school_id == school_id, Room.is_active.is_(True)).all()
    classes = (
        db.query(SchoolClass).filter(SchoolClass.school_id == school_id, SchoolClass.is_active.is_(True)).all()
    )

    teacher_ids = [t.id for t in teachers]
    max_periods_by_teacher = {
        p.teacher_id: p.max_periods_per_week
        for p in db.query(TeacherProfile).filter(TeacherProfile.teacher_id.in_(teacher_ids)).all()
    }
    subject_ids_by_teacher: dict[int, list[int]] = {}
    for row in db.query(TeacherSubject).filter(TeacherSubject.teacher_id.in_(teacher_ids)).all():
        subject_ids_by_teacher.setdefault(row.teacher_id, []).append(row.subject_id)

    return LookupResponse(
        subjects=[
            SubjectItem(id=s.id, name=s.name, periods_per_week=s.periods_per_week, lab_required=s.lab_required)
            for s in subjects
        ],
        teachers=[
            TeacherItem(
                id=t.id,
                name=t.full_name or t.email,
                max_periods_per_week=max_periods_by_teacher.get(t.id),
                subject_ids=subject_ids_by_teacher.get(t.id, []),
            )
            for t in teachers
        ],
        students=[NamedItem(id=s.id, name=s.full_name or s.email) for s in students],
        rooms=[RoomItem(id=r.id, name=r.name, room_type=r.room_type) for r in rooms],
        classes=[
            ClassItem(
                id=c.id, name=c.name, grade_level=c.grade_level, grade_label=c.grade_label, section=c.section,
                class_teacher_id=c.class_teacher_id,
            )
            for c in classes
        ],
    )
