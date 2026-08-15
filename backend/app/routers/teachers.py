"""Real CRUD for Teacher accounts - the most complex master-data entity, since
"creating a teacher" spans a real Supabase Auth account (so they can actually
log in), the local `users` row, their `TeacherProfile` (scheduling load cap),
`TeacherSubject` qualifications, and `TeacherUnavailability` exceptions.

Closes the gap the reliability audit found in Staffing's substitute solver and
Timetable's generation input: `TeacherSubject`/`TeacherUnavailability`/
`TeacherProfile` had zero creation endpoint anywhere, only
`scripts/seed_demo_data.py` (whose users are NOT real, login-capable accounts -
see that script's own docstring) ever populated them.

Sub-resource endpoints (`/subjects`, `/unavailability`) are deliberately
idempotent add/remove operations, not a single big PUT that replaces the whole
set - so an admin adding one qualification to a teacher who already has three
never needs to resend the other three. This is what makes "add to an existing
school, not just cold-start from zero" actually work.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import TeacherProfile, TeacherSubject, TeacherUnavailability
from app.models.user import User
from app.services.auth import CurrentUser, require_role
from app.services.supabase_admin import create_teacher_auth_account

router = APIRouter(prefix="/admin/teachers", tags=["teachers"])

_MUTATOR = require_role("admin", "principal")

_DEFAULT_MAX_PERIODS_PER_WEEK = 30


# --- Schemas -----------------------------------------------------------------


class UnavailabilityIn(BaseModel):
    day_of_week: int
    period_number: int
    academic_year: str


class UnavailabilityOut(BaseModel):
    id: int
    day_of_week: int
    period_number: int
    academic_year: str

    model_config = ConfigDict(from_attributes=True)


class TeacherOut(BaseModel):
    id: int
    email: str
    full_name: str | None
    school_id: int | None
    is_active: bool
    max_periods_per_week: int
    subject_ids: list[int]
    unavailability: list[UnavailabilityOut]


class TeacherCreate(BaseModel):
    school_id: int
    email: str
    password: str
    full_name: str | None = None
    max_periods_per_week: int | None = None
    subject_ids: list[int] = []
    """Real TeacherSubject qualifications to create alongside the account. Can
    also be added later one at a time via POST /admin/teachers/{id}/subjects -
    this list is a convenience for cold-start, not the only way to set them."""
    unavailability: list[UnavailabilityIn] = []


class TeacherUpdate(BaseModel):
    full_name: str | None = None
    max_periods_per_week: int | None = None


# --- Helpers -------------------------------------------------------------------


def _teacher_role(db: Session) -> Role:
    role = db.query(Role).filter(Role.name == "teacher").one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Fixed 'teacher' role row is missing")
    return role


def _get_teacher_or_404(db: Session, teacher_id: int) -> User:
    teacher = (
        db.query(User).join(Role, User.role_id == Role.id).filter(User.id == teacher_id, Role.name == "teacher").one_or_none()
    )
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")
    return teacher


def _build_teacher_out(db: Session, teacher: User) -> TeacherOut:
    profile = db.query(TeacherProfile).filter(TeacherProfile.teacher_id == teacher.id).one_or_none()
    subject_ids = [
        row.subject_id for row in db.query(TeacherSubject).filter(TeacherSubject.teacher_id == teacher.id).all()
    ]
    unavailability = db.query(TeacherUnavailability).filter(TeacherUnavailability.teacher_id == teacher.id).all()
    return TeacherOut(
        id=teacher.id,
        email=teacher.email,
        full_name=teacher.full_name,
        school_id=teacher.school_id,
        is_active=teacher.is_active,
        max_periods_per_week=profile.max_periods_per_week if profile else _DEFAULT_MAX_PERIODS_PER_WEEK,
        subject_ids=subject_ids,
        unavailability=[UnavailabilityOut.model_validate(u) for u in unavailability],
    )


def _validate_subject_ids(db: Session, school_id: int, subject_ids: list[int]) -> None:
    if not subject_ids:
        return
    found = {
        row.id for row in db.query(Subject.id).filter(Subject.id.in_(subject_ids), Subject.school_id == school_id).all()
    }
    missing = set(subject_ids) - found
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown subject_id(s) for this school: {sorted(missing)}")


# --- Endpoints -----------------------------------------------------------------


@router.post("", response_model=TeacherOut, status_code=status.HTTP_201_CREATED)
def create_teacher(body: TeacherCreate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    if db.query(School).filter(School.id == body.school_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown school_id {body.school_id}")
    _validate_subject_ids(db, body.school_id, body.subject_ids)

    if db.query(User).filter(User.email == body.email).one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A user with email {body.email} already exists")

    # Real Supabase Auth account first - if this fails (e.g. already registered
    # in Supabase Auth even though no local row exists yet), nothing local is
    # written. If it succeeds but a later local step fails, the real auth
    # account is left orphaned with no local row - a known, accepted edge case
    # of not having a distributed transaction across Supabase Auth + Postgres.
    supabase_id = create_teacher_auth_account(email=body.email, password=body.password, full_name=body.full_name)

    role = _teacher_role(db)
    teacher = User(
        supabase_id=supabase_id,
        email=body.email,
        full_name=body.full_name,
        role_id=role.id,
        school_id=body.school_id,
        is_active=True,
    )
    db.add(teacher)
    db.flush()

    profile = TeacherProfile(
        teacher_id=teacher.id, max_periods_per_week=body.max_periods_per_week or _DEFAULT_MAX_PERIODS_PER_WEEK
    )
    db.add(profile)

    for subject_id in dict.fromkeys(body.subject_ids):  # de-duplicate, preserve order
        db.add(TeacherSubject(teacher_id=teacher.id, subject_id=subject_id))

    seen_slots = set()
    for slot in body.unavailability:
        key = (slot.day_of_week, slot.period_number, slot.academic_year)
        if key in seen_slots:
            continue
        seen_slots.add(key)
        db.add(
            TeacherUnavailability(
                teacher_id=teacher.id,
                day_of_week=slot.day_of_week,
                period_number=slot.period_number,
                academic_year=slot.academic_year,
            )
        )

    db.commit()
    db.refresh(teacher)
    return _build_teacher_out(db, teacher)


@router.get("", response_model=list[TeacherOut])
def list_teachers(
    school_id: int, include_inactive: bool = False, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)
):
    query = (
        db.query(User)
        .join(Role, User.role_id == Role.id)
        .filter(User.school_id == school_id, Role.name == "teacher")
    )
    if not include_inactive:
        query = query.filter(User.is_active.is_(True))
    teachers = query.order_by(User.id).all()
    return [_build_teacher_out(db, t) for t in teachers]


@router.get("/{teacher_id}", response_model=TeacherOut)
def get_teacher(teacher_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    teacher = _get_teacher_or_404(db, teacher_id)
    return _build_teacher_out(db, teacher)


@router.put("/{teacher_id}", response_model=TeacherOut)
def update_teacher(teacher_id: int, body: TeacherUpdate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    teacher = _get_teacher_or_404(db, teacher_id)
    if body.full_name is not None:
        teacher.full_name = body.full_name

    if body.max_periods_per_week is not None:
        profile = db.query(TeacherProfile).filter(TeacherProfile.teacher_id == teacher.id).one_or_none()
        if profile is None:
            profile = TeacherProfile(teacher_id=teacher.id, max_periods_per_week=body.max_periods_per_week)
            db.add(profile)
        else:
            profile.max_periods_per_week = body.max_periods_per_week

    db.commit()
    db.refresh(teacher)
    return _build_teacher_out(db, teacher)


@router.put("/{teacher_id}/deactivate", response_model=TeacherOut)
def deactivate_teacher(teacher_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    teacher = _get_teacher_or_404(db, teacher_id)
    teacher.is_active = False
    db.commit()
    db.refresh(teacher)
    return _build_teacher_out(db, teacher)


@router.put("/{teacher_id}/reactivate", response_model=TeacherOut)
def reactivate_teacher(teacher_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    teacher = _get_teacher_or_404(db, teacher_id)
    teacher.is_active = True
    db.commit()
    db.refresh(teacher)
    return _build_teacher_out(db, teacher)


@router.post("/{teacher_id}/subjects", response_model=TeacherOut, status_code=status.HTTP_201_CREATED)
def add_teacher_subject(teacher_id: int, subject_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    teacher = _get_teacher_or_404(db, teacher_id)
    subject = db.query(Subject).filter(Subject.id == subject_id).one_or_none()
    if subject is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown subject_id {subject_id}")

    existing = (
        db.query(TeacherSubject)
        .filter(TeacherSubject.teacher_id == teacher_id, TeacherSubject.subject_id == subject_id)
        .one_or_none()
    )
    if existing is None:
        db.add(TeacherSubject(teacher_id=teacher_id, subject_id=subject_id))
        db.commit()
    return _build_teacher_out(db, teacher)


@router.delete("/{teacher_id}/subjects/{subject_id}", response_model=TeacherOut)
def remove_teacher_subject(teacher_id: int, subject_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    teacher = _get_teacher_or_404(db, teacher_id)
    db.query(TeacherSubject).filter(
        TeacherSubject.teacher_id == teacher_id, TeacherSubject.subject_id == subject_id
    ).delete()
    db.commit()
    return _build_teacher_out(db, teacher)


@router.post("/{teacher_id}/unavailability", response_model=TeacherOut, status_code=status.HTTP_201_CREATED)
def add_teacher_unavailability(
    teacher_id: int, body: UnavailabilityIn, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)
):
    teacher = _get_teacher_or_404(db, teacher_id)
    existing = (
        db.query(TeacherUnavailability)
        .filter(
            TeacherUnavailability.teacher_id == teacher_id,
            TeacherUnavailability.day_of_week == body.day_of_week,
            TeacherUnavailability.period_number == body.period_number,
            TeacherUnavailability.academic_year == body.academic_year,
        )
        .one_or_none()
    )
    if existing is None:
        db.add(
            TeacherUnavailability(
                teacher_id=teacher_id,
                day_of_week=body.day_of_week,
                period_number=body.period_number,
                academic_year=body.academic_year,
            )
        )
        db.commit()
    return _build_teacher_out(db, teacher)


@router.delete("/{teacher_id}/unavailability/{unavailability_id}", response_model=TeacherOut)
def remove_teacher_unavailability(
    teacher_id: int, unavailability_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)
):
    teacher = _get_teacher_or_404(db, teacher_id)
    db.query(TeacherUnavailability).filter(
        TeacherUnavailability.id == unavailability_id, TeacherUnavailability.teacher_id == teacher_id
    ).delete()
    db.commit()
    return _build_teacher_out(db, teacher)
