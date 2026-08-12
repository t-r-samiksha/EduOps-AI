from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.risk import Intervention, RiskFlag
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user, require_role

router = APIRouter(tags=["early-warning"])

VALID_RISK_LEVELS = ("low", "medium", "high")
RISK_LEVEL_DEFAULT_SCORE = {"low": 0.2, "medium": 0.5, "high": 0.8}
"""Nominal score for a manually-created flag when the caller doesn't supply one -
matches the low/medium/high midpoints implied by risk_scorer.py's own thresholds."""


def _teacher_class_ids(db: Session, teacher_id: int) -> list[int]:
    return [c.id for c in db.query(SchoolClass).filter(SchoolClass.class_teacher_id == teacher_id).all()]


def _students_in_classes(db: Session, class_ids: list[int]) -> set[int]:
    if not class_ids:
        return set()
    return {
        row.student_id
        for row in db.query(Enrollment.student_id).filter(
            Enrollment.class_id.in_(class_ids), Enrollment.is_primary.is_(True)
        )
    }


class FlagOut(BaseModel):
    id: int
    student_id: int
    risk_level: str
    score: float
    reasons: list[str]
    flagged_at: datetime
    status: str
    resolved_by: int | None
    resolved_at: datetime | None
    # Alert-ready enrichment, not persisted on the row - see module-level note below
    # and the summary's "integration point" callout (same pattern as Staffing's
    # confirm endpoint). Populated fresh on every response, not just on creation.
    class_id: int | None
    class_name: str | None
    homeroom_teacher_id: int | None
    parent_ids: list[int]
    student_name: str | None


def _enrich_flag_out(db: Session, flag: RiskFlag) -> FlagOut:
    """Builds the alert-ready payload: student_id (on the row already), class_id (via
    the student's primary Enrollment), homeroom_teacher_id (via that class's
    class_teacher_id), parent_ids (via ParentStudent, plural for multi-parent
    support) - everything a future notifier needs to reach teacher+parent+counselor
    without a re-query."""
    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == flag.student_id, Enrollment.is_primary.is_(True))
        .one_or_none()
    )
    school_class = (
        db.query(SchoolClass).filter(SchoolClass.id == enrollment.class_id).one_or_none()
        if enrollment is not None
        else None
    )
    parent_ids = [
        row.parent_id for row in db.query(ParentStudent.parent_id).filter(ParentStudent.student_id == flag.student_id)
    ]
    student = db.query(User).filter(User.id == flag.student_id).one_or_none()

    return FlagOut(
        id=flag.id,
        student_id=flag.student_id,
        risk_level=flag.risk_level,
        score=flag.score,
        reasons=flag.reasons,
        flagged_at=flag.flagged_at,
        status=flag.status,
        resolved_by=flag.resolved_by,
        resolved_at=flag.resolved_at,
        class_id=school_class.id if school_class else None,
        class_name=school_class.name if school_class else None,
        homeroom_teacher_id=school_class.class_teacher_id if school_class else None,
        parent_ids=parent_ids,
        student_name=student.full_name if student else None,
    )


# --- POST /risk/flag -------------------------------------------------------------


class FlagCreateRequest(BaseModel):
    student_id: int
    risk_level: str
    reasons: list[str]
    score: float | None = None
    """Omit to use a nominal score for the given risk_level (this is a manual, human
    judgment call, not the output of risk_scorer.py)."""


@router.post("/risk/flag", response_model=FlagOut)
def create_flag(
    body: FlagCreateRequest,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    if body.risk_level not in VALID_RISK_LEVELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"risk_level must be one of {VALID_RISK_LEVELS}")
    if not body.reasons:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reasons must not be empty")

    student = db.query(User).filter(User.id == body.student_id).one_or_none()
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    score = body.score if body.score is not None else RISK_LEVEL_DEFAULT_SCORE[body.risk_level]
    flag = RiskFlag(student_id=body.student_id, risk_level=body.risk_level, score=score, reasons=body.reasons, status="open")
    db.add(flag)
    db.commit()
    db.refresh(flag)
    return _enrich_flag_out(db, flag)


# --- GET /risk/flagged -------------------------------------------------------------


