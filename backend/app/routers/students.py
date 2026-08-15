"""Real Student account creation - closes a gap found while building the
onboarding wizard: `routers/admissions.py`'s accept flow only ENROLLS an
already-existing user, it was never able to create a brand-new student
account (see that router's own docstring). This is the real mechanism for
onboarding a school's EXISTING roster directly (a founding admin adding the 30
students already at their school) - see docs/api-contract.md's "Two ways a
student gets an Enrollment" note for how this is intentionally distinct from,
not a duplicate of, the admissions pipeline (which is for NEW applicants
going forward).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.routers.admissions import enroll_student_primary
from app.services.auth import CurrentUser, require_role
from app.services.supabase_admin import create_auth_account

router = APIRouter(prefix="/admin/students", tags=["students"])

_MUTATOR = require_role("admin", "principal")


class StudentCreate(BaseModel):
    school_id: int
    email: str
    password: str
    full_name: str | None = None
    class_id: int | None = None
    """If given, the student is immediately primary-enrolled into this class -
    the exact same real Enrollment mechanism admissions.py's accept flow uses
    (enroll_student_primary), reused here rather than duplicated."""


class StudentOut(BaseModel):
    id: int
    email: str
    full_name: str | None
    school_id: int | None
    is_active: bool
    class_id: int | None
    """The student's current primary-enrollment class, or null - a computed
    projection of Enrollment(is_primary=True), not a persisted User column."""


class StudentUpdate(BaseModel):
    full_name: str | None = None
    class_id: int | None = None
    """If given, REPLACES the student's current primary enrollment with this
    class - a genuine class change, not the additive-only semantics of
    enroll_student_primary() (which only ever adds, used by admissions.py's
    accept flow and this router's own create_student - neither of those
    callers needs to move a student OUT of an existing class, only into one,
    so that function is intentionally left alone). Omit to leave enrollment
    untouched, same partial-update convention as every other *Update schema
    in this codebase (master_data.py, teachers.py)."""


def _primary_class_id(db: Session, student_id: int) -> int | None:
    enrollment = (
        db.query(Enrollment).filter(Enrollment.student_id == student_id, Enrollment.is_primary.is_(True)).one_or_none()
    )
    return enrollment.class_id if enrollment else None


def _get_student_or_404(db: Session, student_id: int) -> User:
    student_role_id = db.query(Role.id).filter(Role.name == "student").scalar_subquery()
    student = db.query(User).filter(User.id == student_id, User.role_id == student_role_id).one_or_none()
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    return student


def _build_student_out(db: Session, student: User) -> StudentOut:
    return StudentOut(
        id=student.id, email=student.email, full_name=student.full_name, school_id=student.school_id,
        is_active=student.is_active, class_id=_primary_class_id(db, student.id),
    )


def _set_primary_class(db: Session, student_id: int, new_class_id: int) -> None:
    """Swaps a student's primary enrollment to `new_class_id` - removes any
    existing primary enrollment row(s) first, then idempotently creates the
    new one via the same real enroll_student_primary() the admissions accept
    flow uses (not duplicated), so a student is never left primary-enrolled
    in two classes at once (which `_resolve_student_class_id` elsewhere
    assumes can't happen via `.one_or_none()`)."""
    db.query(Enrollment).filter(
        Enrollment.student_id == student_id, Enrollment.is_primary.is_(True), Enrollment.subject_id.is_(None)
    ).delete()
    db.flush()
    enroll_student_primary(db, student_id, new_class_id)


@router.post("", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def create_student(body: StudentCreate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    if db.query(School).filter(School.id == body.school_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown school_id {body.school_id}")
    if body.class_id is not None and db.query(SchoolClass).filter(SchoolClass.id == body.class_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown class_id {body.class_id}")
    if db.query(User).filter(User.email == body.email).one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A user with email {body.email} already exists")

    # Real Supabase Auth account first - same ordering/rationale as
    # teachers.py::create_teacher and auth.py::signup (validate everything
    # local first so a bad request never creates an orphaned real account).
    supabase_id = create_auth_account(email=body.email, password=body.password, full_name=body.full_name, role="student")

    student_role = db.query(Role).filter(Role.name == "student").one()
    student = User(
        supabase_id=supabase_id, email=body.email, full_name=body.full_name, role_id=student_role.id,
        school_id=body.school_id, is_active=True,
    )
    db.add(student)
    db.flush()

    if body.class_id is not None:
        enroll_student_primary(db, student.id, body.class_id)

    db.commit()
    db.refresh(student)

    return _build_student_out(db, student)


@router.get("", response_model=list[StudentOut])
def list_students(
    school_id: int, include_inactive: bool = False, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)
):
    student_role_id = db.query(Role.id).filter(Role.name == "student").scalar_subquery()
    query = db.query(User).filter(User.school_id == school_id, User.role_id == student_role_id)
    if not include_inactive:
        query = query.filter(User.is_active.is_(True))
    students = query.order_by(User.id).all()
    return [_build_student_out(db, s) for s in students]


@router.get("/{student_id}", response_model=StudentOut)
def get_student(student_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    student = _get_student_or_404(db, student_id)
    return _build_student_out(db, student)


@router.put("/{student_id}", response_model=StudentOut)
def update_student(student_id: int, body: StudentUpdate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    student = _get_student_or_404(db, student_id)
    if body.full_name is not None:
        student.full_name = body.full_name
    if body.class_id is not None:
        if db.query(SchoolClass).filter(SchoolClass.id == body.class_id).one_or_none() is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown class_id {body.class_id}")
        _set_primary_class(db, student.id, body.class_id)
    db.commit()
    db.refresh(student)
    return _build_student_out(db, student)


@router.put("/{student_id}/deactivate", response_model=StudentOut)
def deactivate_student(student_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    student = _get_student_or_404(db, student_id)
    student.is_active = False
    db.commit()
    db.refresh(student)
    return _build_student_out(db, student)


@router.put("/{student_id}/reactivate", response_model=StudentOut)
def reactivate_student(student_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    student = _get_student_or_404(db, student_id)
    student.is_active = True
    db.commit()
    db.refresh(student)
    return _build_student_out(db, student)
