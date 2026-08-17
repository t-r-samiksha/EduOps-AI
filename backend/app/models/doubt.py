"""Human-to-human doubt threads, and the teacher-verified answers that feed the KB.

DISTINCT FROM THE DOUBT BOT, despite the shared word. The Doubt Bot (routers/bots.py)
answers a question with an LLM over retrieved chunks; Top Doubts (services/
doubt_insights.py) clusters what students asked it. Neither creates anything a person
can reply to. These tables are the human side: a student posts, classmates and the
teacher reply, and the teacher marks one reply as the verified answer.

THE SCOPE ASYMMETRY - deliberate, and the thing most likely to look like a bug
------------------------------------------------------------------------------------
A thread is CLASS-scoped (`class_id`). Its verified answer is ingested at GRADE level.

Those are different on purpose. A doubt belongs to the room it was asked in - "why did
Q3 on yesterday's worksheet confuse us" is a conversation between 3-A and 3-A's
teacher, and 3-B has no business reading it. But once a teacher has certified an
answer, it stops being classroom chatter and becomes curriculum: it is exactly as
reusable as an uploaded handout, and resources are already grade-scoped for the same
reason (sections of a grade share a syllabus - see resources.grade_level). So 3-B's
students DO get 3-A's verified answers through the bot, while never being able to open
the thread itself.

Consequence to be aware of rather than surprised by: verifying a reply widens its
audience from one class to a whole grade. That is the intended trade, and it is why
unverifying must delete the kb_chunks rows rather than just clearing a flag - a
retracted answer that stayed in the corpus would be unretractable content in the bot.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DoubtThread(Base):
    """One question posted to a class, with its replies and (once certified) the one
    reply the teacher marked as the answer."""

    __tablename__ = "doubt_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    """Denormalised from class_id's school so ingestion and tenant filters never have
    to join through classes - kb_chunks.school_id is load-bearing for isolation and
    the value has to come from somewhere trustworthy."""
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False, index=True)
    """The room this was asked in. Every list/read query filters on it, hence the index."""
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    """Scannable in a list. The older `POST /doubts` stub had only a free-text
    `message`, which makes a thread list a column of paragraph openings."""
    body: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    verified_reply_id: Mapped[int | None] = mapped_column(
        # use_alter defers this constraint to its own ALTER TABLE: doubt_threads and
        # thread_replies reference each other, so neither can be created with both
        # constraints inline. The migration adds it after both tables exist.
        ForeignKey("thread_replies.id", use_alter=True, name="fk_doubt_threads_verified_reply_id"),
    )
    """The reply a teacher certified. Nullable and independent of `resolved` in the
    schema, but the endpoints only ever set the two together."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    school: Mapped["School"] = relationship()
    school_class: Mapped["SchoolClass"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
    author: Mapped["User"] = relationship(foreign_keys=[author_id])
    # Both relationships point at ThreadReply, so each needs its own foreign_keys -
    # SQLAlchemy cannot pick between thread_id and verified_reply_id on its own.
    replies: Mapped[list["ThreadReply"]] = relationship(
        back_populates="thread",
        foreign_keys="ThreadReply.thread_id",
        order_by="ThreadReply.created_at",
        cascade="all, delete-orphan",
    )
    verified_reply: Mapped["ThreadReply | None"] = relationship(foreign_keys=[verified_reply_id], post_update=True)
    """post_update is required by the cycle: inserting a thread and its verified reply
    in one flush needs the FK set in a second UPDATE, or SQLAlchemy cannot order the
    two INSERTs."""


class ThreadReply(Base):
    """One reply on a doubt thread. Any member of the thread's class, or its teacher."""

    __tablename__ = "thread_replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("doubt_threads.id"), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    thread: Mapped["DoubtThread"] = relationship(back_populates="replies", foreign_keys=[thread_id])
    author: Mapped["User"] = relationship(foreign_keys=[author_id])
