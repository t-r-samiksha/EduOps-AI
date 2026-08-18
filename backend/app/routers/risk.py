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
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.notify import dispatch_bulk
from app.services.scoping import classes_taught_by

router = APIRouter(tags=["early-warning"])

VALID_RISK_LEVELS = ("low", "medium", "high")
RISK_LEVEL_DEFAULT_SCORE = {"low": 0.2, "medium": 0.5, "high": 0.8}
"""Nominal score for a manually-created flag when the caller doesn't supply one -
matches the low/medium/high midpoints implied by risk_scorer.py's own thresholds."""


def _teacher_class_ids(db: Session, teacher_id: int) -> list[int]:
    """Classes this teacher is responsible for: homeroom UNION anything they teach.

    WAS HOMEROOM-ONLY (`SchoolClass.class_teacher_id == teacher_id`), which meant a SUBJECT
    teacher saw an empty Early-Warning page. Every flag was filtered to students in classes
    they are the homeroom teacher of - so the Maths teacher for Grade 3-B could not see that
    a student they teach five periods a week had been flagged, and a teacher with no homeroom
    at all (which is normal) saw nothing anywhere, ever. The page rendered "No flagged
    students" rather than an error, so it looked like good news instead of a permissions gap.

    Delegates to services/scoping.py::classes_taught_by, whose docstring already records
    this exact finding on the real Riverside data: scoping Meera Iyer by homeroom cut her
    from 12 students to 2 and removed Grade 3-B entirely, and Kavya Reddy went to zero.

    KEEPING THE PRIVATE NAME. routers/fees.py:22-24 documents the per-router-copy convention
    deliberately, so this stays a thin wrapper rather than churning every call site - the
    behaviour is what was wrong, not the indirection.
    """
    return classes_taught_by(db, teacher_id)


def _students_in_classes(db: Session, class_ids: list[int]) -> set[int]:
    if not class_ids:
        return set()
    return {
        row.student_id
        for row in db.query(Enrollment.student_id).filter(
            Enrollment.class_id.in_(class_ids), Enrollment.is_primary.is_(True)
        )
    }


def _students_in_school(db: Session, school_id: int | None) -> set[int]:
    """Every real student belonging to this school - RiskFlag has no school_id
    of its own (only student_id), so admin/principal scoping has to go
    through User.school_id. Without this, an admin/principal from ANY school
    saw every OTHER school's flagged students too - a real cross-tenant leak,
    only visible once two real schools existed in the same DB at once (see
    routers/timetable.py's GET /timetable/active for the same class of fix
    applied earlier)."""
    if school_id is None:
        return set()
    return {row.id for row in db.query(User.id).filter(User.school_id == school_id)}


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
    # Flush (not commit) so flag.id exists for source_id and _enrich_flag_out can
    # resolve the audience - the notification then commits atomically with the flag
    # below, per services/notify.py's contract.
    db.flush()
    out = _enrich_flag_out(db, flag)
    # The parent_ids/homeroom_teacher_id enrichment above was built for exactly this
    # and had no consumer until now (see _enrich_flag_out's docstring).
    dispatch_bulk(
        db,
        user_ids=[*out.parent_ids, *([out.homeroom_teacher_id] if out.homeroom_teacher_id is not None else [])],
        source_type="early_warning",
        title=f"{out.student_name or 'A student'} flagged as {flag.risk_level} risk",
        body="; ".join(flag.reasons),
        priority="urgent" if flag.risk_level == "high" else "important",
        source_id=flag.id,
    )
    db.commit()
    db.refresh(flag)
    return out


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
        query = query.filter(RiskFlag.student_id.in_(_students_in_school(db, user.school_id) or [-1]))
        if class_id is not None:
            query = query.filter(RiskFlag.student_id.in_(_students_in_classes(db, [class_id]) or [-1]))
        if student_id is not None:
            query = query.filter(RiskFlag.student_id == student_id)
    elif user.role == "teacher":
        owned_class_ids = _teacher_class_ids(db, user.id)
        if class_id is not None:
            if class_id not in owned_class_ids:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "You do not teach this class section"
                )
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


def _load_flag_for_staff(db: Session, user: CurrentUser, flag_id: int) -> RiskFlag:
    """Fetch a flag the caller is actually allowed to act on.

    NOTHING CHECKED THIS. `acknowledge_flag`, `log_intervention` and `resolve_flag` each
    looked the flag up by id alone, so any authenticated teacher or admin could acknowledge,
    intervene on, or resolve a flag for a student in ANOTHER SCHOOL by incrementing the id -
    and `log_intervention` would write their name into that school's intervention history.
    `GET /risk/flagged` was scoped from the start, so the read path was safe and the write
    paths were not, which is why it went unnoticed.

    404 rather than 403 for a flag outside the caller's school, so ids in other tenants
    cannot be probed by status code - same convention as report_cards.py's student check.
    """
    flag = db.query(RiskFlag).filter(RiskFlag.id == flag_id).one_or_none()
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Risk flag not found")

    # MIRRORS GET /risk/flagged's OWN BRANCHES, deliberately - one rule per role, so what a
    # caller can act on can never drift from what they can see (dead buttons on a visible
    # flag, or worse, a live button on one they cannot).
    if user.role == "teacher":
        # Teaching the student IS the authority here, and it is inherently school-scoped:
        # the classes come from this teacher's own homeroom/timetable rows. Deliberately NOT
        # also comparing user.school_id - User.school_id is nullable, and a teacher with a
        # real class assignment but no school column set must still be able to act on their
        # own students. 403: they are a legitimate teacher, just not this student's.
        if flag.student_id not in _students_in_classes(db, _teacher_class_ids(db, user.id)):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Not authorized to act on this student's flag"
            )
        return flag

    # admin/principal: the flag's student must be in their school. THIS is the cross-tenant
    # fix - RiskFlag carries no school_id of its own, so without going through the student
    # an admin could acknowledge, intervene on, or resolve ANY school's flag by incrementing
    # the id, and log_intervention would write their name into that school's history.
    # 404 not 403 so ids in other tenants cannot be probed by status code.
    student_ids = _students_in_school(db, user.school_id)
    if flag.student_id not in student_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Risk flag not found")

    return flag


