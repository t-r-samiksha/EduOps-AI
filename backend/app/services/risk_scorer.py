"""Heuristic (not trained-model) early-warning risk scorer.

Per the playbook's own phrasing this is a "heuristic scorer", not a trained ML model -
it's a documented, tunable weighted combination of three signals, each contributing a
0..1 "risk" sub-score:

    1. Attendance (REAL): present/absent/late counts from AttendanceRecord, the only
       signal this codebase genuinely owns and has real data for.
    2. Grades (REAL): built from Person B's `gradebook_entries` by
       scripts/run_nightly_risk_scoring.py, via
       services/gradebook_service.get_student_gradebook_summary(). A caller with no
       grade data still passes `None`, and this module then excludes the component
       entirely and renormalises the remaining weights rather than assuming a
       fabricated "average" that would silently bias the score - so a school with an
       empty gradebook scores exactly as it did before grades were wired in.
    3. Remark sentiment (PLACEHOLDER text source, REAL analysis): sentiment analysis
       itself (services/remark_sentiment.py) is real and fully functional; the *text*
       it analyzes currently comes from RemarkStub, a clearly-marked placeholder
       table (see app/models/risk.py) seeded with synthetic remarks, standing in for
       Person B's eventual real remarks/report-card system.

Decoupled from the ORM like timetable_solver.py/substitute_solver.py: callers build
plain dataclasses (typically from real DB queries in the caller, e.g.
scripts/run_nightly_risk_scoring.py or routers/risk.py) and get a plain dataclass
back - testable standalone with constructed fixtures, no DB needed.

WEIGHTING - documented and tunable, not learned
--------------------------------------------------
Default weights sum to 1.0 when every signal is available: attendance 0.50, grades
0.35, remarks 0.15. Attendance is weighted highest deliberately, because it's the one
signal guaranteed to be real for every student in this codebase; grades and remarks
are weighted lower partly because they're inherently noisier for early-warning
purposes and partly because - today - remarks may be synthetic and grades may be
completely absent. When a signal is unavailable, its weight is NOT redistributed as
extra confidence in what's left by design choice alone - it is simply excluded, and
the remaining weights are renormalized to sum to 1 among what's actually available.
This is an honest hackathon heuristic, not a validated clinical or statistical risk
model - thresholds below are round numbers chosen for a legible demo, not calibrated
against real outcome data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.remark_sentiment import analyze_sentiment

ATTENDANCE_RATE_THRESHOLD = 0.90
"""Attendance below this starts contributing risk; 0% attendance = max risk."""
GRADE_PASS_THRESHOLD_PCT = 75.0
"""Average grade below this starts contributing risk; 0% = max risk.

75, not a 60% pass mark, and the difference is the point. This is an EARLY-WARNING line,
not a pass/fail line: a student who has already fallen to 60% is not an early warning,
they are a late one. It is set to sit alongside ATTENDANCE_RATE_THRESHOLD (90%) so the
two signals are comparable in severity. At 60 a struggling student's grade risk came out
LOWER than their attendance risk, so adding the grade signal could push a flagged student
below the flag line even though both signals were bad - the composite got better as the
student got worse."""
DECLINING_TREND_PENALTY = 0.15
IMPROVING_TREND_RELIEF = 0.10
NEGATIVE_SENTIMENT_REASON_THRESHOLD = 0.15
"""Below this magnitude of remark-sentiment risk, don't bother surfacing a reason -
mildly-negative-on-average phrasing isn't worth calling out on its own."""

DEFAULT_WEIGHTS: dict[str, float] = {"attendance": 0.50, "grades": 0.35, "remarks": 0.15}

LOW_RISK_MAX = 0.30
MEDIUM_RISK_MAX = 0.60


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class AttendanceSignal:
    student_id: int
    present_count: int
    absent_count: int
    late_count: int
    total_records: int


@dataclass(frozen=True)
class GradeSignal:
    """Built from `gradebook_entries` — see scripts/run_nightly_risk_scoring.py's
    _build_grade_signal(), which sources it from
    services/gradebook_service.get_student_gradebook_summary()."""

    student_id: int
    average_score_pct: float
    """0..100."""
    trend: str | None = None
    """One of: improving, declining, stable, or None if unknown."""


