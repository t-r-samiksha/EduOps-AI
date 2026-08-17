import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admissions import AdmissionApplication
from app.models.class_ import SchoolClass
from app.models.document import Document
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.role import Role
from app.models.timetable import Room
from app.models.user import User
from app.routers.documents import DocumentDetailOut, _build_detail, _get_scoped_document_or_404
from app.services.admissions_rules import (
    SectionCandidate,
    check_eligibility,
    check_reject_reason,
    check_transition,
    grade_level_display,
    pick_section,
)
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, require_role
from app.services.notify import dispatch_notification
from app.services.supabase_admin import create_auth_account

router = APIRouter(tags=["admissions"])

DEFAULT_PAGE_SIZE = 20
DEFAULT_SECTION_CAPACITY = 30
"""Used only when a section has no home_room_id set yet (Room.capacity is real and
preferred whenever available - see _section_candidates). Matches this codebase's own
de facto Room.capacity convention - every real seed/test fixture across this project
uses 30 for an ordinary classroom."""

STUDENT_ACCOUNT_EMAIL_DOMAIN = "eduops-student.local"
"""New students admitted through this pipeline have no email of their own (correctly
- an admission form doesn't collect one, and a new LKG applicant wouldn't have one
anyway). A real, unique, clearly-synthetic account email is generated instead so a
real, genuinely login-capable Supabase Auth + local User row can still be created -
same "real account, no delivery mechanism for the credential" honesty already
established elsewhere in this codebase (e.g. FeeReminder.sent_at staying null: real
determination, no email-sending infrastructure to act on it)."""

REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE = ("marksheet", "id_proof")
"""A real hard requirement (explicit product decision, not just an informational
indicator) - accepting a student without their academic history and identity proof
on file isn't a real admission decision. Checked at accept time, not submission
time, since documents are typically linked to an application over time (via
POST .../documents) rather than all at once."""


def _missing_required_document_types(db: Session, application: AdmissionApplication) -> list[str]:
    """Which of REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE have NO document of that
    type currently linked to this application - empty list means every required
    type is covered by at least one real, school-scoped document."""
    linked_types = {
        row.document_type
        for row in db.query(Document.document_type).filter(
            Document.id.in_(application.ocr_document_ids), Document.school_id == application.school_id
        )
    }
    return [t for t in REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE if t not in linked_types]


def _offered_grade_levels(db: Session, school_id: int, academic_year: str) -> set[str]:
    """Every grade LEVEL offered by at least one real ACTIVE section - "does this
    school teach Grade 3 at all", not "does the section named X exist" (see
    admissions_rules.py's module docstring for the bug this replaced)."""
    return {
        str(row.grade_level)
        for row in db.query(SchoolClass.grade_level).filter(
            SchoolClass.school_id == school_id,
            SchoolClass.academic_year == academic_year,
            SchoolClass.is_active.is_(True),
            SchoolClass.grade_level.isnot(None),
        )
    }


def _section_candidates(db: Session, school_id: int, academic_year: str) -> list[SectionCandidate]:
    """Every real active section for this school/year, each with its real current
    primary-enrollment headcount and real capacity (Room.capacity via
    home_room_id when set, else DEFAULT_SECTION_CAPACITY - a class with no
    homeroom assigned yet still gets a sensible, documented capacity rather than
    blocking section assignment entirely)."""
    classes = (
        db.query(SchoolClass)
        .filter(
            SchoolClass.school_id == school_id,
            SchoolClass.academic_year == academic_year,
            SchoolClass.is_active.is_(True),
            SchoolClass.grade_level.isnot(None),
        )
        .all()
    )
    candidates = []
    for school_class in classes:
        capacity = DEFAULT_SECTION_CAPACITY
        if school_class.home_room_id is not None:
            room = db.query(Room).filter(Room.id == school_class.home_room_id).one_or_none()
            if room is not None:
                capacity = room.capacity
        current_count = (
            db.query(Enrollment)
            .filter(Enrollment.class_id == school_class.id, Enrollment.subject_id.is_(None))
            .count()
        )
        candidates.append(
            SectionCandidate(
                class_id=school_class.id, grade_level=school_class.grade_level,
                current_count=current_count, capacity=capacity,
            )
        )
    return candidates