# --- PUT /risk/{id}/acknowledge -----------------------------------------------------


@router.put("/risk/{flag_id}/acknowledge", response_model=FlagOut)
def acknowledge_flag(
    flag_id: int,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    flag = _load_flag_for_staff(db, user, flag_id)
    if flag.status != "open":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Flag is already {flag.status}, cannot acknowledge")

    flag.status = "acknowledged"
    write_audit_log(db, actor_id=user.id, action="acknowledge", entity_type="risk_flags", entity_id=flag.id)
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
    created_by_name: str | None = None
    """Resolved on the list endpoint so the UI can show who acted without an extra request
    per row. Left None on the create response, where the caller is the actor."""
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

    _load_flag_for_staff(db, user, flag_id)

    intervention = Intervention(risk_flag_id=flag_id, created_by=user.id, note=body.note, action_taken=body.action_taken)
    db.add(intervention)
    db.flush()
    write_audit_log(
        db, actor_id=user.id, action="create", entity_type="interventions", entity_id=intervention.id,
        detail={"risk_flag_id": flag_id, "action_taken": body.action_taken},
    )
    db.commit()
    db.refresh(intervention)
    return InterventionOut.model_validate(intervention)


# --- GET /risk/{id}/interventions ---------------------------------------------------


class InterventionListOut(BaseModel):
    items: list[InterventionOut]


@router.get("/risk/{flag_id}/interventions", response_model=InterventionListOut)
def list_interventions(
    flag_id: int,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """The history of what staff actually did about a flagged student, newest first.

    WHY THIS EXISTS. `POST /risk/{id}/intervention` had NO read counterpart - interventions
    were write-only. A teacher could log "called parent, no answer", the row saved, and then
    nothing anywhere in the app ever displayed it: not on the flag, not on the student, not
    in any report. So the feature was indistinguishable from broken (the dialog closed and
    nothing changed on screen), and the next teacher had no way to know an outreach had
    already been made - which is the entire point of an intervention log.

    `created_by_name` is resolved here so the UI can show WHO acted without a second
    request per row.
    """
    _load_flag_for_staff(db, user, flag_id)

    rows = (
        db.query(Intervention)
        .filter(Intervention.risk_flag_id == flag_id)
        # id as tiebreak: created_at is a server_default now(), which is identical for rows
        # written in the same transaction, so ordering on it alone is unstable.
        .order_by(Intervention.created_at.desc(), Intervention.id.desc())
        .all()
    )
    authors = {
        u.id: u
        for u in db.query(User).filter(User.id.in_([r.created_by for r in rows] or [-1])).all()
    }
    return InterventionListOut(
        items=[
            InterventionOut(
                id=r.id,
                risk_flag_id=r.risk_flag_id,
                created_by=r.created_by,
                created_by_name=(
                    authors[r.created_by].full_name or authors[r.created_by].email
                    if r.created_by in authors
                    else None
                ),
                note=r.note,
                action_taken=r.action_taken,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


# --- PUT /risk/{id}/resolve ---------------------------------------------------------


@router.put("/risk/{flag_id}/resolve", response_model=FlagOut)
def resolve_flag(
    flag_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    # Same cross-tenant gap the other two mutations had - an admin could resolve another
    # school's flag by id. The gate is a no-op on the teacher branch here (this route is
    # admin/principal only) but keeps all three mutations on one rule.
    flag = _load_flag_for_staff(db, user, flag_id)
    if flag.status == "resolved":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Flag is already resolved")

    flag.status = "resolved"
    flag.resolved_by = user.id
    flag.resolved_at = datetime.now(timezone.utc)
    write_audit_log(db, actor_id=user.id, action="resolve", entity_type="risk_flags", entity_id=flag.id)
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
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "You do not teach this class section"
                )
            owned_class_ids = [class_id]
        query = query.filter(RiskFlag.student_id.in_(_students_in_classes(db, owned_class_ids) or [-1]))
    else:
        # admin/principal - same real cross-tenant leak as GET /risk/flagged
        # had (see _students_in_school's docstring): without this, an admin
        # from ANY school saw every school's flagged students.
        query = query.filter(RiskFlag.student_id.in_(_students_in_school(db, user.school_id) or [-1]))
        if class_id is not None:
            query = query.filter(RiskFlag.student_id.in_(_students_in_classes(db, [class_id]) or [-1]))

    if risk_level is not None:
        query = query.filter(RiskFlag.risk_level == risk_level)

    items = [
        EarlyWarningItem(student_id=f.student_id, risk_level=f.risk_level, reasons=f.reasons, flagged_at=f.flagged_at)
        for f in query.order_by(RiskFlag.flagged_at.desc()).all()
    ]
    return EarlyWarningResponse(items=items)
