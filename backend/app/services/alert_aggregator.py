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

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.attendance import AttendanceReconciliation
from app.models.class_ import SchoolClass
from app.models.document import Document, ExtractedEntity
from app.models.fees import FeeRecord, has_outstanding_balance
from app.models.risk import RiskFlag
from app.models.staffing import LeaveRequest, Substitution
from app.models.subject import Subject
from app.models.syllabus import AnomalyFlag, SyllabusPlan
from app.models.timetable import TimetableSlot
from app.models.user import User

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


def _user_ids_in_school(db: Session, school_id: int | None) -> set[int]:
    """Every real user (student or teacher) belonging to this school - most alert
    source tables only reach a school via a *_id FK into users.id, not a school_id
    column of their own. Mirrors routers/risk.py's _students_in_school (same
    underlying gap, just reused across every source below instead of one endpoint)."""
    if school_id is None:
        return set()
    return {row.id for row in db.query(User.id).filter(User.school_id == school_id)}


def _class_ids_in_school(db: Session, school_id: int | None) -> set[int]:
    if school_id is None:
        return set()
    return {row.id for row in db.query(SchoolClass.id).filter(SchoolClass.school_id == school_id)}


def _user_names(db: Session, user_ids: Iterable[int | None]) -> dict[int, str]:
    """user_id -> display name, batched into one query per source function.

    Alert.message is a single pre-formatted string the frontend renders verbatim
    (components/alerts/AlertRow.tsx passes it straight through to EntityCard) - there
    is no structured teacher_id/student_id field on the alert for the client to
    resolve against GET /reference/lookup itself, so a human-readable name has to be
    baked in here at build time. That's why this lives in the aggregator rather than
    being pushed to the client like every other id->name resolution in this codebase.

    Falls back full_name -> email -> "User {id}" so a user row with no profile name
    still reads as something identifiable instead of blanking out.
    """
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = db.query(User.id, User.full_name, User.email).filter(User.id.in_(ids)).all()
    return {row.id: (row.full_name or row.email or f"User {row.id}") for row in rows}


def _slot_descriptions(db: Session, slot_ids: Iterable[int | None]) -> dict[int, str]:
    """timetable_slot_id -> "Period 3, Mathematics (Class 8A)". Same reasoning as
    _user_names: a bare "Slot 4821" in the substitution alert is as unreadable as a
    bare teacher id was, and the client can't resolve it from the flat message string.
    Slots missing from the map (deleted/regenerated timetable) fall back to the id."""
    ids = {i for i in slot_ids if i is not None}
    if not ids:
        return {}
    rows = (
        db.query(TimetableSlot.id, TimetableSlot.period_number, Subject.name, SchoolClass.name)
        .join(Subject, TimetableSlot.subject_id == Subject.id)
        .join(SchoolClass, TimetableSlot.class_id == SchoolClass.id)
        .filter(TimetableSlot.id.in_(ids))
        .all()
    )
    return {
        slot_id: f"Period {period}, {subject_name} ({class_name})"
        for slot_id, period, subject_name, class_name in rows
    }


def _named(names: dict[int, str], user_id: int, role_label: str) -> str:
    """Renders a user for message text, degrading to the old id-only form only when
    the user row genuinely can't be found (deleted account, cross-school row filtered
    out of the batch) - never silently dropping the identifier entirely."""
    return names.get(user_id, f"{role_label} {user_id}")


# --- individual alert sources ------------------------------------------------------
# Every source below takes an optional `school_id`, defaulting to None ("no
# scoping - return every school's rows") so the existing single-school unit tests in
# test_alert_aggregator.py that call these directly keep working unchanged.
# aggregate_alerts() always receives a real school_id from routers/admin_alerts.py at
# the API boundary - the None default only matters for direct/unit-level calls.


def risk_flag_alerts(db: Session, school_id: int | None = None) -> list[Alert]:
    """Open/acknowledged high-risk students. urgent only while status="open" AND
    risk_level="high" - once acknowledged, someone is already on it, so it's
    downgraded to normal rather than continuing to shout. Resolved flags are
    excluded by the query itself (matches /risk/flagged's own convention)."""
    query = db.query(RiskFlag).filter(RiskFlag.status != "resolved")
    if school_id is not None:
        query = query.filter(RiskFlag.student_id.in_(_user_ids_in_school(db, school_id) or [-1]))
    flags = query.all()
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


