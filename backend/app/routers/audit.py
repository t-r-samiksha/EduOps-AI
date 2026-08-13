from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit import AuditLogEntry
from app.services.auth import CurrentUser, require_role

router = APIRouter(tags=["audit-log"])


class AuditLogEntryOut(BaseModel):
    id: int
    actor_id: int
    action: str
    entity_type: str
    entity_id: int
    detail: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogResponse(BaseModel):
    items: list[AuditLogEntryOut]


@router.get("/audit/by_user/{user_id}", response_model=AuditLogResponse)
def audit_by_user(
    user_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(AuditLogEntry)
        .filter(AuditLogEntry.actor_id == user_id)
        .order_by(AuditLogEntry.created_at.desc())
        .all()
    )
    return AuditLogResponse(items=[AuditLogEntryOut.model_validate(e) for e in entries])


@router.get("/audit/by_object/{object_type}/{object_id}", response_model=AuditLogResponse)
def audit_by_object(
    object_type: str,
    object_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == object_type, AuditLogEntry.entity_id == object_id)
        .order_by(AuditLogEntry.created_at.desc())
        .all()
    )
    return AuditLogResponse(items=[AuditLogEntryOut.model_validate(e) for e in entries])
