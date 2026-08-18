"""Teacher Remarks and Bulk Remark Entry Service - Person B (Classroom & Academics).

Handles qualitative student evaluation, sentiment classification (academic, behavioral, appreciation),
and bulk batch remarks entry for teachers.
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from app.models.class_ import SchoolClass
from app.models.parent_student import ParentStudent
from app.models.remark import Remark
from app.models.subject import Subject
from app.models.user import User
from app.services.notify import dispatch_bulk, dispatch_notification


def create_single_remark(
    db: Session,
    school_id: int,
    author_id: int,
    student_id: int,
    class_id: int,
    content: str,
    sentiment_tag: str = "academic",
    subject_id: int | None = None,
) -> Remark:
    """Creates a single remark and dispatches notification."""
    remark = Remark(
        school_id=school_id,
        author_id=author_id,
        student_id=student_id,
        class_id=class_id,
        subject_id=subject_id,
        content=content.strip(),
        sentiment_tag=sentiment_tag.lower(),
    )
    db.add(remark)
    db.flush()

    # Notify student
    dispatch_notification(
        db,
        user_id=student_id,
        source_type="remark_posted",
        title=f"New Teacher Remark ({sentiment_tag.capitalize()})",
        body=f'"{content[:120]}..."' if len(content) > 120 else f'"{content}"',
        priority="normal",
        source_id=remark.id,
    )

    # Also notify parent if linked
    parent_ids = [
        row.parent_id
        for row in db.query(ParentStudent.parent_id).filter(ParentStudent.student_id == student_id).all()
    ]
    if parent_ids:
        dispatch_bulk(
            db,
            user_ids=parent_ids,
            source_type="remark_posted",
            title=f"Teacher Remark for Student ({sentiment_tag.capitalize()})",
            body=f'"{content[:120]}..."' if len(content) > 120 else f'"{content}"',
            priority="normal",
            source_id=remark.id,
        )

    db.commit()
    db.refresh(remark)
    return remark


def create_bulk_remarks(
    db: Session,
    school_id: int,
    author_id: int,
    class_id: int,
    remarks_data: list[dict[str, Any]],
    subject_id: int | None = None,
) -> list[Remark]:
    """Creates multiple student remarks in a single batch transaction."""
    created_remarks = []
    for item in remarks_data:
        student_id = item.get("student_id")
        content = item.get("content", "").strip()
        sentiment = item.get("sentiment_tag", "academic")
        if not student_id or not content:
            continue

        remark = Remark(
            school_id=school_id,
            author_id=author_id,
            student_id=student_id,
            class_id=class_id,
            subject_id=subject_id,
            content=content,
            sentiment_tag=sentiment.lower(),
        )
        db.add(remark)
        created_remarks.append(remark)

    db.commit()
    for r in created_remarks:
        db.refresh(r)

    return created_remarks
