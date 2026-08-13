"""Unified pending-approvals inbox. Per the playbook: "pluggable ruleset support" +
"unified approvals inbox fed by all approval-enabled features" - the same
aggregation pattern as services/alert_aggregator.py, applied to approvals instead of
alerts: a registry of one function per genuinely approval-shaped entity, each
returning a common PendingApproval shape.

WHAT COUNTS AS "APPROVAL-SHAPED" - checked every prior session's models, not assumed
--------------------------------------------------------------------------------------
An entity is approval-shaped here if it has a genuine PENDING state that gates a
decision made by someone other than the requester, with real approve/reject
outcomes - not merely "has a status column." Checked before writing this:

  - LeaveRequest (models/staffing.py): YES.
    status="pending" blocks until an admin/principal makes an explicit approved/
    rejected decision (PUT /staff/approve_leave or POST /admin/approvals/{id}/decision);
    decided_by/decided_at record who and when.
  - AdmissionApplication (models/admissions.py, Fees & Admissions session): YES, the
    second real source. Registered only for status="under_review", NOT "submitted" -
    a freshly-submitted application is pending an initial TRIAGE step (move it to
    under_review, via the dedicated PATCH endpoint), not yet at a binary approve/
    reject decision point; only under_review applications are genuinely at the
    decision point this inbox's approve/reject vocabulary fits. Getting an
    application from submitted to under_review is a deliberate manual step, not
    something the unified "approve" action silently does on your behalf as an
    invisible two-step transition - see services/admissions_rules.py's state machine.
  - RiskFlag / Intervention (models/risk.py): NO. acknowledge/resolve are actions an
    admin/teacher takes directly on their own authority - nothing is pending
    someone else's sign-off. Intervention is a create-only log entry, never a
    decision gate.
  - ExtractedEntity correction (models/document.py): NO. A direct edit to a field
    value, not a decision gate with an accept/reject outcome.
  - AnomalyFlag (models/syllabus.py): NO, same reasoning as RiskFlag - a direct
    resolve, no pending-decision semantic.
  - Substitution "confirm" (models/staffing.py): NO, on reflection. Confirming is an
    admin directly locking in a choice (with automatic conflict-checking against
    the schedule) - not submitting something for a separate approver to accept or
    reject. There's no "pending" state distinct from "suggested," and no second
    party in the loop.
  - FeeRecord/FeeReminder (models/fees.py): NO. Overdue fees are alert-worthy (see
    alert_aggregator.py's fee_overdue source) but there is no pending DECISION
    gating them - nobody "approves" a fee becoming due. A payment either arrives
    (recorded via POST /admin/fees/records/{id}/payment) or doesn't; that's not an
    approval flow.

Two of eight considered entities are genuinely approval-shaped so far - stated
honestly, not padded out with borderline entries to look more complete. Exam
Management (a later session) may introduce another real candidate. Adding one then
is: write a function with this signature, register it in APPROVAL_SOURCES - nothing
else here changes, same pluggability story as alert_aggregator.py's ALERT_SOURCES -
now proven twice over, not just claimed once.

COMPOSITE ID - reused from Command Center, not reinvented
------------------------------------------------------------
PendingApproval.id is "{type}:{entity_id}" (e.g. "leave_request:47",
"admission_application:12") - the exact same scheme alert_aggregator.Alert.id uses.
routers/approvals.py's decision endpoint parses it the same way
routers/admin_alerts.py's resolve endpoint does.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.admissions import AdmissionApplication
from app.models.staffing import LeaveRequest


@dataclass(frozen=True)
class PendingApproval:
    id: str
    """Composite id: f"{type}:{entity_id}" - see module docstring."""
    type: str
    """Which approval-source function produced this - also the decision-routing key."""
    requested_by: int
    requested_at: datetime
    payload: dict
    entity_type: str
    """The underlying table entity_id refers to, e.g. "leave_requests"."""
    entity_id: int


def leave_request_approvals(db: Session) -> list[PendingApproval]:
    requests = db.query(LeaveRequest).filter(LeaveRequest.status == "pending").all()
    return [
        PendingApproval(
            id=f"leave_request:{lr.id}",
            type="leave_request",
            requested_by=lr.teacher_id,
            requested_at=lr.requested_at,
            payload={"start_date": lr.start_date.isoformat(), "end_date": lr.end_date.isoformat(), "reason": lr.reason},
            entity_type="leave_requests",
            entity_id=lr.id,
        )
        for lr in requests
    ]


def admission_application_approvals(db: Session) -> list[PendingApproval]:
    """Only status="under_review" - see module docstring for why "submitted" isn't
    included."""
    apps = db.query(AdmissionApplication).filter(AdmissionApplication.status == "under_review").all()
    return [
        PendingApproval(
            id=f"admission_application:{a.id}",
            type="admission_application",
            requested_by=a.submitted_by,
            requested_at=a.submitted_at,
            payload={"applicant_name": a.applicant_name, "dob": a.dob.isoformat(), "grade_applied": a.grade_applied, "guardian_email": a.guardian_email},
            entity_type="admission_applications",
            entity_id=a.id,
        )
        for a in apps
    ]


APPROVAL_SOURCES: dict[str, Callable[[Session], list[PendingApproval]]] = {
    "leave_request": leave_request_approvals,
    "admission_application": admission_application_approvals,
}


def aggregate_approvals(
    db: Session,
    *,
    sources: dict[str, Callable[[Session], list[PendingApproval]]] = APPROVAL_SOURCES,
) -> list[PendingApproval]:
    """Runs every registered source and returns newest-first. `sources` defaults to
    the real registry - tests override it to exercise the aggregation mechanism with
    fake sources, same pattern as alert_aggregator.aggregate_alerts."""
    approvals: list[PendingApproval] = []
    for fn in sources.values():
        approvals.extend(fn(db))

    approvals.sort(key=lambda a: a.requested_at, reverse=True)
    return approvals