def leave_request_alerts(db: Session, school_id: int | None = None) -> list[Alert]:
    """Pending leave requests awaiting an approve/reject decision. Always normal
    severity per the playbook's own example - a pending leave is routine admin
    workload, not an emergency (a *near-date unconfirmed substitution* stemming from
    an approved leave is the thing that escalates - see substitution_alerts)."""
    query = db.query(LeaveRequest).filter(LeaveRequest.status == "pending")
    if school_id is not None:
        query = query.filter(LeaveRequest.teacher_id.in_(_user_ids_in_school(db, school_id) or [-1]))
    requests = query.all()
    names = _user_names(db, (lr.teacher_id for lr in requests))
    return [
        Alert(
            id=f"leave_request:{lr.id}",
            source="leave_request",
            severity="normal",
            title="Pending leave request",
            message=(
                f"{_named(names, lr.teacher_id, 'Teacher')} requested leave "
                f"{lr.start_date} to {lr.end_date}: {lr.reason}"
            ),
            entity_type="leave_requests",
            entity_id=lr.id,
            created_at=lr.requested_at,
            resolved=False,
        )
        for lr in requests
    ]


def substitution_alerts(db: Session, school_id: int | None = None, today: date | None = None) -> list[Alert]:
    """Unconfirmed (status="suggested") substitutions - no substitute teacher locked
    in yet. Escalates to urgent within SUBSTITUTION_URGENT_WINDOW_DAYS of the
    covering leave's start_date (or already past it). created_at uses the parent
    LeaveRequest.requested_at as a proxy - Substitution itself has no creation
    timestamp of its own (see this module's docstring). Scoped via the covering
    LeaveRequest.teacher_id, the same anchor leave_request_alerts uses - Substitution
    itself has no direct FK to a school either."""
    today = today or _utcnow().date()
    query = (
        db.query(Substitution, LeaveRequest)
        .join(LeaveRequest, Substitution.leave_request_id == LeaveRequest.id)
        .filter(Substitution.status == "suggested")
    )
    if school_id is not None:
        query = query.filter(LeaveRequest.teacher_id.in_(_user_ids_in_school(db, school_id) or [-1]))
    subs = query.all()
    names = _user_names(db, (sub.original_teacher_id for sub, _leave in subs))
    slots = _slot_descriptions(db, (sub.timetable_slot_id for sub, _leave in subs))
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
                    f"{slots.get(sub.timetable_slot_id, f'Slot {sub.timetable_slot_id}')} "
                    f"(normally {_named(names, sub.original_teacher_id, 'teacher')}) "
                    f"needs a confirmed substitute - covering leave starts {leave.start_date}"
                ),
                entity_type="substitutions",
                entity_id=sub.id,
                created_at=leave.requested_at,
                resolved=False,
            )
        )
    return alerts


def document_failed_alerts(db: Session, school_id: int | None = None) -> list[Alert]:
    """Documents where OCR processing itself failed. Urgent: Document.file_url is a
    descriptive reference only (see models/document.py) - the uploaded image bytes
    are never persisted, so a failed document cannot simply be retried without
    re-uploading the original paper form again. Losing that recoverability window is
    a real operational risk, not just a processing hiccup. Document carries its own
    (nullable) school_id column directly - a null-school_id document stays invisible
    here too, matching every other school_id-scoped document endpoint."""
    query = db.query(Document).filter(Document.status == "failed")
    if school_id is not None:
        query = query.filter(Document.school_id == school_id)
    docs = query.all()
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


def document_low_confidence_alerts(db: Session, school_id: int | None = None) -> list[Alert]:
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
    query = db.query(Document).filter(Document.id.in_(document_ids))
    if school_id is not None:
        query = query.filter(Document.school_id == school_id)
    docs = query.all()
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


