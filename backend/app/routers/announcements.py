"""Announcements: post, read your own feed, acknowledge, and see who hasn't.

POSTING IS THE PRIVILEGED SIDE, READING IS THE SCOPED SIDE. `_assert_can_post` enforces
the permission matrix; the feed derives what you can see from who you are. There is no
`user_id` parameter on any read endpoint - the audience a caller belongs to comes from
their own token, so no client can widen it.

Delivery is not implemented here. Posting resolves the audience and hands it to
services/notify.py, so an announcement arrives in the bell the recipient already has.
See services/announcements.py.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.announcement import (
    CATEGORIES,
    PRIORITIES,
    SCOPE_TYPES,
    Announcement,
    AnnouncementAcknowledgment,
)
from app.models.class_ import SchoolClass
from app.models.role import Role
from app.models.user import User
from app.services.announcements import (
    can_see,
    publish_announcement,
    related_children,
    resolve_audience,
    scope_label,
    visible_scope_for,
)
from app.services.auth import CurrentUser, get_current_user, require_role

router = APIRouter(tags=["announcements"])

PRIORITY_RANK = {"urgent": 0, "important": 1, "normal": 2}
"""Feed ordering is part of the contract, not a UI detail - urgent pins to the top."""


# --- schemas ------------------------------------------------------------------------


class AnnouncementCreate(BaseModel):
    scope_type: str
    scope_grade_level: int | None = None
    scope_class_id: int | None = None
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    category: str = "general"
    priority: str = "normal"
    """NOTE: no school_id. It comes from the caller's token - this repo has a documented
    recurring bug class of endpoints trusting a client-supplied school_id."""


class RelatedChild(BaseModel):
    id: int
    name: str | None


class AnnouncementOut(BaseModel):
    id: int
    title: str
    body: str
    category: str
    priority: str
    scope_type: str
    scope_grade_level: int | None
    scope_class_id: int | None
    scope_label: str
    author_id: int
    author_name: str | None
    created_at: datetime
    acknowledged: bool
    acknowledged_at: datetime | None
    related_children: list[RelatedChild]


class FeedResponse(BaseModel):
    items: list[AnnouncementOut]
    unacknowledged_count: int


class CreateResponse(BaseModel):
    announcement: AnnouncementOut
    recipients: int
    """How many notifications were actually dispatched, so the author sees the reach
    immediately rather than trusting that "posted" meant "delivered"."""



class PostableScopes(BaseModel):
    can_post: bool
    can_post_school: bool
    grades: list[int]
    classes: list[dict]
    """[{id, name, grade_level}] - only the classes this caller may actually target."""


class AckPerson(BaseModel):
    user_id: int
    name: str | None
    role: str | None
    acknowledged_at: datetime | None = None


class AckStatusResponse(BaseModel):
    announcement_id: int
    audience_size: int
    acknowledged_count: int
    acknowledged_pct: float
    acknowledged: list[AckPerson]
    outstanding: list[AckPerson]


# --- helpers ------------------------------------------------------------------------


def _teacher_scope(db: Session, teacher_id: int) -> tuple[set[int], set[int]]:
    """(class_ids, grade_levels) a teacher may post to: homeroom UNION timetable-taught.

    Reuses the same union as services/scoping.py rather than inventing a fourth
    definition of "your classes". A teacher's postable GRADES are the grade levels of
    the classes they actually teach - so a teacher of Grade 1-A Math may post to Grade 1
    as well as Grade 3. The rule is "grades you teach", not "your homeroom's grade".
    """
    from app.services.scoping import classes_taught_by

    class_ids = set(classes_taught_by(db, teacher_id))
    grades = {
        row.grade_level
        for row in db.query(SchoolClass.grade_level).filter(SchoolClass.id.in_(class_ids or [-1]))
        if row.grade_level is not None
    }
    return class_ids, grades


def _assert_can_post(db: Session, user: CurrentUser, body: AnnouncementCreate) -> None:
    """The permission matrix, enforced server-side.

        principal/admin : school, grade, class - anywhere in their own school
        teacher         : grade and class, but ONLY ones they teach
        student/parent  : never (already blocked by require_role on the route)

    The UI hides options a caller may not use, but that is a courtesy - this is the
    check that counts.
    """
    if body.scope_type not in SCOPE_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"scope_type must be one of {SCOPE_TYPES}")
    if body.category not in CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"category must be one of {CATEGORIES}")
    if body.priority not in PRIORITIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"priority must be one of {PRIORITIES}")

    # Scope columns must agree with scope_type. The DB has a CHECK constraint too; this
    # turns what would be a 500 IntegrityError into a 400 the client can act on.
    if body.scope_type == "school" and (body.scope_grade_level is not None or body.scope_class_id is not None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "school scope takes no grade or class")
    if body.scope_type == "grade" and (body.scope_grade_level is None or body.scope_class_id is not None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "grade scope requires scope_grade_level and no class")
    if body.scope_type == "class" and (body.scope_class_id is None or body.scope_grade_level is not None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "class scope requires scope_class_id and no grade")

    # A named class must exist IN THE CALLER'S SCHOOL. 404 rather than 403 so an admin
    # cannot probe another school's class ids by status code - same reasoning as
    # fees.py and remarks.py.
    if body.scope_type == "class":
        cls = (
            db.query(SchoolClass)
            .filter(SchoolClass.id == body.scope_class_id, SchoolClass.school_id == user.school_id)
            .one_or_none()
        )
        if cls is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found in your school")

    if user.role in ("admin", "principal"):
        return

    # teacher
    if body.scope_type == "school":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Teachers cannot post school-wide announcements"
        )
    class_ids, grades = _teacher_scope(db, user.id)
    if body.scope_type == "class" and body.scope_class_id not in class_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can only post to classes you teach"
        )
    if body.scope_type == "grade" and body.scope_grade_level not in grades:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can only post to grades you teach"
        )


def _to_out(
    db: Session,
    ann: Announcement,
    *,
    author_names: dict[int, str | None],
    acked: dict[int, datetime],
    scope: dict,
) -> AnnouncementOut:
    return AnnouncementOut(
        id=ann.id,
        title=ann.title,
        body=ann.body,
        category=ann.category,
        priority=ann.priority,
        scope_type=ann.scope_type,
        scope_grade_level=ann.scope_grade_level,
        scope_class_id=ann.scope_class_id,
        scope_label=scope_label(db, ann),
        author_id=ann.author_id,
        author_name=author_names.get(ann.author_id),
        created_at=ann.created_at,
        acknowledged=ann.id in acked,
        acknowledged_at=acked.get(ann.id),
        related_children=[RelatedChild(**c) for c in related_children(db, ann, scope)],
    )


def _author_names(db: Session, announcements: list[Announcement]) -> dict[int, str | None]:
    ids = {a.author_id for a in announcements}
    if not ids:
        return {}
    return {u.id: u.full_name for u in db.query(User).filter(User.id.in_(ids))}


def _acks_for(db: Session, user_id: int, announcement_ids: list[int]) -> dict[int, datetime]:
    if not announcement_ids:
        return {}
    return {
        row.announcement_id: row.acknowledged_at
        for row in db.query(AnnouncementAcknowledgment).filter(
            AnnouncementAcknowledgment.user_id == user_id,
            AnnouncementAcknowledgment.announcement_id.in_(announcement_ids),
        )
    }


# --- POST /announcements ------------------------------------------------------------


@router.post("/announcements", response_model=CreateResponse, status_code=status.HTTP_201_CREATED)
def create_announcement(
    body: AnnouncementCreate,
    user: CurrentUser = Depends(require_role("admin", "principal", "teacher")),
    db: Session = Depends(get_db),
):
    """Post an announcement, then deliver it through the existing notification path."""
    _assert_can_post(db, user, body)

    ann, audience = publish_announcement(
        db,
        author_id=user.id,
        school_id=user.school_id,  # from the token, never the body
        scope_type=body.scope_type,
        scope_grade_level=body.scope_grade_level,
        scope_class_id=body.scope_class_id,
        title=body.title,
        body=body.body,
        category=body.category,
        priority=body.priority,
    )
    db.commit()
    db.refresh(ann)

    scope = visible_scope_for(db, user)
    return CreateResponse(
        announcement=_to_out(db, ann, author_names={user.id: None}, acked={}, scope=scope),
        recipients=len(audience),
    )


# --- GET /announcements/feed --------------------------------------------------------


@router.get("/announcements/feed", response_model=FeedResponse)
def get_feed(
    scope_filter: str | None = None,
    limit: int = 50,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's own feed, auto-filtered.

    NO user_id PARAMETER, deliberately: what a caller may see is derived from their own
    identity, so there is nothing for a client to widen. A parent gets one deduplicated
    list across all their children - no child selection required - with each item tagged
    by which of their children it relates to.
    """
    scope = visible_scope_for(db, user)

    rows = (
        db.query(Announcement)
        .filter(Announcement.school_id == user.school_id)
        .order_by(Announcement.created_at.desc())
        .all()
    )
    visible = [a for a in rows if can_see(a, scope)]
    if scope_filter:
        if scope_filter not in SCOPE_TYPES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"scope must be one of {SCOPE_TYPES}")
        visible = [a for a in visible if a.scope_type == scope_filter]

    # Urgent pinned, then important, then newest first.
    visible.sort(key=lambda a: (PRIORITY_RANK.get(a.priority, 9), -a.created_at.timestamp()))
    visible = visible[:limit]

    names = _author_names(db, visible)
    acked = _acks_for(db, user.id, [a.id for a in visible])
    items = [_to_out(db, a, author_names=names, acked=acked, scope=scope) for a in visible]
    return FeedResponse(
        items=items,
        unacknowledged_count=sum(1 for i in items if not i.acknowledged),
    )



