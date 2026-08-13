"""Unified alert feed for the admin command center - "the single screen admins live
in", per the playbook. This is an AGGREGATION feature, not a new data source: every
alert here is read live from a table some other feature already owns and writes to
(RiskFlag, LeaveRequest, Substitution, Document/ExtractedEntity,
AttendanceReconciliation, AnomalyFlag, FeeRecord). Nothing in this module ever
creates or mutates one of those rows for the purpose of generating an alert.

PLUGGABLE ALERT SOURCES
-----------------------------
Per the playbook: "Pluggable alert modules for each integrated feature." ALERT_SOURCES
is a registry of `(name, function)` pairs; each function takes a `Session` and returns
`list[Alert]`. Adding a future alert source (e.g. Syllabus drift, once that's built)
means writing one new function with this same signature and adding it to
ALERT_SOURCES - nothing else in this module changes.

Not fully ORM-free like risk_scorer.py/ocr_postprocess.py: aggregation is inherently
"read across several tables", so each source function does take a `Session` and
query directly, the same way routers/risk.py's list_flagged does. "Testable
standalone" here means testable by calling these functions directly against a
`db_session` fixture with constructed rows - no HTTP/FastAPI layer required - not
that they're free of the ORM entirely.

SEVERITY - exactly two levels, "normal" and "urgent", documented per source below.
Not a third "info"/"warning" tier - the playbook's own examples only ever need two,
and a flatter scheme is easier for a future notification UI to act on unambiguously
(page someone now, or don't).

RESOLVE ROUTING - risk_flag/anomaly_flag vs. everything else, and why they differ
--------------------------------------------------------------------------------
`routers/admin_alerts.py`'s resolve endpoint needs one consistent contract for every
alert `source`, but the sources genuinely don't have the same underlying mechanism:

  - risk_flag / anomaly_flag: both already have a real terminal `status="resolved"`
    transition on their own row (see PUT /risk/{id}/resolve and PUT
    /admin/anomalies/{id}/resolve, from the Early-Warning and Syllabus/Anomaly
    sessions respectively) - resolving the alert routes directly to that same real
    status field. No separate dismissal state needed or wanted for either; duplicating
    it would create two "resolved" concepts for one entity.
  - leave_request / substitution: their real next states are decisions with
    consequences (approve/reject a leave triggers substitute-finding; confirming a
    substitution needs a chosen teacher) made through their own dedicated endpoints
    (PUT /staff/approve_leave, PUT /substitution/{id}/confirm) - a generic "resolve"
    must NOT fake one of those decisions. Once the real decision is made elsewhere,
    the alert naturally stops being generated (its source query only selects
    pending/unconfirmed rows) - no dismissal needed for that path either.
  - document_failed / document_low_confidence / attendance_reconciliation: none of
    these have a generic single-action "resolved" concept in their own table (a
    failed OCR document has no "acknowledged" flag; a low-confidence field's real
    resolution is the correction flow, which may not happen immediately). This is
    the genuine case of "cross-cutting dismissal state that doesn't map to any
    source table" - see models/alerts.py's AlertDismissal for the (intentionally
    tiny) table that exists solely for this.

A KNOWN GAP, NOT SILENTLY SOLVED: /timetable/update's conflict-detection
(_find_conflicts in routers/timetable.py) is purely transient - conflicts are
returned in the response and never persisted anywhere. There is therefore no table
to read a "timetable conflict" alert from today. Retrofitting persistence onto that
endpoint is a real design decision (would it log every attempted conflicting edit,
or only ones that actually blocked a save?) that belongs to whoever owns that
endpoint's UX, not something to bolt on silently from the alerts side. Not included
as a source.

CONSIDERED AND DECLINED: InvigilationAssignment as a 9th source (Exam Management
session). Substitution's escalation rule works because an unconfirmed substitution
is a genuine open gap - the admin must act before the leave date or a class goes
uncovered. InvigilationAssignment doesn't have that same shape: routers/exams.py's
schedule-generation only ever creates a row once a real teacher has actually been
assigned (see services/exam_scheduler.py) - `status` stays "assigned" for
everything created this session because no confirm/decline endpoint was built (not
requested). An "unconfirmed, close to date" alert on a status that has no path to
ever change would be perpetually true and, worse, wouldn't link to any action a
click-through could resolve. The real analogous gap - a room an exam needs covered
that got NO invigilator at all - is surfaced instead, directly and synchronously, in
POST /admin/exams/{id}/schedules's own response (`unassigned_rooms`), right where an
admin generating the schedule can act on it immediately, rather than routed through
an async alert a day later. Revisit if a real confirm/decline flow is ever added for
invigilation duties.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.attendance import AttendanceReconciliation
from app.models.document import Document, ExtractedEntity
from app.models.fees import FeeRecord
from app.models.risk import RiskFlag
from app.models.staffing import LeaveRequest, Substitution
from app.models.syllabus import AnomalyFlag

SEVERITY_LEVELS = ("normal", "urgent")

SUBSTITUTION_URGENT_WINDOW_DAYS = 3
"""An unconfirmed Substitution escalates to urgent once its leave_request.start_date
is within this many days (or already past). Substitution itself carries no calendar
date of its own (it's tied to a recurring timetable_slot, not a specific occurrence)
- the leave's start_date is the closest real proxy for "when coverage is needed",
and is used here as a documented judgment call, not a modeled certainty."""


@dataclass(frozen=True)
class Alert:
    id: str
    """Composite id: f"{source}:{entity_id}" - e.g. "risk_flag:43". See this
    module's docstring and routers/admin_alerts.py for the resolve-routing contract
    built on this. entity_id alone is not unique across sources, so this is the only
    safe identifier to hand to a client."""
    source: str
    """Which alert-generator function produced this - also the resolve-routing key."""
    severity: str
    """One of SEVERITY_LEVELS."""
    title: str
    message: str
    entity_type: str
    """The underlying table entity_id refers to, e.g. "risk_flags", "documents"."""
    entity_id: int
    created_at: datetime
    resolved: bool
    """Always False for anything aggregate_alerts() returns today - every source
    function only queries currently-unresolved rows in the first place, and
    dismissed alerts are filtered out by aggregate_alerts(). Kept on the dataclass
    for shape completeness (e.g. a future "recently resolved" admin view could reuse
    this same shape), not because a True value is reachable from this module alone."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- individual alert sources ------------------------------------------------------


def risk_flag_alerts(db: Session) -> list[Alert]:
    """Open/acknowledged high-risk students. urgent only while status="open" AND
    risk_level="high" - once acknowledged, someone is already on it, so it's
    downgraded to normal rather than continuing to shout. Resolved flags are
    excluded by the query itself (matches /risk/flagged's own convention)."""
    flags = db.query(RiskFlag).filter(RiskFlag.status != "resolved").all()
    alerts = []
    for flag in flags:
        urgent = flag.risk_level == "high" and flag.status == "open"
        alerts.append(
            Alert(
                id=f"risk_flag:{flag.id}",
                source="risk_flag",
                severity="urgent" if urgent else "normal",
                title=f"Student risk flag ({flag.risk_level})",
                message="; ".join(flag.reasons) if flag.reasons else "No reasons recorded",
                entity_type="risk_flags",
                entity_id=flag.id,
                created_at=flag.flagged_at,
                resolved=False,
            )
        )
    return alerts


def leave_request_alerts(db: Session) -> list[Alert]:
    """Pending leave requests awaiting an approve/reject decision. Always normal
    severity per the playbook's own example - a pending leave is routine admin
    workload, not an emergency (a *near-date unconfirmed substitution* stemming from
    an approved leave is the thing that escalates - see substitution_alerts)."""
    requests = db.query(LeaveRequest).filter(LeaveRequest.status == "pending").all()
    return [
        Alert(
            id=f"leave_request:{lr.id}",
            source="leave_request",
            severity="normal",
            title="Pending leave request",
            message=f"Teacher {lr.teacher_id} requested leave {lr.start_date} to {lr.end_date}: {lr.reason}",
            entity_type="leave_requests",
            entity_id=lr.id,
            created_at=lr.requested_at,
            resolved=False,
        )
        for lr in requests
    ]


def substitution_alerts(db: Session, today: date | None = None) -> list[Alert]:
    """Unconfirmed (status="suggested") substitutions - no substitute teacher locked
    in yet. Escalates to urgent within SUBSTITUTION_URGENT_WINDOW_DAYS of the
    covering leave's start_date (or already past it). created_at uses the parent
    LeaveRequest.requested_at as a proxy - Substitution itself has no creation
    timestamp of its own (see this module's docstring)."""
    today = today or _utcnow().date()
    subs = (
        db.query(Substitution, LeaveRequest)
        .join(LeaveRequest, Substitution.leave_request_id == LeaveRequest.id)
        .filter(Substitution.status == "suggested")
        .all()
    )
    alerts = []
    for sub, leave in subs:
        days_until = (leave.start_date - today).days
        urgent = days_until <= SUBSTITUTION_URGENT_WINDOW_DAYS
        alerts.append(
            Alert(
                id=f"substitution:{sub.id}",
                source="substitution",
                severity="urgent" if urgent else "normal",
                title="Unconfirmed substitution",
                message=(
                    f"Slot {sub.timetable_slot_id} (originally teacher {sub.original_teacher_id}) "
                    f"needs a confirmed substitute - covering leave starts {leave.start_date}"
                ),
                entity_type="substitutions",
                entity_id=sub.id,
                created_at=leave.requested_at,
                resolved=False,
            )
        )
    return alerts


def document_failed_alerts(db: Session) -> list[Alert]:
    """Documents where OCR processing itself failed. Urgent: Document.file_url is a
    descriptive reference only (see models/document.py) - the uploaded image bytes
    are never persisted, so a failed document cannot simply be retried without
    re-uploading the original paper form again. Losing that recoverability window is
    a real operational risk, not just a processing hiccup."""
    docs = db.query(Document).filter(Document.status == "failed").all()
    return [
        Alert(
            id=f"document_failed:{doc.id}",
            source="document_failed",
            severity="urgent",
            title="Document OCR failed",
            message=f"Document {doc.id} ({doc.document_type}) failed OCR processing and cannot be retried without re-upload",
            entity_type="documents",
            entity_id=doc.id,
            created_at=doc.processed_at or doc.uploaded_at,
            resolved=False,
        )
        for doc in docs
    ]


def document_low_confidence_alerts(db: Session) -> list[Alert]:
    """Documents with at least one extracted field flagged is_low_confidence and not
    yet corrected. One alert per DOCUMENT (not per field) - a document with several
    shaky fields shouldn't flood the feed with duplicates for what's really one "go
    review this upload" task. Always normal per the playbook's own example."""
    rows = (
        db.query(ExtractedEntity.document_id)
        .filter(ExtractedEntity.is_low_confidence.is_(True), ExtractedEntity.corrected_value.is_(None))
        .distinct()
        .all()
    )
    document_ids = [r.document_id for r in rows]
    if not document_ids:
        return []
    docs = db.query(Document).filter(Document.id.in_(document_ids)).all()
    return [
        Alert(
            id=f"document_low_confidence:{doc.id}",
            source="document_low_confidence",
            severity="normal",
            title="Document has low-confidence extracted fields",
            message=f"Document {doc.id} ({doc.document_type}) has uncorrected low-confidence OCR fields - review and correct",
            entity_type="documents",
            entity_id=doc.id,
            created_at=doc.processed_at or doc.uploaded_at,
            resolved=False,
        )
        for doc in docs
    ]


def attendance_reconciliation_alerts(db: Session) -> list[Alert]:
    """Pending CV/RFID attendance mismatches awaiting manual review. Included for
    completeness (the table and its status field are real, already-shipped schema -
    see models/attendance.py), but honestly expect this to always return empty today:
    nothing populates AttendanceReconciliation yet since RFID ingestion (and the
    reconciliation job that would compare it against CV) is a later session, per that
    model's own docstring. Not a new feature - just wiring an existing empty pipe
    into the feed so it lights up automatically once that work lands, no aggregator
    changes needed then."""
    rows = db.query(AttendanceReconciliation).filter(AttendanceReconciliation.status == "pending").all()
    return [
        Alert(
            id=f"attendance_reconciliation:{r.id}",
            source="attendance_reconciliation",
            severity="normal",
            title="Attendance record mismatch",
            message=f"Student {r.student_id} attendance on {r.date} needs manual review ({r.reason})",
            entity_type="attendance_reconciliations",
            entity_id=r.id,
            created_at=r.created_at,
            resolved=False,
        )
        for r in rows
    ]


def anomaly_flag_alerts(db: Session) -> list[Alert]:
    """Open AnomalyFlag rows (services/anomaly_detector.py + syllabus_pace.py, via
    scripts/run_nightly_syllabus_anomaly_scan.py) - the 7th alert source, added in
    the Syllabus Tracking & Anomaly Detection session. `severity` is copied straight
    from the row: AnomalyFlag.severity was deliberately defined to already match
    SEVERITY_LEVELS (see models/syllabus.py), so there's no re-derivation here, unlike
    risk_flag's open-vs-acknowledged nuance. `message` is read from
    detail["message"] - populated by the nightly scan when it writes the row (see
    that script's `_upsert_flag`) - rather than re-deriving formatting logic here
    that would have to know about every anomaly `type`."""
    flags = db.query(AnomalyFlag).filter(AnomalyFlag.status != "resolved").all()
    return [
        Alert(
            id=f"anomaly_flag:{flag.id}",
            source="anomaly_flag",
            severity=flag.severity,
            title=f"Anomaly: {flag.type}",
            message=flag.detail.get("message", f"{flag.type} anomaly on {flag.entity_type}:{flag.entity_id}"),
            entity_type=flag.entity_type,
            entity_id=flag.entity_id,
            created_at=flag.detected_at,
            resolved=False,
        )
        for flag in flags
    ]


FEE_OVERDUE_URGENT_DAYS = 30
"""Matches services/fee_reminder_engine.py's own third/"escalated" reminder tier
threshold, deliberately - "urgent" here and "escalated" there should agree on what
counts as seriously overdue rather than each inventing its own independent number."""


def fee_overdue_alerts(db: Session, today: date | None = None) -> list[Alert]:
    """Open FeeRecord rows in status="overdue" - the 8th alert source, added in the
    Fees & Admissions session. Severity escalates at FEE_OVERDUE_URGENT_DAYS, same
    threshold services/fee_reminder_engine.py treats as its final escalated tier."""
    today = today or _utcnow().date()
    records = db.query(FeeRecord).filter(FeeRecord.status == "overdue").all()
    alerts = []
    for r in records:
        days_overdue = (today - r.due_date).days
        balance = round(r.amount_due - r.amount_paid, 2)
        alerts.append(
            Alert(
                id=f"fee_overdue:{r.id}",
                source="fee_overdue",
                severity="urgent" if days_overdue >= FEE_OVERDUE_URGENT_DAYS else "normal",
                title="Overdue fee",
                message=f"Student {r.student_id} has {balance} overdue, {days_overdue} days past due date {r.due_date}",
                entity_type="fee_records",
                entity_id=r.id,
                created_at=r.created_at,
                resolved=False,
            )
        )
    return alerts


ALERT_SOURCES: dict[str, Callable[[Session], list[Alert]]] = {
    "risk_flag": risk_flag_alerts,
    "leave_request": leave_request_alerts,
    "substitution": substitution_alerts,
    "document_failed": document_failed_alerts,
    "document_low_confidence": document_low_confidence_alerts,
    "attendance_reconciliation": attendance_reconciliation_alerts,
    "anomaly_flag": anomaly_flag_alerts,
    "fee_overdue": fee_overdue_alerts,
}


def aggregate_alerts(
    db: Session,
    *,
    dismissed_ids: set[str] | None = None,
    since: datetime | None = None,
    severity: str | None = None,
    sources: dict[str, Callable[[Session], list[Alert]]] = ALERT_SOURCES,
) -> list[Alert]:
    """Runs every registered source, filters out dismissed/since/severity, and
    returns newest-first. `sources` defaults to the real registry - tests override it
    to exercise the aggregation mechanism with fake sources without depending on
    every real table."""
    dismissed_ids = dismissed_ids or set()

    alerts: list[Alert] = []
    for fn in sources.values():
        alerts.extend(fn(db))

    alerts = [a for a in alerts if a.id not in dismissed_ids]
    if since is not None:
        alerts = [a for a in alerts if a.created_at >= since]
    if severity is not None:
        alerts = [a for a in alerts if a.severity == severity]

    alerts.sort(key=lambda a: a.created_at, reverse=True)
    return alerts


def summarize_alerts(alerts: list[Alert]) -> dict:
    """Counts-by-severity and counts-by-source, for GET /admin/alerts/summary."""
    by_severity = {level: 0 for level in SEVERITY_LEVELS}
    by_source: dict[str, int] = {}
    for a in alerts:
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
        by_source[a.source] = by_source.get(a.source, 0) + 1
    return {"total": len(alerts), "by_severity": by_severity, "by_source": by_source}