def attendance_reconciliation_alerts(db: Session, school_id: int | None = None) -> list[Alert]:
    """Pending CV/RFID attendance mismatches awaiting manual review. Included for
    completeness (the table and its status field are real, already-shipped schema -
    see models/attendance.py), but honestly expect this to always return empty today:
    nothing populates AttendanceReconciliation yet since RFID ingestion (and the
    reconciliation job that would compare it against CV) is a later session, per that
    model's own docstring. Not a new feature - just wiring an existing empty pipe
    into the feed so it lights up automatically once that work lands, no aggregator
    changes needed then."""
    query = db.query(AttendanceReconciliation).filter(AttendanceReconciliation.status == "pending")
    if school_id is not None:
        query = query.filter(AttendanceReconciliation.student_id.in_(_user_ids_in_school(db, school_id) or [-1]))
    rows = query.all()
    names = _user_names(db, (r.student_id for r in rows))
    return [
        Alert(
            id=f"attendance_reconciliation:{r.id}",
            source="attendance_reconciliation",
            severity="normal",
            title="Attendance record mismatch",
            message=(
                f"{_named(names, r.student_id, 'Student')}'s attendance on {r.date} "
                f"needs manual review ({r.reason})"
            ),
            entity_type="attendance_reconciliations",
            entity_id=r.id,
            created_at=r.created_at,
            resolved=False,
        )
        for r in rows
    ]


def _anomaly_flag_in_school(db: Session, flag: AnomalyFlag, school_id: int) -> bool:
    """AnomalyFlag.entity_id is polymorphic - which table it names depends on
    entity_type (see that model's docstring) - so unlike every other source there's
    no single FK to join on. entity_type is one of exactly 4 real values today
    (services/anomaly_detector.py, scripts/run_nightly_syllabus_anomaly_scan.py):
    "classes", "users", "documents", "syllabus_plans". Any other value fails CLOSED
    (returns False, i.e. hidden) rather than guessing - the same "don't show it if
    you can't prove it's yours" rule as every other source's school_id filter."""
    if flag.entity_type == "classes":
        return flag.entity_id in _class_ids_in_school(db, school_id)
    if flag.entity_type == "users":
        return flag.entity_id in _user_ids_in_school(db, school_id)
    if flag.entity_type == "documents":
        doc = db.query(Document.school_id).filter(Document.id == flag.entity_id).one_or_none()
        return doc is not None and doc.school_id == school_id
    if flag.entity_type == "syllabus_plans":
        plan = db.query(SyllabusPlan.class_id).filter(SyllabusPlan.id == flag.entity_id).one_or_none()
        return plan is not None and plan.class_id in _class_ids_in_school(db, school_id)
    return False


def anomaly_flag_alerts(db: Session, school_id: int | None = None) -> list[Alert]:
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
    if school_id is not None:
        flags = [f for f in flags if _anomaly_flag_in_school(db, f, school_id)]
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


