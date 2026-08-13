import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.alerts import AlertDismissal
from app.models.attendance import AttendanceReconciliation
from app.models.document import Document
from app.models.fees import FeeRecord
from app.models.risk import RiskFlag
from app.models.staffing import LeaveRequest, Substitution
from app.models.syllabus import AnomalyFlag
from app.services.alert_aggregator import SEVERITY_LEVELS, aggregate_alerts, summarize_alerts
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, require_role

router = APIRouter(tags=["admin-command-center"])

SSE_POLL_INTERVAL_SECONDS = 5
"""Reasonable for demo scale: frequent enough a dashboard feels "live", infrequent
enough not to re-run a cross-table aggregation query every request across however
many admins have a tab open. See this module's docstring below for why polling
rather than genuine push."""

# Sources with a real terminal status="resolved" transition on their own row - resolve
# routes directly there. Both RiskFlag and AnomalyFlag use identical status/
# resolved_by/resolved_at mechanics (see AnomalyFlag's docstring), so one helper
# handles both instead of duplicating the transition per source.
_REAL_STATUS_SOURCES: dict[str, type] = {
    "risk_flag": RiskFlag,
    "anomaly_flag": AnomalyFlag,
}

# Sources whose "resolve" is a cross-cutting dismissal (AlertDismissal) rather than a
# native status transition - see alert_aggregator.py's "RESOLVE ROUTING" docstring
# and models/alerts.py's AlertDismissal for the full reasoning. Maps source -> the
# model used to verify entity_id actually exists before recording a dismissal.
# fee_overdue joins this list, not _REAL_STATUS_SOURCES: a fee's real resolution is
# getting PAID (POST /admin/fees/records/{id}/payment), not a generic "resolve" -
# dismissing the alert must not fake a payment that never happened.
_DISMISSAL_SOURCES: dict[str, type] = {
    "leave_request": LeaveRequest,
    "substitution": Substitution,
    "document_failed": Document,
    "document_low_confidence": Document,
    "attendance_reconciliation": AttendanceReconciliation,
    "fee_overdue": FeeRecord,
}


class AlertOut(BaseModel):
    id: str
    source: str
    severity: str
    title: str
    message: str
    entity_type: str
    entity_id: int
    created_at: datetime
    resolved: bool

    model_config = ConfigDict(from_attributes=True)


class AlertsFeedResponse(BaseModel):
    items: list[AlertOut]


class AlertsSummaryResponse(BaseModel):
    total: int
    by_severity: dict[str, int]
    by_source: dict[str, int]


class ResolveResponse(BaseModel):
    id: str
    resolved: bool


def _dismissed_alert_ids(db: Session) -> set[str]:
    return {row.alert_id for row in db.query(AlertDismissal.alert_id).all()}


@router.get("/admin/alerts", response_model=AlertsFeedResponse)
def get_alerts(
    since: datetime | None = None,
    severity: str | None = None,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if severity is not None and severity not in SEVERITY_LEVELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"severity must be one of {SEVERITY_LEVELS}")

    alerts = aggregate_alerts(db, dismissed_ids=_dismissed_alert_ids(db), since=since, severity=severity)
    return AlertsFeedResponse(items=[AlertOut.model_validate(a) for a in alerts])