def enroll_student_primary(db: Session, student_user_id: int, class_id: int) -> bool:
    """Real, idempotent primary-enrollment creation - `Enrollment(subject_id=None,
    is_primary=True)` is this codebase's "this student's homeroom class" record
    (see the Enrollment model). Returns True iff a new row was created (False if
    the student was already primary-enrolled in that class - re-calling this is
    always safe, never creates a duplicate).

    Shared by three real, intentionally-distinct callers - not duplicated logic:
    `decide_admission_application` below (processing a NEW applicant through the
    admissions pipeline), `routers/students.py::create_student` (onboarding an
    EXISTING roster directly, e.g. via the onboarding wizard), and
    `routers/students.py::_set_primary_class` (an ongoing class change) - see
    docs/api-contract.md's "Two ways a student gets an Enrollment" note for why
    these are real and neither is a legacy stub of the other."""
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


def _student_email_for_application(application: AdmissionApplication) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", application.applicant_name.lower()).strip("-") or "student"
    return f"{slug}.{application.id}@{STUDENT_ACCOUNT_EMAIL_DOMAIN}"


def _create_student_for_application(db: Session, application: AdmissionApplication) -> User:
    """A brand-new applicant, by definition, has no existing student account to
    look up - always creates one (unlike guardian resolution below, which
    genuinely may find an existing parent, e.g. for a second child). Same real
    Supabase-Auth-account-creation mechanism as routers/students.py::create_student
    - not duplicated, just inlined since this call site has no admin-supplied
    password to pass through (see STUDENT_ACCOUNT_EMAIL_DOMAIN's docstring)."""
    student_role = db.query(Role).filter(Role.name == "student").one()
    email = _student_email_for_application(application)
    password = secrets.token_urlsafe(18)
    supabase_id = create_auth_account(email=email, password=password, full_name=application.applicant_name, role="student")
    student = User(
        supabase_id=supabase_id, email=email, full_name=application.applicant_name, role_id=student_role.id,
        school_id=application.school_id, is_active=True,
    )
    db.add(student)
    db.flush()
    return student


def _existing_parent_or_conflict(db: Session, guardian_email: str) -> User | None:
    """Real guardian resolution's VALIDATION half - checked before any real account
    creation happens (see decide_admission_application's call order), same
    "validate everything local first so a bad request never creates an orphaned
    real account" principle already established by
    routers/students.py::create_student. Returns an existing PARENT user with
    this email, or None if nobody has it yet. Fails closed rather than silently
    adopting someone else's account: if guardian_email already belongs to a real
    user who ISN'T a parent (e.g. a teacher happens to share an email), that's a
    real identity conflict, not something to paper over."""
    parent_role = db.query(Role).filter(Role.name == "parent").one()
    existing = db.query(User).filter(User.email == guardian_email).one_or_none()
    if existing is None:
        return None
    if existing.role_id != parent_role.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"guardian_email {guardian_email!r} already belongs to an existing account that isn't a parent - cannot link as guardian",
        )
    return existing


def _create_parent_account(db: Session, school_id: int, guardian_email: str, guardian_name: str | None) -> User:
    """The creation half - only ever called once _existing_parent_or_conflict has
    already confirmed no real account owns this email.

    guardian_name (found live: real sam school data had parent accounts with
    full_name=None) comes from the APPLICATION's own guardian_name field - real
    end-to-end now (admission_form OCR extraction -> routing pre-fill ->
    application -> this account), not fabricated. Still genuinely nullable: an
    application submitted via the Submit tab (no document) or one whose source
    form never captured a guardian name has nothing real to give here, and a
    blank name is more honest than a guessed one."""
    parent_role = db.query(Role).filter(Role.name == "parent").one()
    password = secrets.token_urlsafe(18)
    supabase_id = create_auth_account(email=guardian_email, password=password, full_name=guardian_name, role="parent")
    parent = User(
        supabase_id=supabase_id, email=guardian_email, full_name=guardian_name,
        role_id=parent_role.id, school_id=school_id, is_active=True,
    )
    db.add(parent)
    db.flush()
    return parent


def _link_parent_student(db: Session, parent_id: int, student_id: int) -> None:
    existing = (
        db.query(ParentStudent)
        .filter(ParentStudent.parent_id == parent_id, ParentStudent.student_id == student_id)
        .one_or_none()
    )
    if existing is None:
        db.add(ParentStudent(parent_id=parent_id, student_id=student_id))
        db.flush()


@dataclass(frozen=True)
class AdmissionDecisionOutcome:
    enrollment_created: bool
    assigned_class_id: int | None = None
    enrolled_student_id: int | None = None
    parent_user_id: int | None = None
    parent_account_created: bool = False


