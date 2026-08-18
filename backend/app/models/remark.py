from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

REMARK_SENTIMENT_TAGS = ("academic", "behavioral", "appreciation")


class Remark(Base):
    """A teacher's qualitative evaluation remark or behavioral observation for a student.

    *** NOT WIRED TO models/risk.py's `RemarkStub` (table `remark_stubs`). READ FIRST. ***
    Since the person-B merge, TWO remark tables exist and NOTHING SYNCHRONISES THEM.

    This table is the WRITE side: POST /remarks and POST /remarks/bulk write here, and
    only GET /remarks/{student_id} reads it back. `sentiment_tag` is a hand-picked
    label ("academic" / "behavioral" / "appreciation") that defaults to "academic" and
    is never computed from the text.

    `remark_stubs` is the READ side that the rest of the product is built on: the
    parent portal remarks feed, the Parent Assistant Bot's qualitative summary, the
    nightly risk scorer's sentiment input, and GET /remarks/student/{student_id}
    (note the different path - the two endpoints do not collide). That side runs VADER
    over the text per request and returns {label, compound}.

    CONSEQUENCE: a remark filed through Person B's BulkRemarksPage will NOT show up in
    the parent feed, will NOT reach the Parent Bot, and will NOT influence risk
    scoring. Both features work; they are simply disconnected. This is a known,
    accepted deferral - see docs/audit/merge-01-conflicts.md (D-1) and
    docs/audit/remarks-disconnect.md before wiring them together, because the read
    paths are demo-critical.
    """

    __tablename__ = "remarks"
    __table_args__ = (
        Index("ix_remarks_student_id", "student_id"),
        Index("ix_remarks_class_subject", "class_id", "subject_id"),
        Index("ix_remarks_sentiment", "sentiment_tag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment_tag: Mapped[str] = mapped_column(String(50), default="academic", nullable=False)  # academic, behavioral, appreciation

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship()
    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    author: Mapped["User"] = relationship(foreign_keys=[author_id])
    school_class: Mapped["SchoolClass"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
