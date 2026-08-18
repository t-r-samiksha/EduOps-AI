from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.class_ import SchoolClass
    from app.models.resource import Resource
    from app.models.school import School
    from app.models.subject import Subject
    from app.models.user import User

POST_TYPES = ("note", "announcement", "material")


class Classroom(Base):
    """A classroom space connecting a class section, subject, and teacher.
    Serves as the container for classroom stream posts, notes, announcements,
    materials, assignments, and quizzes.
    """

    __tablename__ = "classrooms"
    __table_args__ = (
        Index("ix_classrooms_school_id", "school_id"),
        Index("ix_classrooms_class_id", "class_id"),
        Index("ix_classrooms_teacher_id", "teacher_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    class_name: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship()
    school_class: Mapped["SchoolClass"] = relationship()
    subject: Mapped["Subject"] = relationship()
    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])
    posts: Mapped[list["StreamPost"]] = relationship(
        back_populates="classroom", cascade="all, delete-orphan", order_by="StreamPost.created_at.desc()"
    )


class StreamPost(Base):
    """A post published by a teacher to a classroom stream: note, announcement, or material."""

    __tablename__ = "stream_posts"
    __table_args__ = (
        Index("ix_stream_posts_classroom_created", "classroom_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    post_type: Mapped[str] = mapped_column(String(20), nullable=False)  # note, announcement, material
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    classroom: Mapped["Classroom"] = relationship(back_populates="posts")
    author: Mapped["User"] = relationship(foreign_keys=[author_id])
    attachments: Mapped[list["PostAttachment"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class PostAttachment(Base):
    """File attachment uploaded with a stream post."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("stream_posts.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)  # in bytes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("resources.id", ondelete="SET NULL"), nullable=True
    )
    """The `resources` row this attachment was indexed as, so the Doubt Bot can answer
    from it - NULL for an attachment that is not indexable (images) or that predates this
    column.

    WHY THIS EXISTS. Uploading a file to a classroom post used to write bytes to storage
    and stop there: no `Resource` row, no `ingest_resource` call, so nothing a teacher
    posted to their stream was ever retrievable by the Doubt Bot. The Resources library
    was the only path into the RAG corpus, which meant teachers had to upload the same PDF
    twice - once to share it with the class, once so the bot could read it - and nothing
    in either UI said so. Now the stream post is itself an indexed resource and this
    column is the link.

    `ondelete="SET NULL"`, not CASCADE: deleting the resource from the library should not
    silently delete the teacher's stream post along with it. The attachment keeps its own
    `file_url`, so the download route still works; it just stops being indexed.
    """

    post: Mapped["StreamPost"] = relationship(back_populates="attachments")
    resource: Mapped["Resource | None"] = relationship()
