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

    Person B owns the actual gradebook/report-card/remarks system, which doesn't
    exist in this repo yet. There's nowhere real for a "teacher remark" to live, and
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
