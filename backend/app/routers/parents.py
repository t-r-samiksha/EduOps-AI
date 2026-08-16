"""Real Parent account creation + linking - the same onboarding-gap fix as
routers/students.py, for the parent side: no endpoint anywhere created a new
parent account or linked one to students (parent.py's GET /children only
reads an ALREADY-linked parent's own children). This is the real mechanism
for onboarding a school's existing roster of parent/guardian contacts.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.parent_student import ParentStudent
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.auth import CurrentUser, require_role
from app.services.supabase_admin import create_auth_account

router = APIRouter(prefix="/admin/parents", tags=["parents"])

_MUTATOR = require_role("admin", "principal")


class ParentCreate(BaseModel):
    school_id: int
    email: str
    password: str
    full_name: str | None = None
    phone: str | None = None
    """Real gap found live: School Management's Parents tab had no contact number
    for a guardian at all - AdmissionApplication.guardian_phone existed but
    belongs to the application, never carried into the parent's own account."""
    student_ids: list[int] = []
    """Real students (already created via POST /admin/students or otherwise)
    to link via ParentStudent - the same table/mechanism GET /parent/children
    reads from. Supports linking more than one child in the same call (a
    parent with multiple kids at this school)."""


class ParentOut(BaseModel):
    id: int
    email: str
    full_name: str | None
    phone: str | None
    school_id: int | None
    is_active: bool
    student_ids: list[int]

    model_config = ConfigDict(from_attributes=False)


class ParentUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    """Linked children are managed via the add/remove sub-resource endpoints
    below (POST/DELETE .../children/{student_id}), same idempotent pattern as
    teachers.py's subject qualifications - not a single big PUT that replaces
    the whole set, so adding one child to a parent who already has two never
    requires resending those two."""


def _get_parent_or_404(db: Session, parent_id: int) -> User:
    parent_role_id = db.query(Role.id).filter(Role.name == "parent").scalar_subquery()
    parent = db.query(User).filter(User.id == parent_id, User.role_id == parent_role_id).one_or_none()
    if parent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Parent not found")
    return parent


def _build_parent_out(db: Session, parent: User) -> ParentOut:
    student_ids = [
        row.student_id for row in db.query(ParentStudent).filter(ParentStudent.parent_id == parent.id).all()
    ]
    return ParentOut(
        id=parent.id, email=parent.email, full_name=parent.full_name, phone=parent.phone, school_id=parent.school_id,
        is_active=parent.is_active, student_ids=student_ids,
    )


@router.post("", response_model=ParentOut, status_code=status.HTTP_201_CREATED)
def create_parent(body: ParentCreate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    if db.query(School).filter(School.id == body.school_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown school_id {body.school_id}")

    student_role_id = db.query(Role.id).filter(Role.name == "student").scalar_subquery()
    found_student_ids = {
        row.id for row in db.query(User.id).filter(User.id.in_(body.student_ids), User.role_id == student_role_id).all()
    }
    missing_students = set(body.student_ids) - found_student_ids
    if missing_students:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown student_id(s): {sorted(missing_students)}")

    if db.query(User).filter(User.email == body.email).one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A user with email {body.email} already exists")

    supabase_id = create_auth_account(email=body.email, password=body.password, full_name=body.full_name, role="parent")

    parent_role = db.query(Role).filter(Role.name == "parent").one()
    parent = User(
        supabase_id=supabase_id, email=body.email, full_name=body.full_name, phone=body.phone, role_id=parent_role.id,
        school_id=body.school_id, is_active=True,
    )
    db.add(parent)
    db.flush()

    for student_id in dict.fromkeys(body.student_ids):  # de-duplicate, preserve order
        db.add(ParentStudent(parent_id=parent.id, student_id=student_id))

    db.commit()
    db.refresh(parent)

    return _build_parent_out(db, parent)


@router.get("", response_model=list[ParentOut])
def list_parents(
    school_id: int, include_inactive: bool = False, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)
):
    parent_role_id = db.query(Role.id).filter(Role.name == "parent").scalar_subquery()
    query = db.query(User).filter(User.school_id == school_id, User.role_id == parent_role_id)
    if not include_inactive:
        query = query.filter(User.is_active.is_(True))
    parents = query.order_by(User.id).all()
    return [_build_parent_out(db, p) for p in parents]


@router.get("/{parent_id}", response_model=ParentOut)
def get_parent(parent_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    parent = _get_parent_or_404(db, parent_id)
    return _build_parent_out(db, parent)


@router.put("/{parent_id}", response_model=ParentOut)
def update_parent(parent_id: int, body: ParentUpdate, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    parent = _get_parent_or_404(db, parent_id)
    if body.full_name is not None:
        parent.full_name = body.full_name
    if body.phone is not None:
        parent.phone = body.phone
    db.commit()
    db.refresh(parent)
    return _build_parent_out(db, parent)


@router.put("/{parent_id}/deactivate", response_model=ParentOut)
def deactivate_parent(parent_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    parent = _get_parent_or_404(db, parent_id)
    parent.is_active = False
    db.commit()
    db.refresh(parent)
    return _build_parent_out(db, parent)


@router.put("/{parent_id}/reactivate", response_model=ParentOut)
def reactivate_parent(parent_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    parent = _get_parent_or_404(db, parent_id)
    parent.is_active = True
    db.commit()
    db.refresh(parent)
    return _build_parent_out(db, parent)


@router.post("/{parent_id}/children", response_model=ParentOut, status_code=status.HTTP_201_CREATED)
def add_parent_child(parent_id: int, student_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    parent = _get_parent_or_404(db, parent_id)
    student_role_id = db.query(Role.id).filter(Role.name == "student").scalar_subquery()
    if db.query(User).filter(User.id == student_id, User.role_id == student_role_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown student_id {student_id}")

    existing = (
        db.query(ParentStudent)
        .filter(ParentStudent.parent_id == parent_id, ParentStudent.student_id == student_id)
        .one_or_none()
    )
    if existing is None:
        db.add(ParentStudent(parent_id=parent_id, student_id=student_id))
        db.commit()
    return _build_parent_out(db, parent)


@router.delete("/{parent_id}/children/{student_id}", response_model=ParentOut)
def remove_parent_child(parent_id: int, student_id: int, user: CurrentUser = Depends(_MUTATOR), db: Session = Depends(get_db)):
    parent = _get_parent_or_404(db, parent_id)
    db.query(ParentStudent).filter(
        ParentStudent.parent_id == parent_id, ParentStudent.student_id == student_id
    ).delete()
    db.commit()
    return _build_parent_out(db, parent)
