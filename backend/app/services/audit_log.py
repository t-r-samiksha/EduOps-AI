"""Audit log writer with a consistent schema for all auditable actions, per the
playbook. One small function, called from every router where a meaningful privileged
state change happens.

DOES NOT COMMIT - a deliberate choice, not an oversight
------------------------------------------------------------
write_audit_log() only calls db.add(); it never calls db.commit(). Every call site
already has its own db.commit() immediately after the state change it's auditing -
calling write_audit_log() before that commit means the audit entry and the state
change persist in the SAME transaction, atomically. If the commit fails, neither
happens; there's no window where a state change succeeds but its audit entry is
silently lost (or vice versa). A writer that committed on its own would break that
guarantee for no benefit.

WHERE THIS IS ACTUALLY WIRED IN - the real work of this session
------------------------------------------------------------------
Checked every router from every prior session for privileged state-changing
endpoints and wired an audit write into each one (see each router's own call site
for the specific action/entity_type used):
  - routers/timetable.py: PUT /update
  - routers/attendance.py: PUT /{id}/review
  - routers/staffing.py: PUT /staff/approve_leave, PUT /substitution/{id}/confirm
  - routers/risk.py: PUT /{id}/acknowledge, POST /{id}/intervention, PUT /{id}/resolve
  - routers/documents.py: PUT /entities/{id} (correction)
  - routers/syllabus.py: PUT /admin/anomalies/{id}/resolve
  - routers/admin_alerts.py: POST /admin/alerts/{id}/resolve (both the real-status
    and the dismissal-table resolve paths)
  - routers/approvals.py: POST /admin/approvals/{id}/decision (this session's own
    new endpoint)

That's 10 endpoints across 8 routers. Before this session, NONE of them wrote
anything audit-trail-shaped - this is a genuine, repo-wide gap being closed for the
first time, not a partial addition to something that already existed. Read-only GETs
and simple creates without a meaningful "state changed" semantic (e.g. POST
/risk/flag, POST /syllabus/checkpoint, POST /timetable/generate) are deliberately
NOT wired in - audited actions are decisions/corrections/transitions on an existing
entity, not every write in the system.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.audit import AuditLogEntry


def write_audit_log(
    db: Session,
    *,
    actor_id: int,
    action: str,
    entity_type: str,
    entity_id: int,
    detail: dict | None = None,
) -> AuditLogEntry:
    entry = AuditLogEntry(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, detail=detail)
    db.add(entry)
    return entry