@router.get("/admin/alerts/summary", response_model=AlertsSummaryResponse)
def get_alerts_summary(
    since: datetime | None = None,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """Lightweight counts-by-severity/source, meant for a dashboard header widget.
    NOT in the original api-contract.md stub - a small, natural addition alongside
    the feed endpoint, called out explicitly here rather than silently added."""
    alerts = aggregate_alerts(db, dismissed_ids=_dismissed_alert_ids(db), since=since)
    return AlertsSummaryResponse(**summarize_alerts(alerts))


@router.post("/admin/alerts/{alert_id}/resolve", response_model=ResolveResponse)
def resolve_alert(
    alert_id: str,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """alert_id is the composite "{source}:{entity_id}" string from GET /admin/alerts
    - e.g. "risk_flag:43". Routes back to the correct source based on `source`:
    risk_flag and anomaly_flag resolve their real status field directly; every other
    source records an AlertDismissal instead. See alert_aggregator.py's module
    docstring for why those aren't the same mechanism."""
    source, sep, raw_entity_id = alert_id.partition(":")
    if not sep or not raw_entity_id.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Malformed alert id - expected "source:entity_id"')
    entity_id = int(raw_entity_id)

    real_status_model = _REAL_STATUS_SOURCES.get(source)
    if real_status_model is not None:
        row = db.query(real_status_model).filter(real_status_model.id == entity_id).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Alert's underlying {source} not found")
        if row.status == "resolved":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Alert is already resolved")
        row.status = "resolved"
        row.resolved_by = user.id
        row.resolved_at = datetime.now(timezone.utc)
        write_audit_log(db, actor_id=user.id, action="resolve", entity_type=real_status_model.__tablename__, entity_id=entity_id)
        db.commit()
        return ResolveResponse(id=alert_id, resolved=True)

    dismissal_model = _DISMISSAL_SOURCES.get(source)
    if dismissal_model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown alert source: {source!r}")

    if db.query(dismissal_model).filter(dismissal_model.id == entity_id).first() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert's underlying entity not found")
    if db.query(AlertDismissal).filter(AlertDismissal.alert_id == alert_id).first() is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Alert is already resolved")

    db.add(AlertDismissal(alert_id=alert_id, dismissed_by=user.id))
    write_audit_log(
        db, actor_id=user.id, action="dismiss_alert", entity_type=dismissal_model.__tablename__, entity_id=entity_id,
        detail={"note": "alert hidden from feed - underlying entity status unchanged"},
    )
    db.commit()
    return ResolveResponse(id=alert_id, resolved=True)


# --- Live feed: SSE, not Socket.io ---------------------------------------------------
# Per the playbook: "Websocket/server-sent events endpoint for live alert feed."
# Checked first: Socket.io is named in the tech stack doc but nothing in this repo
# actually wires it up yet (Person C hasn't started chat, the only other feature that
# would plausibly need it). Standing up Socket.io infrastructure for this one feature
# is over-investment - a plain FastAPI/Starlette StreamingResponse with
# `text/event-stream` needs no new dependency and no server process changes. Person C
# can introduce Socket.io later for chat and this endpoint can move onto the same
# infra then if it makes sense to unify; nothing here blocks that.
#
# Polls the aggregator every SSE_POLL_INTERVAL_SECONDS rather than pushing on write -
# genuine push (DB LISTEN/NOTIFY, a message bus) is real infrastructure investment
# this session deliberately doesn't take on, consistent with every other
# "no task queue exists yet" finding across this project.
#
# Reuses the single request-scoped `db` session for the life of the connection rather
# than opening a fresh one per poll - simpler, and fine at demo scale/connection
# counts; a production version would likely bound this differently (a short-lived
# session per poll, or a connection pool sized for concurrent open streams).


def _format_sse_event(db: Session) -> str:
    alerts = aggregate_alerts(db, dismissed_ids=_dismissed_alert_ids(db))
    payload = [AlertOut.model_validate(a).model_dump(mode="json") for a in alerts]
    return f"data: {json.dumps(payload)}\n\n"


async def _alert_event_stream(db: Session, *, max_events: int | None = None, poll_interval: float = SSE_POLL_INTERVAL_SECONDS):
    """`max_events`/`poll_interval` exist purely for testability: an HTTP integration
    test can't cleanly cancel a genuinely-infinite generator through TestClient's
    streaming interface (there's no real network disconnect to trigger cleanup), so
    tests call this generator directly with a small max_events and poll_interval=0
    instead of going through the endpoint. Production always uses the defaults
    (max_events=None, the real poll interval) - unbounded, same as before these
    parameters existed."""
    emitted = 0
    while max_events is None or emitted < max_events:
        yield _format_sse_event(db)
        emitted += 1
        if max_events is not None and emitted >= max_events:
            return
        await asyncio.sleep(poll_interval)


@router.get("/admin/alerts/stream")
async def stream_alerts(
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    return StreamingResponse(_alert_event_stream(db), media_type="text/event-stream")
