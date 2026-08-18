"""Student Analytics Router - Person B (Classroom & Academics).

Implements multi-dimensional academic analytics, grade trends, and Person A risk banner integration.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.analytics_service import get_student_personal_analytics
from app.services.scoping import assert_can_view_student_record
from app.services.auth import CurrentUser, get_current_user

router = APIRouter(tags=["analytics"])


@router.get("/analytics/student/{student_id}")
def get_student_analytics(
    student_id: int,
    term: str = Query(default="Term 1"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve comprehensive personal academic analytics for a student."""
    assert_can_view_student_record(db, user, student_id, what="analytics")

    try:
        return get_student_personal_analytics(db, student_id, term)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