@router.get("/risk/flagged", response_model=list[FlagOut])
def list_flagged(
    risk_level: str | None = None,
    class_id: int | None = None,
    student_id: int | None = None,
    status_filter: str | None = Query(None, alias="status"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(RiskFlag)

    if user.role in ("admin", "principal"):
        if class_id is not None:
            query = query.filter(RiskFlag.student_id.in_(_students_in_classes(db, [class_id]) or [-1]))
        if student_id is not None:
            query = query.filter(RiskFlag.student_id == student_id)
    elif user.role == "teacher":
        owned_class_ids = _teacher_class_ids(db, user.id)
        if class_id is not None:
            if class_id not in owned_class_ids:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your class")
            owned_class_ids = [class_id]
        query = query.filter(RiskFlag.student_id.in_(_students_in_classes(db, owned_class_ids) or [-1]))
    elif user.role == "parent":
        if student_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "student_id is required for parent role")
        link = (
            db.query(ParentStudent)
            .filter(ParentStudent.parent_id == user.id, ParentStudent.student_id == student_id)
            .one_or_none()
        )
        if link is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not linked to this student")
        query = query.filter(RiskFlag.student_id == student_id)
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view risk flags")

    if risk_level is not None:
        query = query.filter(RiskFlag.risk_level == risk_level)
    if status_filter is not None:
        query = query.filter(RiskFlag.status == status_filter)
    else:
        query = query.filter(RiskFlag.status != "resolved")  # "flagged" = currently active concern

    return [_enrich_flag_out(db, f) for f in query.order_by(RiskFlag.flagged_at.desc()).all()]


# --- PUT /risk/{id}/acknowledge -----------------------------------------------------


@router.put("/risk/{flag_id}/acknowledge", response_model=FlagOut)
def acknowledge_flag(
    flag_id: int,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    flag = db.query(RiskFlag).filter(RiskFlag.id == flag_id).one_or_none()
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Risk flag not found")
    if flag.status != "open":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Flag is already {flag.status}, cannot acknowledge")

    flag.status = "acknowledged"
    db.commit()
    db.refresh(flag)
    return _enrich_flag_out(db, flag)


# --- POST /risk/{id}/intervention ---------------------------------------------------


class InterventionCreateRequest(BaseModel):
    note: str
    action_taken: str


class InterventionOut(BaseModel):
    id: int
    risk_flag_id: int
    created_by: int
    note: str
    action_taken: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("/risk/{flag_id}/intervention", response_model=InterventionOut)
def log_intervention(
    flag_id: int,
    body: InterventionCreateRequest,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    if not body.note.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "note must not be empty")
    if not body.action_taken.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "action_taken must not be empty")

    flag = db.query(RiskFlag).filter(RiskFlag.id == flag_id).one_or_none()
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Risk flag not found")

    intervention = Intervention(risk_flag_id=flag_id, created_by=user.id, note=body.note, action_taken=body.action_taken)
    db.add(intervention)
    db.commit()
    db.refresh(intervention)
    return InterventionOut.model_validate(intervention)


# --- PUT /risk/{id}/resolve ---------------------------------------------------------


@router.put("/risk/{flag_id}/resolve", response_model=FlagOut)
def resolve_flag(
    flag_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    flag = db.query(RiskFlag).filter(RiskFlag.id == flag_id).one_or_none()
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Risk flag not found")
    if flag.status == "resolved":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Flag is already resolved")

    flag.status = "resolved"
    flag.resolved_by = user.id
    flag.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(flag)
    return _enrich_flag_out(db, flag)


# --- GET /admin/early-warning/students ----------------------------------------------
# Reconciles with the pre-existing api-contract.md stub rather than duplicating
# /risk/flagged under a new name - same underlying data, this endpoint's role gate
# (admin/principal/teacher, no parent) and response shape (`{"items": [...]}`) match
# what was already documented and possibly already being built against.


class EarlyWarningItem(BaseModel):
    student_id: int
    risk_level: str
    reasons: list[str]
    flagged_at: datetime


class EarlyWarningResponse(BaseModel):
    items: list[EarlyWarningItem]


@router.get("/admin/early-warning/students", response_model=EarlyWarningResponse)
def early_warning_students(
    class_id: int | None = None,
    risk_level: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("admin", "principal", "teacher"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")

    query = db.query(RiskFlag).filter(RiskFlag.status != "resolved")

    if user.role == "teacher":
        owned_class_ids = _teacher_class_ids(db, user.id)
        if class_id is not None:
            if class_id not in owned_class_ids:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your class")
            owned_class_ids = [class_id]
        query = query.filter(RiskFlag.student_id.in_(_students_in_classes(db, owned_class_ids) or [-1]))
    elif class_id is not None:
        query = query.filter(RiskFlag.student_id.in_(_students_in_classes(db, [class_id]) or [-1]))

    if risk_level is not None:
        query = query.filter(RiskFlag.risk_level == risk_level)

    items = [
        EarlyWarningItem(student_id=f.student_id, risk_level=f.risk_level, reasons=f.reasons, flagged_at=f.flagged_at)
        for f in query.order_by(RiskFlag.flagged_at.desc()).all()
    ]
    return EarlyWarningResponse(items=items)