# --- GET /announcements/postable-scopes ---------------------------------------------


@router.get("/announcements/postable-scopes", response_model=PostableScopes)
def postable_scopes(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """What this caller may post to - so the composer can OFFER only that.

    Exists because the composer would otherwise have to guess. /reference/lookup returns
    every class in the school, which is right for an admin and wrong for a teacher: it
    would offer classes the server then rejects with a 403, teaching the user that the
    UI lies. A teacher should not see a greyed-out "School-wide" option either; it should
    be absent, and that requires the server to say so.

    This is a convenience for rendering. It is NOT the authorization boundary -
    _assert_can_post is, and it runs regardless of what the composer offered.
    """
    if user.role not in ("admin", "principal", "teacher"):
        return PostableScopes(can_post=False, can_post_school=False, grades=[], classes=[])

    if user.role in ("admin", "principal"):
        rows = (
            db.query(SchoolClass)
            .filter(SchoolClass.school_id == user.school_id, SchoolClass.is_active.is_(True))
            .order_by(SchoolClass.grade_level, SchoolClass.name)
            .all()
        )
        grades = sorted({c.grade_level for c in rows if c.grade_level is not None})
        return PostableScopes(
            can_post=True, can_post_school=True, grades=grades,
            classes=[{"id": c.id, "name": c.name, "grade_level": c.grade_level} for c in rows],
        )

    class_ids, grades = _teacher_scope(db, user.id)
    rows = (
        db.query(SchoolClass)
        .filter(SchoolClass.id.in_(class_ids or [-1]), SchoolClass.is_active.is_(True))
        .order_by(SchoolClass.grade_level, SchoolClass.name)
        .all()
    )
    return PostableScopes(
        can_post=bool(rows),
        can_post_school=False,  # never, for a teacher
        grades=sorted(grades),
        classes=[{"id": c.id, "name": c.name, "grade_level": c.grade_level} for c in rows],
    )


# --- GET /announcements/{id} --------------------------------------------------------


def _get_visible_or_404(db: Session, announcement_id: int, user: CurrentUser) -> tuple[Announcement, dict]:
    ann = (
        db.query(Announcement)
        .filter(Announcement.id == announcement_id, Announcement.school_id == user.school_id)
        .one_or_none()
    )
    if ann is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Announcement not found")
    scope = visible_scope_for(db, user)
    if not can_see(ann, scope):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This announcement was not sent to you")
    return ann, scope


@router.get("/announcements/{announcement_id}", response_model=AnnouncementOut)
def get_announcement(
    announcement_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ann, scope = _get_visible_or_404(db, announcement_id, user)
    return _to_out(
        db, ann,
        author_names=_author_names(db, [ann]),
        acked=_acks_for(db, user.id, [ann.id]),
        scope=scope,
    )


# --- PUT /announcements/{id}/acknowledge --------------------------------------------


@router.put("/announcements/{announcement_id}/acknowledge", response_model=AnnouncementOut)
def acknowledge(
    announcement_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark as read. Only for someone actually in the audience.

    Acknowledging something you were never sent would inflate the numerator of a ratio
    whose denominator is the audience, making "27 of 40 have read this" arithmetic that
    doesn't hold. Idempotent - a second ack keeps the first timestamp.
    """
    ann, scope = _get_visible_or_404(db, announcement_id, user)

    existing = (
        db.query(AnnouncementAcknowledgment)
        .filter(
            AnnouncementAcknowledgment.announcement_id == ann.id,
            AnnouncementAcknowledgment.user_id == user.id,
        )
        .one_or_none()
    )
    if existing is None:
        db.add(AnnouncementAcknowledgment(announcement_id=ann.id, user_id=user.id))
        db.commit()

    return _to_out(
        db, ann,
        author_names=_author_names(db, [ann]),
        acked=_acks_for(db, user.id, [ann.id]),
        scope=scope,
    )


# --- GET /announcements/{id}/ack-status ---------------------------------------------


@router.get("/announcements/{announcement_id}/ack-status", response_model=AckStatusResponse)
def ack_status(
    announcement_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Who has read it and who hasn't - the operations view.

    Author, admin and principal only. "Who else has read this" is not every recipient's
    business, so this is NOT open to the general audience.
    """
    ann = (
        db.query(Announcement)
        .filter(Announcement.id == announcement_id, Announcement.school_id == user.school_id)
        .one_or_none()
    )
    if ann is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Announcement not found")
    if user.role not in ("admin", "principal") and ann.author_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the author, an admin or a principal can see this"
        )

    audience = resolve_audience(db, ann)
    acked_at = {
        row.user_id: row.acknowledged_at
        for row in db.query(AnnouncementAcknowledgment).filter(
            AnnouncementAcknowledgment.announcement_id == ann.id
        )
    }
    people = (
        db.query(User, Role.name)
        .outerjoin(Role, Role.id == User.role_id)
        .filter(User.id.in_(audience or [-1]))
        .all()
    )

    acknowledged, outstanding = [], []
    for u, role_name in people:
        if u.id in acked_at:
            acknowledged.append(
                AckPerson(user_id=u.id, name=u.full_name, role=role_name, acknowledged_at=acked_at[u.id])
            )
        else:
            outstanding.append(AckPerson(user_id=u.id, name=u.full_name, role=role_name))

    size = len(audience)
    return AckStatusResponse(
        announcement_id=ann.id,
        audience_size=size,
        acknowledged_count=len(acknowledged),
        acknowledged_pct=round(100 * len(acknowledged) / size, 1) if size else 0.0,
        acknowledged=acknowledged,
        outstanding=outstanding,
    )