def decide_admission_application(
    db: Session,
    application: AdmissionApplication,
    new_status: str,
    actor_id: int,
    decision_justification: str | None = None,
) -> AdmissionDecisionOutcome:
    """Applies a state transition via services/admissions_rules.py's legal-transition
    check (raises HTTPException(400) if illegal). Rejecting requires a real reason
    (check_reject_reason) - no reason, no reject.

    Accepting REQUIRES a marksheet and an id_proof already linked
    (REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE) - a real hard requirement, not just an
    informational indicator (see that constant's own docstring for the reasoning).

    Accepting is a REAL, fully automatic pipeline - not stubbed, not manual:
    1. Auto-assign the least-filled real active section at the requested
       grade_level with room (pick_section) - 400 with a clear reason if none
       have room; never silently overfills, never invents a new section.
    2. Create a real, genuinely login-capable student account (Supabase Auth +
       local User row) - a brand-new applicant always needs one.
    3. Resolve guardian_email to a real existing parent account or create one.
    4. Link them via a real ParentStudent row.
    5. Enroll the new student in the assigned section (enroll_student_primary).

    Shared by PATCH /admin/admissions/applications/{id} and
    POST /admin/approvals/{id}/decision (routers/approvals.py) so both entry points
    are behaviorally identical - same reasoning as staffing.py's decide_leave_request.

    Atomicity note: EVERY check that can still fail (transition legality, reject
    reason, grade_applied parses as a real int, a section has room, guardian_email
    doesn't conflict with a non-parent account) runs BEFORE any mutation - the
    application's own status/decided_by/decided_at is only ever set once none of
    those can fail anymore. Found live via this function's own test suite: an
    earlier version set application.status = "accepted" before checking section
    capacity, so a failed "no seats available" accept still left the application
    mutated toward "accepted" within the request's DB transaction - a real
    half-applied state, not just a cosmetic ordering nit."""
    transition = check_transition(application.status, new_status)
    if not transition.allowed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, transition.reason)

    reject_error = check_reject_reason(new_status, decision_justification)
    if reject_error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, reject_error)

    assignment = None
    existing_parent = None
    if new_status == "accepted":
        missing_types = _missing_required_document_types(db, application)
        if missing_types:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Cannot accept: missing required document(s) - {', '.join(missing_types)}. "
                "Attach them (Document OCR page) before accepting.",
            )

        try:
            grade_level = int(application.grade_applied)
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"grade_applied {application.grade_applied!r} is not a valid grade level - cannot auto-assign a section",
            )

        candidates = _section_candidates(db, application.school_id, application.academic_year)
        assignment = pick_section(grade_level, application.academic_year, candidates)
        if assignment.class_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, assignment.reason)

        # Validate the guardian situation BEFORE creating any real account - a bad
        # request (email conflict) must never leave a real, orphaned Supabase Auth
        # account behind (see _existing_parent_or_conflict's own docstring).
        existing_parent = _existing_parent_or_conflict(db, application.guardian_email)

    # Every check above that could still fail has passed - safe to mutate now.
    application.status = new_status
    application.decided_by = actor_id
    application.decided_at = datetime.now(timezone.utc)
    if decision_justification is not None:
        application.decision_justification = decision_justification

    # Placed here, before the reject-path early return below, so ONE call covers both
    # outcomes. Only reaches a guardian who ALREADY has an account: on the accept path
    # a brand-new parent account may be created further down, and that guardian has no
    # user row to notify at this point (they get their credentials out-of-band anyway).
    guardian = db.query(User).filter(User.email == application.guardian_email).one_or_none()
    if guardian is not None:
        dispatch_notification(
            db, user_id=guardian.id, source_type="admission_decision",
            title=f"Admission application {new_status}",
            body=f"{application.applicant_name}, grade {application.grade_applied}",
            priority="important", source_id=application.id,
        )

    if new_status != "accepted":
        return AdmissionDecisionOutcome(enrollment_created=False)

    student = _create_student_for_application(db, application)
    if existing_parent is not None:
        parent, parent_created = existing_parent, False
    else:
        parent = _create_parent_account(db, application.school_id, application.guardian_email, application.guardian_name)
        parent_created = True

    _link_parent_student(db, parent.id, student.id)
    created = enroll_student_primary(db, student.id, assignment.class_id)
    application.enrolled_student_id = student.id

    return AdmissionDecisionOutcome(
        enrollment_created=created,
        assigned_class_id=assignment.class_id,
        enrolled_student_id=student.id,
        parent_user_id=parent.id,
        parent_account_created=parent_created,
    )


