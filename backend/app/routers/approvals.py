from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admissions import AdmissionApplication
from app.models.staffing import LeaveRequest
from app.routers.admissions import decide_admission_application
from app.routers.staffing import decide_leave_request
from app.services.approval_aggregator import aggregate_approvals
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, require_role

router = APIRouter(tags=["approvals"])

# type -> handler. "leave_request" and "admission_application" are real - see
# services/approval_aggregator.py's module docstring for what else was checked and
# ruled out. A handler takes (db, entity_id, decision, body, user) and returns the
# resulting status string for the response/audit write; it raises HTTPException
# itself for 404/400 cases specific to that entity type. Both handlers delegate to
# the SAME shared decide_*() function their entity's own dedicated router uses
# (decide_leave_request in staffing.py, decide_admission_application in
# admissions.py) so behavior is identical regardless of entry point.


def _decide_leave_request(db: Session, entity_id: int, decision: str, body: "DecisionRequest", user: CurrentUser) -> str:
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == entity_id).one_or_none()
    if leave is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found")
    if leave.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Leave request is already {leave.status}, not pending")

    db_decision = "approved" if decision == "approve" else "rejected"
    decide_leave_request(db, leave, db_decision, user.id, body.academic_year)
    write_audit_log(
        db, actor_id=user.id, action=decision, entity_type="leave_requests", entity_id=leave.id,
        detail={"comment": body.comment, "via": "unified_approvals_inbox"},
    )
    return leave.status


def _decide_admission_application(db: Session, entity_id: int, decision: str, body: "DecisionRequest", user: CurrentUser) -> str:
    # Scoped to the caller's own school - same fix as the dedicated PATCH endpoint
    # in admissions.py (found live via this session's cross-school walkthrough
    # test); without it, this second entry point to the exact same decide function
    # would have let an admin from ANY school accept/reject another school's
    # application even after the dedicated endpoint was locked down.
    application = (
        db.query(AdmissionApplication)
        .filter(AdmissionApplication.id == entity_id, AdmissionApplication.school_id == user.school_id)
        .one_or_none()
    )
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admission application not found")

    db_decision = "accepted" if decision == "approve" else "rejected"
    outcome = decide_admission_application(db, application, db_decision, user.id, body.comment)
    write_audit_log(
        db, actor_id=user.id, action=decision, entity_type="admission_applications", entity_id=application.id,
        detail={
            "comment": body.comment, "via": "unified_approvals_inbox",
            "enrollment_created": outcome.enrollment_created, "assigned_class_id": outcome.assigned_class_id,
        },
    )
    return application.status


_DECISION_HANDLERS = {
    "leave_request": _decide_leave_request,
    "admission_application": _decide_admission_application,
}


class ApprovalOut(BaseModel):
    id: str
    type: str
    requested_by: int
    requested_at: datetime
    payload: dict
    entity_type: str
    entity_id: int


class ApprovalsResponse(BaseModel):
    items: list[ApprovalOut]


# --- GET /admin/approvals ------------------------------------------------------------
# ROLE SCOPING - admin/principal only, NOT teacher, despite the original stub listing
# "teacher" as an allowed role. Reasoning: the one real approval source
# (LeaveRequest) can only be decided by admin/principal (PUT /staff/approve_leave and
# this session's decision endpoint both require that role) - a teacher is never the
# decision-maker for anything currently in this inbox. A teacher's own filed leave
# requests are already visible to them via GET /staff/leave_requests (their existing
# self-service status view) - a "pending approvals *I* need to act on" inbox with
# nothing in it for any teacher today would be a confusing empty screen, not a
# feature. Revisit this once a genuinely teacher-decidable approval source exists
# (e.g. a future feature where a teacher approves a student's request for something).


@router.get("/admin/approvals", response_model=ApprovalsResponse)
def list_approvals(
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    approvals = aggregate_approvals(db)
    return ApprovalsResponse(
        items=[
            ApprovalOut(
                id=a.id, type=a.type, requested_by=a.requested_by, requested_at=a.requested_at,
                payload=a.payload, entity_type=a.entity_type, entity_id=a.entity_id,
            )
            for a in approvals
        ]
    )


# --- POST /admin/approvals/{id}/decision ---------------------------------------------


class DecisionRequest(BaseModel):
    decision: str
    """"approve" or "reject"."""
    comment: str | None = None
    academic_year: str | None = None
    """ADDITION beyond the original api-contract.md stub - required when deciding a
    leave_request-type approval with decision="approve" (needed to resolve affected
    timetable slots for substitute-finding, exactly like PUT /staff/approve_leave
    already requires)."""


class DecisionResponse(BaseModel):
    id: str
    status: str


@router.post("/admin/approvals/{approval_id}/decision", response_model=DecisionResponse)
def decide_approval(
    approval_id: str,
    body: DecisionRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """approval_id is the composite "{type}:{entity_id}" string from GET
    /admin/approvals - e.g. "leave_request:47". Same addressing scheme as Command
    Center's POST /admin/alerts/{source}:{id}/resolve (routers/admin_alerts.py),
    reused deliberately rather than reinvented - see services/approval_aggregator.py."""
    if body.decision not in ("approve", "reject"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "decision must be 'approve' or 'reject'")

    type_, sep, raw_entity_id = approval_id.partition(":")
    if not sep or not raw_entity_id.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Malformed approval id - expected "type:entity_id"')
    entity_id = int(raw_entity_id)

    handler = _DECISION_HANDLERS.get(type_)
    if handler is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown approval type: {type_!r}")

    result_status = handler(db, entity_id, body.decision, body, user)
    db.commit()
    return DecisionResponse(id=approval_id, status=result_status)
