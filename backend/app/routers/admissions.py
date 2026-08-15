from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admissions import AdmissionApplication
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.user import User
from app.services.admissions_rules import check_eligibility, check_transition
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, require_role

router = APIRouter(tags=["admissions"])

DEFAULT_PAGE_SIZE = 20


def _offered_grades(db: Session, school_id: int, academic_year: str) -> set[str]:
    return {
        row.name
        for row in db.query(SchoolClass.name).filter(SchoolClass.school_id == school_id, SchoolClass.academic_year == academic_year)
    }


def enroll_student_primary(db: Session, student_user_id: int, class_id: int) -> bool:
    """Real, idempotent primary-enrollment creation - `Enrollment(subject_id=None,
    is_primary=True)` is this codebase's "this student's homeroom class" record
    (see the Enrollment model). Returns True iff a new row was created (False if
    the student was already primary-enrolled in that class - re-calling this is
    always safe, never creates a duplicate).

    Shared by two real, intentionally-distinct callers - not duplicated logic:
    `decide_admission_application` below (processing a NEW applicant through the
    admissions pipeline) and `routers/students.py::create_student` (onboarding an
    EXISTING roster directly, e.g. via the onboarding wizard) - see
    docs/api-contract.md's "Two ways a student gets an Enrollment" note for why
    both are real and neither is a legacy stub of the other."""
    student = db.query(User).filter(User.id == student_user_id).one_or_none()
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "student_user_id does not refer to an existing user")
    school_class = db.query(SchoolClass).filter(SchoolClass.id == class_id).one_or_none()
    if school_class is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "class_id does not refer to an existing class")

    existing = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == student_user_id, Enrollment.class_id == class_id, Enrollment.subject_id.is_(None))
        .one_or_none()
    )
    if existing is not None:
        return False
    db.add(Enrollment(student_id=student_user_id, class_id=class_id, subject_id=None, is_primary=True))
    return True


def decide_admission_application(
    db: Session,
    application: AdmissionApplication,
    new_status: str,
    actor_id: int,
    decision_justification: str | None = None,
    student_user_id: int | None = None,
    class_id: int | None = None,
) -> bool:
    """Applies a state transition via services/admissions_rules.py's legal-transition
    check (raises HTTPException(400) if illegal). Returns True iff accepting this
    application created a real Enrollment row.

    Enrollment wiring is REAL, not stubbed - but only fires when the caller supplies
    both student_user_id (an ALREADY-EXISTING user - see AdmissionApplication's own
    docstring, and routers/students.py for how a brand new one gets created) and
    class_id. Without both, acceptance still succeeds; enrollment creation is a
    documented no-op reflected in the return value, not a silent skip.

    Shared by PATCH /admin/admissions/applications/{id} and
    POST /admin/approvals/{id}/decision (routers/approvals.py) so both entry points
    are behaviorally identical - same reasoning as staffing.py's decide_leave_request."""
    transition = check_transition(application.status, new_status)
    if not transition.allowed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, transition.reason)

    application.status = new_status
    application.decided_by = actor_id
    application.decided_at = datetime.now(timezone.utc)
    if decision_justification is not None:
        application.decision_justification = decision_justification

    if new_status != "accepted" or student_user_id is None or class_id is None:
        return False

    created = enroll_student_primary(db, student_user_id, class_id)
    application.enrolled_student_id = student_user_id
    return created


# --- POST /admin/admissions/applications ---------------------------------------------


class ApplicationCreateRequest(BaseModel):
    school_id: int
    academic_year: str
    applicant_name: str
    dob: date
    guardian_email: str
    grade_applied: str
    ocr_document_ids: list[int] = []


class ApplicationOut(BaseModel):
    id: int
    school_id: int
    academic_year: str
    applicant_name: str
    dob: date
    guardian_email: str
    grade_applied: str
    ocr_document_ids: list[int]
    status: str
    submitted_by: int
    submitted_at: datetime
    decided_by: int | None
    decided_at: datetime | None
    decision_justification: str | None
    enrolled_student_id: int | None

    model_config = ConfigDict(from_attributes=True)


@router.post("/admin/admissions/applications", response_model=ApplicationOut)
def submit_application(
    body: ApplicationCreateRequest,
    user: CurrentUser = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if not body.applicant_name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "applicant_name must not be empty")

    offered = _offered_grades(db, body.school_id, body.academic_year)
    eligibility = check_eligibility(body.grade_applied, offered)
    if not eligibility.eligible:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, eligibility.reason)

    application = AdmissionApplication(
        school_id=body.school_id, academic_year=body.academic_year, applicant_name=body.applicant_name,
        dob=body.dob, guardian_email=body.guardian_email, grade_applied=body.grade_applied,
        ocr_document_ids=body.ocr_document_ids, status="submitted", submitted_by=user.id,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return ApplicationOut.model_validate(application)


# --- GET /admin/admissions/applications -----------------------------------------------


class ApplicationsListResponse(BaseModel):
    items: list[ApplicationOut]
    total: int
    page: int
    page_size: int


@router.get("/admin/admissions/applications", response_model=ApplicationsListResponse)
def list_applications(
    status_filter: str | None = Query(None, alias="status"),
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if page < 1 or page_size < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "page and page_size must be positive")

    query = db.query(AdmissionApplication)
    if status_filter is not None:
        query = query.filter(AdmissionApplication.status == status_filter)

    total = query.count()
    rows = query.order_by(AdmissionApplication.submitted_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ApplicationsListResponse(items=[ApplicationOut.model_validate(a) for a in rows], total=total, page=page, page_size=page_size)


# --- PATCH /admin/admissions/applications/{id} -----------------------------------------


class ApplicationUpdateRequest(BaseModel):
    status: str
    decision_justification: str | None = None
    student_user_id: int | None = None
    """ADDITION beyond the original stub - an already-existing user id to enroll if
    status="accepted". See decide_admission_application()'s docstring."""
    class_id: int | None = None
    """ADDITION beyond the original stub - required alongside student_user_id to
    wire a real Enrollment on acceptance."""


class ApplicationUpdateResponse(BaseModel):
    id: int
    status: str
    enrollment_created: bool


@router.patch("/admin/admissions/applications/{application_id}", response_model=ApplicationUpdateResponse)
def update_application(
    application_id: int,
    body: ApplicationUpdateRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    application = db.query(AdmissionApplication).filter(AdmissionApplication.id == application_id).one_or_none()
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admission application not found")

    enrollment_created = decide_admission_application(
        db, application, body.status, user.id, body.decision_justification, body.student_user_id, body.class_id
    )
    write_audit_log(
        db, actor_id=user.id, action=body.status, entity_type="admission_applications", entity_id=application.id,
        detail={"enrollment_created": enrollment_created, "justification": body.decision_justification},
    )
    db.commit()
    db.refresh(application)

    return ApplicationUpdateResponse(id=application.id, status=application.status, enrollment_created=enrollment_created)
