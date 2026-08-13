from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.class_ import SchoolClass
from app.models.subject import Subject
from app.models.syllabus import AnomalyFlag, SyllabusCheckpoint, SyllabusPlan
from app.models.timetable import TimetableSlot
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.syllabus_pace import SyllabusPlanInput, compute_pace

router = APIRouter(tags=["syllabus-tracking"])


def _teacher_class_subject_pairs(db: Session, teacher_id: int) -> set[tuple[int, int]]:
    """Which (class_id, subject_id) pairs a teacher actually teaches, per active
    TimetableSlot - the accurate "own subjects" signal for role-scoping, since a
    class's homeroom teacher (SchoolClass.class_teacher_id) is often a different
    person than who teaches a given subject to that class."""
    rows = (
        db.query(TimetableSlot.class_id, TimetableSlot.subject_id)
        .filter(TimetableSlot.teacher_id == teacher_id, TimetableSlot.is_active.is_(True))
        .distinct()
        .all()
    )
    return {(r.class_id, r.subject_id) for r in rows}


# --- POST /syllabus/plan ------------------------------------------------------------
# NOT in the task's endpoint list - added because without some way to create a
# SyllabusPlan through the API, POST /syllabus/checkpoint would have nothing to
# attach to (SyllabusPlan.total_units/term dates can't be inferred from a checkpoint
# alone). Flagged here and in the summary, same pattern as Command Center's
# GET /admin/alerts/summary addition last session.


class PlanCreateRequest(BaseModel):
    class_id: int
    subject_id: int
    academic_year: str
    total_units: int
    term_start_date: date
    term_end_date: date


class PlanOut(BaseModel):
    id: int
    class_id: int
    subject_id: int
    academic_year: str
    total_units: int
    term_start_date: date
    term_end_date: date
    created_by: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("/syllabus/plan", response_model=PlanOut)
def create_plan(
    body: PlanCreateRequest,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    if body.total_units <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "total_units must be positive")
    if body.term_end_date <= body.term_start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "term_end_date must be after term_start_date")
    if db.query(SchoolClass).filter(SchoolClass.id == body.class_id).one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    if db.query(Subject).filter(Subject.id == body.subject_id).one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")

    plan = SyllabusPlan(
        class_id=body.class_id, subject_id=body.subject_id, academic_year=body.academic_year,
        total_units=body.total_units, term_start_date=body.term_start_date, term_end_date=body.term_end_date,
        created_by=user.id,
    )
    db.add(plan)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A syllabus plan already exists for this class/subject/academic_year") from exc
    db.refresh(plan)
    return PlanOut.model_validate(plan)


# --- POST /syllabus/checkpoint -------------------------------------------------------


class CheckpointCreateRequest(BaseModel):
    plan_id: int
    topic_label: str
    sequence_number: int


class CheckpointOut(BaseModel):
    id: int
    plan_id: int
    topic_label: str
    sequence_number: int
    logged_by: int
    logged_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("/syllabus/checkpoint", response_model=CheckpointOut)
