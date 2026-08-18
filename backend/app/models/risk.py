from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RiskFlag(Base):
    """An open/acknowledged/resolved early-warning flag for a student, created either
    manually (POST /risk/flag) or by the nightly risk-scoring job
    (scripts/run_nightly_risk_scoring.py -> services/risk_scorer.py)."""

    __tablename__ = "risk_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    """One of: low, medium, high."""
    score: Mapped[float] = mapped_column(Float, nullable=False)
    """0..1 composite risk score - see services/risk_scorer.py for how it's computed."""
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    flagged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="open")
    """One of: open, acknowledged, resolved."""
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    resolver: Mapped["User | None"] = relationship(foreign_keys=[resolved_by])


class Intervention(Base):
    """An outreach/intervention note logged against a RiskFlag - the human-readable
    history of what staff actually did about a flagged student."""

    __tablename__ = "interventions"

    id: Mapped[int] = mapped_column(primary_key=True)
    risk_flag_id: Mapped[int] = mapped_column(ForeignKey("risk_flags.id"), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    action_taken: Mapped[str] = mapped_column(String(255), nullable=False)
    """Free text, e.g. "called parent", "counselor referral", "teacher meeting" - not
    an enum, deliberately open-ended like LeaveRequest.reason elsewhere."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    risk_flag: Mapped["RiskFlag"] = relationship()
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])


class RemarkStub(Base):
    """PLACEHOLDER TABLE - not the real thing.

    *** NOT WIRED TO models/remark.py's `Remark` (table `remarks`). READ THIS FIRST. ***
    Since the person-B merge, TWO remark tables exist and NOTHING SYNCHRONISES THEM:

      - `remark_stubs` (this table) is what the READ side uses: the parent portal
        remarks feed, the Parent Assistant Bot's qualitative summary, the nightly risk
        scorer's sentiment input, and GET /remarks/student/{student_id}. Sentiment is
        computed per request by services/remark_sentiment.py (VADER) - there is no
        sentiment column here, deliberately, so the scorer's thresholds can change
        without a backfill.
      - `remarks` is what the WRITE side uses: POST /remarks and POST /remarks/bulk
        (Person B's BulkRemarksPage), read back only by GET /remarks/{student_id}.
        It carries a hand-picked `sentiment_tag` string, never a computed score.

    So a remark a teacher files through Person B's UI does NOT appear in the parent
    feed, does NOT reach the Parent Bot, and does NOT affect risk scoring. That is a
    known, accepted deferral, not a bug to fix by pointing one at the other casually -
    both read paths are demo-critical. See docs/audit/merge-01-conflicts.md (D-1) and
    docs/audit/remarks-disconnect.md before changing either.

    Person B's gradebook/report-card/remarks system now DOES exist in this repo (it
    did not when this table was written). There's still nowhere real for the scorer's
    remark text to live, and
    the early-warning scorer needs *some* remark text to run sentiment analysis
    against to be genuinely testable end-to-end (not just against hardcoded strings
    in a unit test). This table exists ONLY to hold synthetic seeded remark text for
    that purpose - it is not a stand-in for report cards, assignment feedback, or any
    other real Person-B-owned concept, and deliberately has the bare minimum columns
    so it's trivial to delete once Person B's real remarks system lands (at which
    point services/risk_scorer.py's RemarkSignal should be built from that instead -
    see this module's and risk_scorer.py's docstrings).

    By contrast, there is NO placeholder table for grades: risk_scorer.py's
    GradeSignal is a pure dataclass interface with no backing table at all, because
    a "minimal" grades table would still require presupposing subject/assignment
    structure that is genuinely Person B's design decision to make, not ours.
    """

    __tablename__ = "remark_stubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    remark_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])
