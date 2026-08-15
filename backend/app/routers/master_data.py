"""Real CRUD for the four simplest master-data entities: School, SchoolClass,
Subject, Room. Teacher is deliberately NOT here - it needs a real Supabase Auth
account provisioned alongside the local row, which is enough extra complexity
to warrant its own router (see `routers/teachers.py`).

Closes the gap the reliability audit found: every Person A feature that
references a school/class/subject/room id assumed one already existed via
`scripts/seed_demo_data.py`, with no real endpoint for an admin to create one.
`CLAUDE.md`'s prior scope note ("seed-script-managed, no CRUD API, by explicit
user decision") is superseded by this session's explicit build request - a real
school cannot onboard from zero without this.

Soft-delete only: every entity gets `is_active`, never a hard DELETE. Every
list endpoint defaults to active-only rows (`include_inactive=true` to see
everything) - this is what makes "deactivate" actually mean something end to
end, e.g. a deactivated Room stops showing up in `GET /reference/lookup` and
stops being a valid `room_id` for `POST /timetable/generate` (see the matching
`.filter(*.is_active.is_(True))` added to `reference.py` and `timetable.py` in
this same change).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room
from app.models.user import User
from app.services.auth import CurrentUser, require_role

router = APIRouter(tags=["master-data"])

_MUTATOR = require_role("admin", "principal")


# --- Schemas -----------------------------------------------------------------


class SchoolOut(BaseModel):
    id: int
    name: str
    address: str | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SchoolCreate(BaseModel):
    name: str
    address: str | None = None


class SchoolUpdate(BaseModel):
    name: str | None = None
    address: str | None = None


class SchoolClassOut(BaseModel):
    id: int
    name: str
    academic_year: str
    grade_level: int | None
    grade_label: str | None
    section: str | None
    school_id: int
    class_teacher_id: int | None
    home_room_id: int | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SchoolClassCreate(BaseModel):
    school_id: int
    name: str
    academic_year: str
    grade_level: int | None = None
    grade_label: str | None = None
    """Display label for grade_level, e.g. "LKG" for grade_level=-2 - purely
    cosmetic, see SchoolClass.grade_label's own docstring. grade_level itself
    is still what every resolution/generation endpoint keys off."""
    section: str | None = None
    class_teacher_id: int | None = None
    home_room_id: int | None = None
    """This class's designated homeroom - see SchoolClass.home_room_id's own
    docstring. Two active classes may never share the same home_room_id
    (validated below, 400 before it ever reaches the solver)."""


class SchoolClassUpdate(BaseModel):
    name: str | None = None
    academic_year: str | None = None
    grade_level: int | None = None
    grade_label: str | None = None
    section: str | None = None
    class_teacher_id: int | None = None
    home_room_id: int | None = None


class SubjectOut(BaseModel):
    id: int
    name: str
    code: str | None
    school_id: int
    is_active: bool
    periods_per_week: int
    lab_required: bool

    model_config = ConfigDict(from_attributes=True)


class SubjectCreate(BaseModel):
    school_id: int
    name: str
    code: str | None = None
    periods_per_week: int = 3
    lab_required: bool = False


class SubjectUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    periods_per_week: int | None = None
    lab_required: bool | None = None


class RoomOut(BaseModel):
    id: int
    name: str
    capacity: int
    room_type: str
    school_id: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class RoomCreate(BaseModel):
    school_id: int
    name: str
    capacity: int
    room_type: str = "classroom"


class RoomUpdate(BaseModel):
    name: str | None = None
    capacity: int | None = None
    room_type: str | None = None


# --- Helpers -------------------------------------------------------------------


def _get_school_or_400(db: Session, school_id: int) -> School:
    school = db.query(School).filter(School.id == school_id).one_or_none()
    if school is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown school_id {school_id}")
    return school


def _get_or_404(db: Session, model, entity_id: int, label: str):
    row = db.query(model).filter(model.id == entity_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found")
    return row


def _validate_home_room(db: Session, home_room_id: int, exclude_class_id: int | None) -> None:
    """Rejects an unknown room, or a room already claimed as another ACTIVE
    class's homeroom, with a clean 400 - never lets a collision reach the
    solver (POST /timetable/generate assumes home_room_id uniquely identifies
    one class's non-lab periods; two classes sharing one would silently
    double-book that room every period)."""
    if db.query(Room).filter(Room.id == home_room_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown home_room_id {home_room_id}")
    query = db.query(SchoolClass).filter(SchoolClass.home_room_id == home_room_id, SchoolClass.is_active.is_(True))
    if exclude_class_id is not None:
        query = query.filter(SchoolClass.id != exclude_class_id)
    conflict = query.first()
    if conflict is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Room {home_room_id} is already the home room of class '{conflict.name}' (id={conflict.id})",
        )


# --- School --------------------------------------------------------------------


@router.post("/admin/schools", response_model=SchoolOut, status_code=status.HTTP_201_CREATED)
def create_school(body: SchoolCreate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    school = School(name=body.name, address=body.address)
    db.add(school)
    db.commit()
    db.refresh(school)
    return school


@router.get("/admin/schools", response_model=list[SchoolOut])
def list_schools(include_inactive: bool = False, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    query = db.query(School)
    if not include_inactive:
        query = query.filter(School.is_active.is_(True))
    return query.order_by(School.id).all()


@router.get("/admin/schools/{school_id}", response_model=SchoolOut)
def get_school(school_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    return _get_or_404(db, School, school_id, "School")


@router.put("/admin/schools/{school_id}", response_model=SchoolOut)
def update_school(school_id: int, body: SchoolUpdate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    school = _get_or_404(db, School, school_id, "School")
    if body.name is not None:
        school.name = body.name
    if body.address is not None:
        school.address = body.address
    db.commit()
    db.refresh(school)
    return school


@router.put("/admin/schools/{school_id}/deactivate", response_model=SchoolOut)
def deactivate_school(school_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    school = _get_or_404(db, School, school_id, "School")
    school.is_active = False
    db.commit()
    db.refresh(school)
    return school


@router.put("/admin/schools/{school_id}/reactivate", response_model=SchoolOut)
def reactivate_school(school_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    school = _get_or_404(db, School, school_id, "School")
    school.is_active = True
    db.commit()
    db.refresh(school)
    return school


# --- SchoolClass -----------------------------------------------------------------


@router.post("/admin/classes", response_model=SchoolClassOut, status_code=status.HTTP_201_CREATED)
def create_class(body: SchoolClassCreate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    _get_school_or_400(db, body.school_id)
    if body.class_teacher_id is not None:
        teacher = db.query(User).filter(User.id == body.class_teacher_id).one_or_none()
        if teacher is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown class_teacher_id {body.class_teacher_id}")
    if body.home_room_id is not None:
        _validate_home_room(db, body.home_room_id, exclude_class_id=None)

    school_class = SchoolClass(
        school_id=body.school_id,
        name=body.name,
        academic_year=body.academic_year,
        grade_level=body.grade_level,
        grade_label=body.grade_label,
        section=body.section,
        class_teacher_id=body.class_teacher_id,
        home_room_id=body.home_room_id,
    )
    db.add(school_class)
    db.commit()
    db.refresh(school_class)
    return school_class


@router.get("/admin/classes", response_model=list[SchoolClassOut])
def list_classes(
    school_id: int,
    academic_year: str | None = None,
    include_inactive: bool = False,
    user: CurrentUser = Depends(_MUTATOR),
    db: Session = Depends(get_db),
):
    query = db.query(SchoolClass).filter(SchoolClass.school_id == school_id)
    if academic_year is not None:
        query = query.filter(SchoolClass.academic_year == academic_year)
    if not include_inactive:
        query = query.filter(SchoolClass.is_active.is_(True))
    return query.order_by(SchoolClass.grade_level, SchoolClass.section).all()


@router.get("/admin/classes/{class_id}", response_model=SchoolClassOut)
def get_class(class_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    return _get_or_404(db, SchoolClass, class_id, "Class")


@router.put("/admin/classes/{class_id}", response_model=SchoolClassOut)
def update_class(class_id: int, body: SchoolClassUpdate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    school_class = _get_or_404(db, SchoolClass, class_id, "Class")
    if body.class_teacher_id is not None:
        teacher = db.query(User).filter(User.id == body.class_teacher_id).one_or_none()
        if teacher is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown class_teacher_id {body.class_teacher_id}")
        school_class.class_teacher_id = body.class_teacher_id
    if body.home_room_id is not None:
        _validate_home_room(db, body.home_room_id, exclude_class_id=school_class.id)
        school_class.home_room_id = body.home_room_id
    if body.name is not None:
        school_class.name = body.name
    if body.academic_year is not None:
        school_class.academic_year = body.academic_year
    if body.grade_level is not None:
        school_class.grade_level = body.grade_level
    if body.grade_label is not None:
        school_class.grade_label = body.grade_label
    if body.section is not None:
        school_class.section = body.section
    db.commit()
    db.refresh(school_class)
    return school_class


@router.put("/admin/classes/{class_id}/deactivate", response_model=SchoolClassOut)
def deactivate_class(class_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    school_class = _get_or_404(db, SchoolClass, class_id, "Class")
    school_class.is_active = False
    db.commit()
    db.refresh(school_class)
    return school_class


@router.put("/admin/classes/{class_id}/reactivate", response_model=SchoolClassOut)
def reactivate_class(class_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    school_class = _get_or_404(db, SchoolClass, class_id, "Class")
    school_class.is_active = True
    db.commit()
    db.refresh(school_class)
    return school_class


# --- Subject -------------------------------------------------------------------


@router.post("/admin/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(body: SubjectCreate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    _get_school_or_400(db, body.school_id)
    subject = Subject(
        school_id=body.school_id, name=body.name, code=body.code,
        periods_per_week=body.periods_per_week, lab_required=body.lab_required,
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return subject


@router.get("/admin/subjects", response_model=list[SubjectOut])
def list_subjects(
    school_id: int, include_inactive: bool = False, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)
):
    query = db.query(Subject).filter(Subject.school_id == school_id)
    if not include_inactive:
        query = query.filter(Subject.is_active.is_(True))
    return query.order_by(Subject.name).all()


@router.get("/admin/subjects/{subject_id}", response_model=SubjectOut)
def get_subject(subject_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    return _get_or_404(db, Subject, subject_id, "Subject")


@router.put("/admin/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(subject_id: int, body: SubjectUpdate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    subject = _get_or_404(db, Subject, subject_id, "Subject")
    if body.name is not None:
        subject.name = body.name
    if body.code is not None:
        subject.code = body.code
    if body.periods_per_week is not None:
        subject.periods_per_week = body.periods_per_week
    if body.lab_required is not None:
        subject.lab_required = body.lab_required
    db.commit()
    db.refresh(subject)
    return subject


@router.put("/admin/subjects/{subject_id}/deactivate", response_model=SubjectOut)
def deactivate_subject(subject_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    subject = _get_or_404(db, Subject, subject_id, "Subject")
    subject.is_active = False
    db.commit()
    db.refresh(subject)
    return subject


@router.put("/admin/subjects/{subject_id}/reactivate", response_model=SubjectOut)
def reactivate_subject(subject_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    subject = _get_or_404(db, Subject, subject_id, "Subject")
    subject.is_active = True
    db.commit()
    db.refresh(subject)
    return subject


# --- Room ------------------------------------------------------------------------


@router.post("/admin/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
def create_room(body: RoomCreate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    _get_school_or_400(db, body.school_id)
    room = Room(school_id=body.school_id, name=body.name, capacity=body.capacity, room_type=body.room_type)
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@router.get("/admin/rooms", response_model=list[RoomOut])
def list_rooms(
    school_id: int, include_inactive: bool = False, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)
):
    query = db.query(Room).filter(Room.school_id == school_id)
    if not include_inactive:
        query = query.filter(Room.is_active.is_(True))
    return query.order_by(Room.name).all()


@router.get("/admin/rooms/{room_id}", response_model=RoomOut)
def get_room(room_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    return _get_or_404(db, Room, room_id, "Room")


@router.put("/admin/rooms/{room_id}", response_model=RoomOut)
def update_room(room_id: int, body: RoomUpdate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    room = _get_or_404(db, Room, room_id, "Room")
    if body.name is not None:
        room.name = body.name
    if body.capacity is not None:
        room.capacity = body.capacity
    if body.room_type is not None:
        room.room_type = body.room_type
    db.commit()
    db.refresh(room)
    return room


@router.put("/admin/rooms/{room_id}/deactivate", response_model=RoomOut)
def deactivate_room(room_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    room = _get_or_404(db, Room, room_id, "Room")
    room.is_active = False
    db.commit()
    db.refresh(room)
    return room


@router.put("/admin/rooms/{room_id}/reactivate", response_model=RoomOut)
def reactivate_room(room_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    room = _get_or_404(db, Room, room_id, "Room")
    room.is_active = True
    db.commit()
    db.refresh(room)
    return room
