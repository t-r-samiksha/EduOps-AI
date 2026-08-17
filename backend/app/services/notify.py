"""Notification dispatch - the single write path for the `notifications` table.

One small function called from every router where something happens that a user
should be told about, mirroring services/audit_log.py. Nothing else in the app
should construct a Notification directly; funnelling every write through here is
what makes the source_type vocabulary and the de-duplication below enforceable in
one place.

DOES NOT COMMIT - a deliberate choice, not an oversight
------------------------------------------------------------
dispatch_notification() only calls db.add(); it never calls db.commit(). Every
call site already has its own db.commit() for the state change it is announcing -
dispatching before that commit puts the notification and the state change in the
SAME transaction, atomically. If the commit fails, neither happens: no user is
ever told about an approval that rolled back, and no state change silently lands
without its notification. A dispatcher that committed on its own would break that
guarantee for no benefit. Same reasoning, same wording, as audit_log.py - and
where a router already calls write_audit_log(), the dispatch call belongs right
next to it.

WHERE THIS IS WIRED IN
------------------------
Person A's routers already computed the audience for these events and did nothing
with it (routers/risk.py's `parent_ids` enrichment existed for precisely this,
unused - see its comment). Wired in at:
  - routers/risk.py: flag creation -> parents + homeroom teacher (early_warning)
  - routers/fees.py: POST /admin/fees/reminders -> parents (fee_reminder)
  - routers/staffing.py: PUT /staff/approve_leave -> requesting teacher
    (leave_decision); PUT /substitution/{id}/confirm -> substitute
    (substitute_assigned)
  - routers/approvals.py: POST /admin/approvals/{id}/decision -> requester
    (leave_decision)
  - routers/admissions.py: decision path -> the guardian's user account if one
    exists (admission_decision)

Read state (read_at/acknowledged_at) is owned by routers/notifications.py, not
this module - this is the write-on-event path only.
"""

from __future__ import annotations

from typing import Iterable

from app.models.notification import Notification


def dispatch_notification(
    db,
    *,
    user_id: int,
    source_type: str,
    title: str,
    body: str | None = None,
    priority: str = "normal",
    source_id: int | None = None,
) -> Notification:
    """Queue one notification for one user, inside the caller's transaction.

    `source_type` should be one of models/notification.py's SOURCE_TYPES and
    `priority` one of its PRIORITIES; neither is validated here for the same
    reason neither is a DB enum - new features keep adding kinds, and a
    dispatcher that raised on an unknown string would turn a cosmetic mistake
    into a failed state change at the call site.

    Returns the pending Notification (no id until the caller flushes/commits).
    """
    notification = Notification(
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
        title=title,
        body=body,
        priority=priority,
    )
    db.add(notification)
    return notification


def dispatch_bulk(db, *, user_ids: Iterable[int], **kwargs) -> list[Notification]:
    """Same as dispatch_notification, fanned out over several recipients.

    De-duplicates `user_ids` while preserving first-seen order: `parent_student`
    has no unique constraint on (parent_id, student_id), so a double-linked
    parent would otherwise get the same notification twice. Call sites currently
    de-dupe in application code before calling out; doing it here means they no
    longer have to, and the one that forgets doesn't ship a bug.

    Returns one pending Notification per distinct user, in that same order.
    """
    seen: set[int] = set()
    notifications: list[Notification] = []
    for user_id in user_ids:
        if user_id in seen:
            continue
        seen.add(user_id)
        notifications.append(dispatch_notification(db, user_id=user_id, **kwargs))
    return notifications
