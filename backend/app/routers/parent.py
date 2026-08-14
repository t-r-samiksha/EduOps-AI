from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.user import User
from app.services.auth import CurrentUser, require_role

router = APIRouter(prefix="/parent", tags=["parent"])

# Same gap-closing pattern as reference.py's /reference/lookup: the schema has
# real multi-child support (ParentStudent, see its own docstring) but no
# endpoint ever exposed "which children am I linked to" - every parent-scoped
# endpoint built so far (Timetable, Attendance, Risk) instead makes the parent
# type in a student_id by hand. That's a real, honestly-documented gap in each
# of those api-contract.md sections, not a bug - but it blocks a real parent
# dashboard from existing at all, so it's closed here, scoped strictly to the
# calling parent's own linked children (role-gated, not a general lookup).


class LinkedChild(BaseModel):
    id: int
    name: str
    class_id: int | None
    class_name: str | None

    model_config = ConfigDict(from_attributes=True)


class ChildrenResponse(BaseModel):
    items: list[LinkedChild]


@router.get("/children", response_model=ChildrenResponse)
def get_linked_children(
    user: CurrentUser = Depends(require_role("parent")),
    db: Session = Depends(get_db),
):
    links = db.query(ParentStudent).filter(ParentStudent.parent_id == user.id).all()
    student_ids = [link.student_id for link in links]
    students = db.query(User).filter(User.id.in_(student_ids)).all() if student_ids else []
    students_by_id = {s.id: s for s in students}

    # Same primary-enrollment resolution as timetable.py's _resolve_student_class_id.
    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.student_id.in_(student_ids), Enrollment.is_primary.is_(True))
        .all()
        if student_ids
        else []
    )
    class_id_by_student = {e.student_id: e.class_id for e in enrollments}
    class_ids = list(class_id_by_student.values())
    classes_by_id = {c.id: c for c in db.query(SchoolClass).filter(SchoolClass.id.in_(class_ids)).all()} if class_ids else {}

    items = []
    for student_id in student_ids:
        student = students_by_id.get(student_id)
        if student is None:
            continue
        class_id = class_id_by_student.get(student_id)
        school_class = classes_by_id.get(class_id) if class_id else None
        items.append(
            LinkedChild(
                id=student.id,
                name=student.full_name or student.email,
                class_id=class_id,
                class_name=school_class.name if school_class else None,
            )
        )

    return ChildrenResponse(items=items)