def log_checkpoint(
    body: CheckpointCreateRequest,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    if not body.topic_label.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "topic_label must not be empty")

    plan = db.query(SyllabusPlan).filter(SyllabusPlan.id == body.plan_id).one_or_none()
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus plan not found")

    if user.role == "teacher" and (plan.class_id, plan.subject_id) not in _teacher_class_subject_pairs(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your subject")

    checkpoint = SyllabusCheckpoint(
        plan_id=body.plan_id, topic_label=body.topic_label, sequence_number=body.sequence_number, logged_by=user.id
    )
    db.add(checkpoint)
    db.commit()
    db.refresh(checkpoint)
    return CheckpointOut.model_validate(checkpoint)


# --- GET /syllabus/summary -----------------------------------------------------------


class SummaryItem(BaseModel):
    plan_id: int
    class_id: int
    class_name: str
    subject_id: int
    subject_name: str
    academic_year: str
    total_units: int
    checkpoints_logged: int
    term_start_date: date
    term_end_date: date
    expected_fraction: float
    actual_fraction: float
    drift: float
    status: str


class SummaryResponse(BaseModel):
    items: list[SummaryItem]


@router.get("/syllabus/summary", response_model=SummaryResponse)
def syllabus_summary(
    class_id: int | None = None,
    subject_id: int | None = None,
    academic_year: str | None = None,
    today: date | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in ("teacher", "admin", "principal"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")

    query = db.query(SyllabusPlan)
    if class_id is not None:
        query = query.filter(SyllabusPlan.class_id == class_id)
    if subject_id is not None:
        query = query.filter(SyllabusPlan.subject_id == subject_id)
    if academic_year is not None:
        query = query.filter(SyllabusPlan.academic_year == academic_year)

    plans = query.all()

    if user.role == "teacher":
        owned_pairs = _teacher_class_subject_pairs(db, user.id)
        plans = [p for p in plans if (p.class_id, p.subject_id) in owned_pairs]

    today = today or datetime.now(timezone.utc).date()
    items = []
    for plan in plans:
        checkpoints_logged = db.query(SyllabusCheckpoint).filter(SyllabusCheckpoint.plan_id == plan.id).count()
        result = compute_pace(
            SyllabusPlanInput(
                plan_id=plan.id, class_id=plan.class_id, subject_id=plan.subject_id,
                total_units=plan.total_units, term_start_date=plan.term_start_date,
                term_end_date=plan.term_end_date, checkpoints_logged=checkpoints_logged,
            ),
            today,
        )
        school_class = db.query(SchoolClass).filter(SchoolClass.id == plan.class_id).one_or_none()
        subject = db.query(Subject).filter(Subject.id == plan.subject_id).one_or_none()
        items.append(
            SummaryItem(
                plan_id=plan.id, class_id=plan.class_id, class_name=school_class.name if school_class else "",
                subject_id=plan.subject_id, subject_name=subject.name if subject else "",
                academic_year=plan.academic_year, total_units=plan.total_units, checkpoints_logged=checkpoints_logged,
                term_start_date=plan.term_start_date, term_end_date=plan.term_end_date,
                expected_fraction=result.expected_fraction, actual_fraction=result.actual_fraction,
                drift=result.drift, status=result.status,
            )
        )
    return SummaryResponse(items=items)


# --- GET /admin/anomalies, PUT /admin/anomalies/{id}/resolve ------------------------
# GET /admin/anomalies is a genuinely new addition (no prior api-contract.md stub
# existed for anomaly detection at all) - flagged here and in docs. Resolving here
# duplicates PUT /risk/{id}/resolve's own precedent of a dedicated resolve endpoint
# existing *alongside* the unified /admin/alerts/{source}:{id}/resolve path from the
# Command Center session, rather than one replacing the other - see
# routers/admin_alerts.py, which now treats anomaly_flag identically to risk_flag.


class AnomalyOut(BaseModel):
    id: int
    type: str
    entity_type: str
    entity_id: int
    severity: str
    detail: dict
    detected_at: datetime
    status: str
    resolved_by: int | None
    resolved_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class AnomaliesResponse(BaseModel):
    items: list[AnomalyOut]


@router.get("/admin/anomalies", response_model=AnomaliesResponse)
def list_anomalies(
    type: str | None = None,
    severity: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    query = db.query(AnomalyFlag)
    if type is not None:
        query = query.filter(AnomalyFlag.type == type)
    if severity is not None:
        query = query.filter(AnomalyFlag.severity == severity)
    if status_filter is not None:
        query = query.filter(AnomalyFlag.status == status_filter)
    else:
        query = query.filter(AnomalyFlag.status != "resolved")

    flags = query.order_by(AnomalyFlag.detected_at.desc()).all()
    return AnomaliesResponse(items=[AnomalyOut.model_validate(f) for f in flags])


@router.put("/admin/anomalies/{anomaly_id}/resolve", response_model=AnomalyOut)
def resolve_anomaly(
    anomaly_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    flag = db.query(AnomalyFlag).filter(AnomalyFlag.id == anomaly_id).one_or_none()
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Anomaly flag not found")
    if flag.status == "resolved":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Anomaly flag is already resolved")

    flag.status = "resolved"
    flag.resolved_by = user.id
    flag.resolved_at = datetime.now(timezone.utc)
    write_audit_log(db, actor_id=user.id, action="resolve", entity_type="anomaly_flags", entity_id=flag.id)
    db.commit()
    db.refresh(flag)
    return AnomalyOut.model_validate(flag)
