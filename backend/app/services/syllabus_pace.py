"""Syllabus pace tracking: how much of a SyllabusPlan's planned units have actually
been covered vs. how far through the term we are, per playbook 11.3.

PACING MODEL - deliberately simple, documented as a real limitation
------------------------------------------------------------------------
A SyllabusPlan (models/syllabus.py) is a flat total_units count across
[term_start_date, term_end_date] - no week-by-week breakdown, matching how a
syllabus is normally issued (a fixed list of topics to get through by a fixed date),
not a detailed scheme-of-work that front-loads harder topics or accounts for exam
weeks/holidays. Expected progress at any point is therefore LINEAR:

    expected_fraction = elapsed_days / total_days   (clamped to [0, 1])

This is honest-simple, not a claim of pedagogical accuracy - a real pacing curve
would vary topic weight and calendar exceptions. Documented here rather than hidden
behind a plausible-looking number.

PROGRESS MEASUREMENT - count-based, not sequence-based
------------------------------------------------------------
actual_fraction = checkpoints_logged / total_units. Deliberately a raw COUNT of
SyllabusCheckpoint rows, not derived from sequence_number - see that model's
docstring: a teacher may legitimately log topics out of syllabus order, so counting
is the only honest measure of "how much has been covered".

DRIFT THRESHOLD
------------------
drift = actual_fraction - expected_fraction. Flagged "behind" at drift <=
BEHIND_THRESHOLD (-0.15, i.e. 15 percentage points behind pace) and "ahead" at drift
>= AHEAD_THRESHOLD (+0.15) - ahead isn't a problem, but is useful signal (the plan may
be light, or the class could take on more). Everything between is "on_pace". Round,
undconfigurable-by-data numbers chosen for a legible demo - same honesty as
risk_scorer.py's thresholds, not calibrated against real academic outcomes.

Example from the task brief: 5 weeks into a 10-week term (expected_fraction=0.5),
only 30% of planned topics logged (actual_fraction=0.3) -> drift=-0.2, below -0.15 ->
"behind".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

BEHIND_THRESHOLD = -0.15
AHEAD_THRESHOLD = 0.15


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class SyllabusPlanInput:
    plan_id: int
    class_id: int
    subject_id: int
    total_units: int
    term_start_date: date
    term_end_date: date
    checkpoints_logged: int


@dataclass(frozen=True)
class SyllabusPaceResult:
    plan_id: int
    class_id: int
    subject_id: int
    expected_fraction: float
    actual_fraction: float
    drift: float
    status: str
    """One of: behind, on_pace, ahead."""


def compute_pace(plan: SyllabusPlanInput, today: date) -> SyllabusPaceResult:
    total_days = (plan.term_end_date - plan.term_start_date).days
    if total_days <= 0:
        # A degenerate plan (end_date <= start_date) - treat the term as already
        # over rather than dividing by zero or crashing on bad input data.
        expected_fraction = 1.0
    else:
        elapsed_days = (today - plan.term_start_date).days
        expected_fraction = _clamp(elapsed_days / total_days)

    actual_fraction = _clamp(plan.checkpoints_logged / plan.total_units) if plan.total_units > 0 else 0.0

    drift = round(actual_fraction - expected_fraction, 3)
    if drift <= BEHIND_THRESHOLD:
        status = "behind"
    elif drift >= AHEAD_THRESHOLD:
        status = "ahead"
    else:
        status = "on_pace"

    return SyllabusPaceResult(
        plan_id=plan.plan_id,
        class_id=plan.class_id,
        subject_id=plan.subject_id,
        expected_fraction=round(expected_fraction, 3),
        actual_fraction=round(actual_fraction, 3),
        drift=drift,
        status=status,
    )