@dataclass(frozen=True)
class RemarkSignal:
    student_id: int
    remark_texts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RiskScoreResult:
    score: float
    """0..1 composite risk score."""
    risk_level: str
    """One of: low, medium, high."""
    reasons: list[str]
    missing_signals: list[str]
    """Which of grades/remarks were unavailable and therefore excluded - never
    silently treated as "no risk" or fabricated, always reported."""


def _attendance_component(signal: AttendanceSignal) -> tuple[float, str | None]:
    if signal.total_records == 0:
        return 0.0, None
    rate = signal.present_count / signal.total_records
    risk = _clamp((ATTENDANCE_RATE_THRESHOLD - rate) / ATTENDANCE_RATE_THRESHOLD)
    reason = f"attendance rate {rate:.0%} is below the {ATTENDANCE_RATE_THRESHOLD:.0%} threshold" if risk > 0 else None
    return risk, reason


def _grade_component(signal: GradeSignal | None) -> tuple[float | None, str | None]:
    if signal is None:
        return None, None

    risk = _clamp((GRADE_PASS_THRESHOLD_PCT - signal.average_score_pct) / GRADE_PASS_THRESHOLD_PCT)
    if signal.trend == "declining":
        risk = _clamp(risk + DECLINING_TREND_PENALTY)
    elif signal.trend == "improving":
        risk = _clamp(risk - IMPROVING_TREND_RELIEF)

    reason = None
    if risk > 0:
        reason = f"average grade {signal.average_score_pct:.0f}% is below the {GRADE_PASS_THRESHOLD_PCT:.0f}% passing threshold"
        if signal.trend == "declining":
            reason += " and trending down"
    elif signal.trend == "declining":
        reason = "grade trend is declining"
    return risk, reason


def _remark_component(signal: RemarkSignal | None) -> tuple[float | None, str | None]:
    if signal is None or not signal.remark_texts:
        return None, None

    compounds = [analyze_sentiment(text).compound for text in signal.remark_texts]
    avg_compound = sum(compounds) / len(compounds)
    risk = _clamp(-avg_compound)
    reason = (
        f"recent teacher remarks skew negative (avg sentiment {avg_compound:.2f})"
        if risk > NEGATIVE_SENTIMENT_REASON_THRESHOLD
        else None
    )
    return risk, reason


def score_student(
    attendance: AttendanceSignal,
    grades: GradeSignal | None = None,
    remarks: RemarkSignal | None = None,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
) -> RiskScoreResult:
    components: dict[str, float] = {}
    reasons: list[str] = []
    missing: list[str] = []

    attendance_risk, attendance_reason = _attendance_component(attendance)
    components["attendance"] = attendance_risk
    if attendance_reason:
        reasons.append(attendance_reason)

    grade_risk, grade_reason = _grade_component(grades)
    if grade_risk is None:
        missing.append("grades")
    else:
        components["grades"] = grade_risk
        if grade_reason:
            reasons.append(grade_reason)

    remark_risk, remark_reason = _remark_component(remarks)
    if remark_risk is None:
        missing.append("remarks")
    else:
        components["remarks"] = remark_risk
        if remark_reason:
            reasons.append(remark_reason)

    total_weight = sum(weights[key] for key in components)
    score = sum(components[key] * weights[key] for key in components) / total_weight if total_weight else 0.0
    score = round(_clamp(score), 3)

    if score <= LOW_RISK_MAX:
        risk_level = "low"
    elif score <= MEDIUM_RISK_MAX:
        risk_level = "medium"
    else:
        risk_level = "high"

    if not reasons:
        reasons.append(
            "no individual signal crossed its risk threshold"
            if risk_level == "low"
            else "combined signals indicate elevated risk despite no single dominant factor"
        )

    return RiskScoreResult(score=score, risk_level=risk_level, reasons=reasons, missing_signals=missing)