def fee_overdue_alerts(db: Session, school_id: int | None = None, today: date | None = None) -> list[Alert]:
    """Fee records with money still owed past their due date - the 8th alert source,
    added in the Fees & Admissions session. Severity escalates at
    FEE_OVERDUE_URGENT_DAYS, same threshold services/fee_reminder_engine.py treats as
    its final escalated tier. FeeRecord has no school_id of its own (only
    student_id/fee_schedule_id - see models/fees.py) so scoping goes through the
    student, same as risk_flag.

    PARTIALLY PAID COUNTS AS OVERDUE, and used not to. This filtered on
    `status == "overdue"` alone, but recording any payment flips a record to
    "partial" - so paying 1 rupee of a 350 rupee fee removed it from this feed
    entirely, 30 days late and 349 rupees short. Paying part of a debt made the school
    stop tracking it, which is backwards: a partial payer is still a debtor, and a
    more actionable one than someone who has paid nothing.

    Uses `has_outstanding_balance` so this and the reminder engine agree about what
    "still owed" means, rather than each carrying its own status list.
    """
    today = today or _utcnow().date()
    query = db.query(FeeRecord).filter(has_outstanding_balance(today))
    if school_id is not None:
        query = query.filter(FeeRecord.student_id.in_(_user_ids_in_school(db, school_id) or [-1]))
    records = query.all()
    names = _user_names(db, (r.student_id for r in records))
    alerts = []
    for r in records:
        days_overdue = (today - r.due_date).days
        balance = round(r.amount_due - r.amount_paid, 2)
        part_paid = r.amount_paid > 0
        alerts.append(
            Alert(
                id=f"fee_overdue:{r.id}",
                source="fee_overdue",
                severity="urgent" if days_overdue >= FEE_OVERDUE_URGENT_DAYS else "normal",
                title="Partly paid fee overdue" if part_paid else "Overdue fee",
                message=(
                    f"{_named(names, r.student_id, 'Student')} has {balance} overdue, "
                    f"{days_overdue} days past due date {r.due_date}"
                    + (f" ({r.amount_paid} of {r.amount_due} paid)" if part_paid else "")
                ),
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
    school_id: int | None = None,
    dismissed_ids: set[str] | None = None,
    since: datetime | None = None,
    severity: str | None = None,
    sources: dict[str, Callable[..., list[Alert]]] = ALERT_SOURCES,
) -> list[Alert]:
    """Runs every registered source, filters out dismissed/since/severity, and
    returns newest-first. `sources` defaults to the real registry - tests override it
    to exercise the aggregation mechanism with fake sources without depending on
    every real table.

    `school_id` is the real, previously-missing cross-tenant scope: every registered
    source function accepts it (see each one's own docstring for how it's applied),
    but only when passed here explicitly - routers/admin_alerts.py always passes the
    calling admin/principal's real user.school_id. Left as None (the default) this
    behaves exactly as before school-scoping existed, which is what lets the
    existing single-school unit tests in test_alert_aggregator.py (and the
    fake-source tests here, whose lambdas only take `db`) keep working unchanged."""
    dismissed_ids = dismissed_ids or set()

    alerts: list[Alert] = []
    for fn in sources.values():
        alerts.extend(fn(db, school_id) if school_id is not None else fn(db))

    alerts = [a for a in alerts if a.id not in dismissed_ids]
    if since is not None:
        alerts = [a for a in alerts if a.created_at >= since]
    if severity is not None:
        alerts = [a for a in alerts if a.severity == severity]

    alerts.sort(key=lambda a: a.created_at, reverse=True)
    return alerts


def alert_belongs_to_school(db: Session, source: str, entity_id: int, school_id: int) -> bool:
    """The write-side twin of every source function's school_id filter above - used
    by routers/admin_alerts.py's resolve endpoint so an admin can't resolve/dismiss
    another school's alert just by guessing its "{source}:{entity_id}" id (that id is
    handed to any admin/principal client via GET /admin/alerts, so it's guessable in
    the sense that any admin of ANY school can construct one). Mirrors each source's
    own school_id join rather than re-deriving one; unknown/unrecognized sources fail
    closed (False)."""
    if source == "risk_flag":
        row = db.query(RiskFlag.student_id).filter(RiskFlag.id == entity_id).one_or_none()
        return row is not None and row.student_id in _user_ids_in_school(db, school_id)
    if source == "leave_request":
        row = db.query(LeaveRequest.teacher_id).filter(LeaveRequest.id == entity_id).one_or_none()
        return row is not None and row.teacher_id in _user_ids_in_school(db, school_id)
    if source == "substitution":
        row = (
            db.query(LeaveRequest.teacher_id)
            .join(Substitution, Substitution.leave_request_id == LeaveRequest.id)
            .filter(Substitution.id == entity_id)
            .one_or_none()
        )
        return row is not None and row.teacher_id in _user_ids_in_school(db, school_id)
    if source in ("document_failed", "document_low_confidence"):
        row = db.query(Document.school_id).filter(Document.id == entity_id).one_or_none()
        return row is not None and row.school_id == school_id
    if source == "attendance_reconciliation":
        row = db.query(AttendanceReconciliation.student_id).filter(AttendanceReconciliation.id == entity_id).one_or_none()
        return row is not None and row.student_id in _user_ids_in_school(db, school_id)
    if source == "fee_overdue":
        row = db.query(FeeRecord.student_id).filter(FeeRecord.id == entity_id).one_or_none()
        return row is not None and row.student_id in _user_ids_in_school(db, school_id)
    if source == "anomaly_flag":
        flag = db.query(AnomalyFlag).filter(AnomalyFlag.id == entity_id).one_or_none()
        return flag is not None and _anomaly_flag_in_school(db, flag, school_id)
    return False


def summarize_alerts(alerts: list[Alert]) -> dict:
    """Counts-by-severity and counts-by-source, for GET /admin/alerts/summary."""
    by_severity = {level: 0 for level in SEVERITY_LEVELS}
    by_source: dict[str, int] = {}
    for a in alerts:
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
        by_source[a.source] = by_source.get(a.source, 0) + 1
    return {"total": len(alerts), "by_severity": by_severity, "by_source": by_source}