# --- POST /admin/admissions/applications ---------------------------------------------


class ApplicationCreateRequest(BaseModel):
    school_id: int
    academic_year: str
    applicant_name: str
    dob: date
    guardian_email: str
    guardian_name: str | None = None
    """Optional - not every submission path has it (the Submit tab doesn't ask for
    it explicitly), but when present (typically via the admission_form OCR routing
    pre-fill), it becomes the real name on the guardian account created at accept
    time (see _create_parent_account) - the fix for a real gap found live (sam
    school: real parent accounts with full_name=None)."""
    guardian_phone: str | None = None
    grade_applied: str
    """A stringified grade LEVEL (e.g. "3", "-2" for LKG) - see
    AdmissionApplication.grade_applied's own docstring."""
    ocr_document_ids: list[int] = []


class ApplicationOut(BaseModel):
    id: int
    school_id: int
    academic_year: str
    applicant_name: str
    dob: date
    guardian_email: str
    guardian_name: str | None
    guardian_phone: str | None
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


class ApplicationDetailOut(ApplicationOut):
    """The single-application GET response - adds full per-document detail (not
    just ids) for every linked document, so an admin reviewing one application
    sees the applicant's declared info AND every supporting document's extracted
    fields without a separate round-trip per document. Reuses documents.py's own
    DocumentDetailOut/_build_detail rather than re-deriving a second shape for the
    same data."""

    documents: list[DocumentDetailOut]


def _build_application_detail(db: Session, application: AdmissionApplication) -> ApplicationDetailOut:
    """Resolves every id in ocr_document_ids to a full DocumentDetailOut, scoped to
    the application's own school and in list order. Silently skips any id that
    doesn't resolve (e.g. a document deleted after linking) rather than 500ing -
    the same "don't crash on stale references" posture as the rest of this file."""
    docs_by_id = {
        d.id: d
        for d in db.query(Document).filter(
            Document.id.in_(application.ocr_document_ids), Document.school_id == application.school_id
        )
    }
    documents = [_build_detail(db, docs_by_id[doc_id]) for doc_id in application.ocr_document_ids if doc_id in docs_by_id]
    return ApplicationDetailOut(**ApplicationOut.model_validate(application).model_dump(), documents=documents)


