"""Announcements and their acknowledgments.

AN ANNOUNCEMENT IS A SOURCE, NOT A DELIVERY SYSTEM. Posting one resolves its audience
and dispatches through services/notify.py with source_type="announcement", so recipients
receive it in the notification bell they already have. This table stores the richer
content that a bell row cannot carry - category, scope, author, priority, and who has
acknowledged it - and the feed page is a view over that. Nothing here delivers anything;
if you find yourself writing a second inbox, stop.

SCOPE IS THREE COLUMNS AND THEY MUST AGREE. `scope_type` says which of
`scope_grade_level` / `scope_class_id` is meaningful, and the CHECK constraint below
makes a half-populated row unrepresentable rather than merely discouraged. That matters
because audience resolution branches on scope_type and reads the matching column: a
`class`-scoped row with a null class_id would resolve to an empty audience and the
announcement would silently reach nobody, which is the worst failure mode this feature
has - it looks posted.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

SCOPE_TYPES = ("school", "grade", "class")
CATEGORIES = ("event", "academic", "fee", "general")
PRIORITIES = ("normal", "important", "urgent")
"""Matches models/notification.py's PRIORITIES so an announcement's priority can be
passed straight through to dispatch rather than translated."""


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (
        # The scope columns must match scope_type. Enforced in the DB as well as the
        # service because an inconsistent row resolves to the wrong audience (or none)
        # with no error anywhere - it just looks like nobody read it.
        CheckConstraint(
            "(scope_type = 'school' AND scope_grade_level IS NULL AND scope_class_id IS NULL)"
            " OR (scope_type = 'grade' AND scope_grade_level IS NOT NULL AND scope_class_id IS NULL)"
            " OR (scope_type = 'class' AND scope_class_id IS NOT NULL AND scope_grade_level IS NULL)",
            name="ck_announcement_scope_columns_match_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, index=True)
    """Always taken from the author's token, never from the request body. Every feed
    query filters on it first - this repo has a documented recurring bug class of
    cross-tenant leaks in admin endpoints."""
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    scope_type: Mapped[str] = mapped_column(String(10), nullable=False)
    """One of SCOPE_TYPES."""
    scope_grade_level: Mapped[int | None] = mapped_column(Integer)
    """Set iff scope_type == 'grade'. Matches SchoolClass.grade_level, including its
    negative pre-Grade-1 convention (see that column's docstring)."""
    scope_class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    """Set iff scope_type == 'class'."""

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    """One of CATEGORIES. Free text with a documented vocabulary, same approach as
    FeeSchedule.fee_type and Notification.source_type."""
    priority: Mapped[str] = mapped_column(String(10), nullable=False, server_default="normal")
    """One of PRIORITIES. Passed straight through to dispatch, and drives feed
    ordering - urgent pins to the top."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    school: Mapped["School"] = relationship()
    author: Mapped["User"] = relationship(foreign_keys=[author_id])
    scope_class: Mapped["SchoolClass | None"] = relationship()


class AnnouncementAcknowledgment(Base):
    """One recipient's "I've read this".

    Only ever written for a user actually in the announcement's audience - an ack from
    outside it would inflate the numerator of a ratio whose denominator is the audience,
    making "27 of 40 have read this" arithmetic that doesn't hold.
    """

    __tablename__ = "announcement_acknowledgments"
    __table_args__ = (
        # Acknowledging twice must not create a second row - the ack count is a COUNT
        # over this table, so a duplicate would overstate readership.
        UniqueConstraint("announcement_id", "user_id", name="uq_announcement_ack_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("announcements.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    announcement: Mapped["Announcement"] = relationship()
    user: Mapped["User"] = relationship()
