"""The notification center - a user's own inbox.

Every route here is scoped to `user.id` from the token and takes no `user_id`
parameter of any kind. That's the whole authorization model: there is no "read
someone else's inbox" operation to get wrong, so none of these routes needs a
role gate beyond being authenticated. Where a row might not be the caller's
(the by-id routes), the answer is 404 rather than 403 - a 403 would confirm the
row exists, which is itself a leak on a table whose ids are sequential.

Writes come from services/notify.py only; there is no create endpoint here.
"""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.notification import Notification
from app.services.auth import CurrentUser, get_current_user

router = APIRouter(tags=["notifications"])

SSE_POLL_INTERVAL_SECONDS = 5
"""Matches admin_alerts.py's stream - see its note on polling rather than genuine
push. The unread count this re-runs is index-backed, so it's a cheaper poll than
the alerts aggregation."""

STREAM_LATEST_LIMIT = 10
"""How many recent notifications ride along with each unread_count push. The bell
dropdown shows a short list and links to the full inbox for the rest; sending the
whole table on a 5-second interval would be pointless."""

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class NotificationOut(BaseModel):
    id: int
    source_type: str
    source_id: int | None
    title: str
    body: str | None
    priority: str
    read_at: datetime | None
    """Null means unread."""
    acknowledged_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    page: int
    page_size: int


class UnreadCountResponse(BaseModel):
    count: int


class ReadAllResponse(BaseModel):
    updated: int


def _out(notification: Notification) -> NotificationOut:
    return NotificationOut(
        id=notification.id,
        source_type=notification.source_type,
        source_id=notification.source_id,
        title=notification.title,
        body=notification.body,
        priority=notification.priority,
        read_at=notification.read_at,
        acknowledged_at=notification.acknowledged_at,
        created_at=notification.created_at,
    )


def _own_notification(db: Session, notification_id: int, user_id: int) -> Notification:
    """404, never 403 - see this module's docstring."""
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .one_or_none()
    )
    if notification is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    return notification


def _unread_count(db: Session, user_id: int) -> int:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .count()
    )


# --- GET /notifications ---------------------------------------------------------------
# The repo's first genuinely paginated route. docs/api-contract.md's Conventions
# section has always specified ?page=&page_size= returning {items,total,page,page_size},
# but no existing router implements it - they all return an unpaginated {"items":[...]}.
# Matching the contract doc rather than the surrounding code is deliberate here: an
# inbox is the one list in this app that grows without bound per user.


@router.get("/notifications", response_model=NotificationPage)
def list_notifications(
    read: bool | None = None,
    page: int = Query(1),
    page_size: int = Query(DEFAULT_PAGE_SIZE),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's own inbox, newest first. `read` omitted returns both."""
    if page < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "page must be >= 1")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"page_size must be between 1 and {MAX_PAGE_SIZE}")

    query = db.query(Notification).filter(Notification.user_id == user.id)
    if read is True:
        query = query.filter(Notification.read_at.isnot(None))
    elif read is False:
        query = query.filter(Notification.read_at.is_(None))

    total = query.count()
    rows = (
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return NotificationPage(items=[_out(n) for n in rows], total=total, page=page, page_size=page_size)


# --- Static paths before /{id} ones ----------------------------------------------------
# /notifications/unread-count and /notifications/read-all are single-segment and so
# can't collide with the two-segment /notifications/{id}/... routes, but they're
# declared first anyway so the ordering stays safe if a /notifications/{id} route is
# ever added.


@router.get("/notifications/unread-count", response_model=UnreadCountResponse)
def unread_count(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Badge count. Hit on every poll - served by the (user_id, read_at) index."""
    return UnreadCountResponse(count=_unread_count(db, user.id))


@router.put("/notifications/read-all", response_model=ReadAllResponse)
def mark_all_read(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .update({Notification.read_at: now}, synchronize_session=False)
    )
    db.commit()
    return ReadAllResponse(updated=updated)


@router.put("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = _own_notification(db, notification_id, user.id)
    # Idempotent: don't bump an existing read_at, so "when did they first see it"
    # survives a re-click.
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return _out(notification)


@router.put("/notifications/{notification_id}/acknowledge", response_model=NotificationOut)
def acknowledge(
    notification_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Acknowledging does not imply reading - the two timestamps are independent,
    matching how RiskFlag keeps acknowledge and resolve separate."""
    notification = _own_notification(db, notification_id, user.id)
    if notification.acknowledged_at is None:
        notification.acknowledged_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return _out(notification)


# --- GET /notifications/stream ---------------------------------------------------------
# SSE, following GET /admin/alerts/stream exactly (see admin_alerts.py's "SSE, not
# Socket.io" note - that reasoning is unchanged: no Socket.io exists in this repo and
# this needs no new dependency). Same _format_sse_event helper shape, same
# reuse-the-request-session-for-the-life-of-the-connection tradeoff, same
# max_events/poll_interval testability parameters.


def _format_sse_event(db: Session, user_id: int) -> str:
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(STREAM_LATEST_LIMIT)
        .all()
    )
    payload = {
        "unread_count": _unread_count(db, user_id),
        "latest": [_out(n).model_dump(mode="json") for n in rows],
    }
    return f"data: {json.dumps(payload)}\n\n"


async def _notification_event_stream(
    db: Session,
    *,
    user_id: int,
    max_events: int | None = None,
    poll_interval: float = SSE_POLL_INTERVAL_SECONDS,
):
    """`max_events`/`poll_interval` exist purely for testability, same as the alerts
    stream's - a TestClient can't cleanly cancel an infinite generator, so tests call
    this directly with a small max_events and poll_interval=0. Production always uses
    the defaults."""
    emitted = 0
    while max_events is None or emitted < max_events:
        yield _format_sse_event(db, user_id)
        emitted += 1
        if max_events is not None and emitted >= max_events:
            return
        await asyncio.sleep(poll_interval)


@router.get("/notifications/stream")
async def stream_notifications(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return StreamingResponse(_notification_event_stream(db, user_id=user.id), media_type="text/event-stream")