@router.post("/admin/admissions/applications", response_model=ApplicationOut)
def submit_application(
    body: ApplicationCreateRequest,
    user: CurrentUser = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if not body.applicant_name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "applicant_name must not be empty")

    offered = _offered_grade_levels(db, body.school_id, body.academic_year)
    eligibility = check_eligibility(body.grade_applied, offered)
    if not eligibility.eligible:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, eligibility.reason)

    application = AdmissionApplication(
        school_id=body.school_id, academic_year=body.academic_year, applicant_name=body.applicant_name,
        dob=body.dob, guardian_email=body.guardian_email, guardian_name=body.guardian_name,
        guardian_phone=body.guardian_phone, grade_applied=body.grade_applied,
        ocr_document_ids=body.ocr_document_ids, status="submitted", submitted_by=user.id,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return ApplicationOut.model_validate(application)


# --- GET /admin/admissions/grade-levels -----------------------------------------------


class GradeLevelOut(BaseModel):
    grade_level: int
    display: str


class GradeLevelsResponse(BaseModel):
    items: list[GradeLevelOut]


@router.get("/admin/admissions/grade-levels", response_model=GradeLevelsResponse)
def list_offered_grade_levels(
    school_id: int,
    academic_year: str,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """Real offered grade levels for a school/year, with a friendly display label -
    backs the Submit form's "Grade applied" dropdown (grade LEVEL only, never a
    specific section - see this module's docstring) so an admin picks from what's
    actually real instead of typing a value that may not match anything."""
    offered = _offered_grade_levels(db, school_id, academic_year)
    levels = sorted(int(g) for g in offered)
    return GradeLevelsResponse(items=[GradeLevelOut(grade_level=g, display=grade_level_display(g)) for g in levels])


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

    # Scoped to the caller's own school - found live (via a real cross-school login
    # during this session's manual walkthrough) that this endpoint had NO school_id
    # filter at all, unlike every comparable list endpoint in this codebase
    # (students.py/teachers.py/parents.py all filter on User.school_id) - any
    # admin/principal from any school could see every other school's applications.
    query = db.query(AdmissionApplication).filter(AdmissionApplication.school_id == user.school_id)
    if status_filter is not None:
        query = query.filter(AdmissionApplication.status == status_filter)

    total = query.count()
    rows = query.order_by(AdmissionApplication.submitted_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ApplicationsListResponse(items=[ApplicationOut.model_validate(a) for a in rows], total=total, page=page, page_size=page_size)


def _get_scoped_application_or_404(db: Session, application_id: int, school_id: int | None) -> AdmissionApplication:
    application = (
        db.query(AdmissionApplication)
        .filter(AdmissionApplication.id == application_id, AdmissionApplication.school_id == school_id)
        .one_or_none()
    )
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admission application not found")
    return application


@router.get("/admin/admissions/applications/{application_id}", response_model=ApplicationDetailOut)
def get_application(
    application_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """Single-application detail - an addition beyond the original list-only stub,
    backing the real applicant detail view (full info + every linked OCR
    document's full detail, not just ids - see ApplicationDetailOut).

    Scoped to the caller's own school (same fix/reasoning as list_applications above) -
    a real id from another school 404s exactly like an unknown id, rather than leaking
    whether it exists."""
    application = _get_scoped_application_or_404(db, application_id, user.school_id)
    return _build_application_detail(db, application)


# --- PATCH /admin/admissions/applications/{id}/details -------------------------------
# Genuinely separate from correcting a linked OCR document's own extracted fields
# (PUT /admin/ocr/documents/{id}/entities/{entity_id}) - found live: an admin
# corrected a document's applicant_name and expected the application (already
# created from it) to update too. It never did - correcting a document only ever
# fixed that document's own record, with no path back to an application already
# built from it. This is the real, explicit, audited way to fix a mistake in the
# application's OWN declared details instead of expecting an unrelated document
# edit to silently propagate into it.


class ApplicationDetailsUpdateRequest(BaseModel):
    applicant_name: str | None = None
    dob: date | None = None
    guardian_email: str | None = None
    guardian_name: str | None = None
    guardian_phone: str | None = None


@router.patch("/admin/admissions/applications/{application_id}/details", response_model=ApplicationDetailOut)
def update_application_details(
    application_id: int,
    body: ApplicationDetailsUpdateRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """Partial update (only supplied fields change) - blocked once accepted: a real
    student/parent account and Enrollment already exist based on these exact
    values by that point, so editing them afterward would silently diverge the
    application's own record from the real accounts already created from it.
    Editing while submitted/under_review/rejected is fine - none of those states
    have created anything real from this data yet (or, for rejected, ever will)."""
    application = _get_scoped_application_or_404(db, application_id, user.school_id)

    if application.status == "accepted":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot edit an accepted application's details - a real student/parent account already exists from these values.",
        )

    if body.applicant_name is not None:
        if not body.applicant_name.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "applicant_name must not be empty")
        application.applicant_name = body.applicant_name.strip()
    if body.dob is not None:
        application.dob = body.dob
    if body.guardian_email is not None:
        if not body.guardian_email.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "guardian_email must not be empty")
        application.guardian_email = body.guardian_email.strip()
    if body.guardian_name is not None:
        application.guardian_name = body.guardian_name.strip() or None
    if body.guardian_phone is not None:
        application.guardian_phone = body.guardian_phone.strip() or None

    write_audit_log(
        db, actor_id=user.id, action="edit_details", entity_type="admission_applications", entity_id=application.id,
        detail={
            "applicant_name": body.applicant_name, "dob": body.dob.isoformat() if body.dob else None,
            "guardian_email": body.guardian_email, "guardian_name": body.guardian_name, "guardian_phone": body.guardian_phone,
        },
    )
    db.commit()
    db.refresh(application)
    return _build_application_detail(db, application)


# --- POST /admin/admissions/applications/{id}/documents ------------------------------
# A real application starts life with at most one linked document (the admission_form
# that routed into it - see ocr_routing.py). In a real intake process the parent also
# hands over a marksheet and ID proof, uploaded separately (marksheet/id_proof have no
# routing handler of their own - see ocr_routing.py's module docstring for why those
# stay honest stubs) - this is the missing link that lets an already-uploaded document
# of ANY type be attached to an application after the fact, so an admin reviewing it
# sees everything in one place before deciding.


class AttachDocumentRequest(BaseModel):
    document_id: int


# Deliberate: no restriction on application.status below - attaching a document is
# record-keeping (evidence for a decision), not a decision itself, unlike
# accept/reject which the state machine in admissions_rules.py DOES gate. A
# late-arriving ID proof for an already-accepted student is still worth keeping
# on file.
@router.post("/admin/admissions/applications/{application_id}/documents", response_model=ApplicationDetailOut)
def attach_document(
    application_id: int,
    body: AttachDocumentRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    application = _get_scoped_application_or_404(db, application_id, user.school_id)
    # Same-school check on the document too - reuses documents.py's own scoped
    # lookup rather than re-deriving a second "document not found vs. wrong school,
    # same 404" check.
    document = _get_scoped_document_or_404(db, body.document_id, application.school_id)

    if document.id not in application.ocr_document_ids:
        # Reject double-linking to a DIFFERENT application - found live (real sam
        # school data: document #1119 ended up in two applications' ocr_document_ids
        # from before this check existed), which then crashed
        # documents.py::_linked_application_for_document (MultipleResultsFound - a
        # document is assumed to belong to at most one application). A document is
        # evidence for one applicant; attaching it elsewhere first requires
        # detaching it, not silently cloning the link.
        existing_link = (
            db.query(AdmissionApplication.id, AdmissionApplication.applicant_name)
            .filter(
                AdmissionApplication.school_id == application.school_id,
                AdmissionApplication.id != application.id,
                AdmissionApplication.ocr_document_ids.contains([document.id]),
            )
            .first()
        )
        if existing_link is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Document #{document.id} is already attached to a different application "
                f"(#{existing_link.id}, {existing_link.applicant_name}) - a document can only belong to one application.",
            )

        # Full reassignment (not an in-place .append()) - SQLAlchemy only detects a
        # JSONB column as dirty on a new list object, not a mutated one.
        application.ocr_document_ids = application.ocr_document_ids + [document.id]
        write_audit_log(
            db, actor_id=user.id, action="attach_document", entity_type="admission_applications",
            entity_id=application.id, detail={"document_id": document.id, "document_type": document.document_type},
        )
        db.commit()
        db.refresh(application)
    # Already-linked is a no-op, not an error - idempotent, same posture as
    # _link_parent_student above.

    return _build_application_detail(db, application)


# --- PATCH /admin/admissions/applications/{id} -----------------------------------------


class ApplicationUpdateRequest(BaseModel):
    status: str
    decision_justification: str | None = None
    """Required (non-empty) when status="rejected" - see check_reject_reason.
    Optional for "under_review"/"accepted"."""


class ApplicationUpdateResponse(BaseModel):
    id: int
    status: str
    enrollment_created: bool
    assigned_class_id: int | None = None
    """Set only on a successful acceptance - the real, auto-assigned section."""
    enrolled_student_id: int | None = None
    parent_user_id: int | None = None
    parent_account_created: bool = False
    """True iff accepting this application created a BRAND NEW parent account
    (guardian_email didn't already belong to one) - False when an existing
    parent (e.g. a sibling's application) was found and reused instead."""


@router.patch("/admin/admissions/applications/{application_id}", response_model=ApplicationUpdateResponse)
def update_application(
    application_id: int,
    body: ApplicationUpdateRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    # Scoped to the caller's own school (same fix/reasoning as list_applications
    # above) - without this an admin from ANY school could accept/reject another
    # school's application outright, not just view it.
    application = (
        db.query(AdmissionApplication)
        .filter(AdmissionApplication.id == application_id, AdmissionApplication.school_id == user.school_id)
        .one_or_none()
    )
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admission application not found")

    outcome = decide_admission_application(db, application, body.status, user.id, body.decision_justification)
    write_audit_log(
        db, actor_id=user.id, action=body.status, entity_type="admission_applications", entity_id=application.id,
        detail={
            "enrollment_created": outcome.enrollment_created,
            "justification": body.decision_justification,
            "assigned_class_id": outcome.assigned_class_id,
            "parent_account_created": outcome.parent_account_created,
        },
    )
    db.commit()
    db.refresh(application)

    return ApplicationUpdateResponse(
        id=application.id, status=application.status, enrollment_created=outcome.enrollment_created,
        assigned_class_id=outcome.assigned_class_id, enrolled_student_id=outcome.enrolled_student_id,
        parent_user_id=outcome.parent_user_id, parent_account_created=outcome.parent_account_created,
    )
