from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.role import Role
from app.models.subject import Subject
from app.models.timetable import Room
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


class LookupResponse(BaseModel):
    subjects: list[NamedItem]
    teachers: list[NamedItem]
    students: list[NamedItem]
    rooms: list[NamedItem]
    classes: list[NamedItem]


def _users_by_role(db: Session, school_id: int, role_name: str) -> list[User]:
    return (
        db.query(User)
        .join(Role, User.role_id == Role.id)
        .filter(User.school_id == school_id, Role.name == role_name)
        .all()
    )


@router.get("/lookup", response_model=LookupResponse)
def get_lookup(
    school_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subjects = db.query(Subject).filter(Subject.school_id == school_id).all()
    teachers = _users_by_role(db, school_id, "teacher")
    students = _users_by_role(db, school_id, "student")
    rooms = db.query(Room).filter(Room.school_id == school_id).all()
    classes = db.query(SchoolClass).filter(SchoolClass.school_id == school_id).all()

    return LookupResponse(
        subjects=[NamedItem(id=s.id, name=s.name) for s in subjects],
        teachers=[NamedItem(id=t.id, name=t.full_name or t.email) for t in teachers],
        students=[NamedItem(id=s.id, name=s.full_name or s.email) for s in students],
        rooms=[NamedItem(id=r.id, name=r.name) for r in rooms],
        classes=[NamedItem(id=c.id, name=c.name) for c in classes],
    )
