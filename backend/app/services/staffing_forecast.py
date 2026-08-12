"""Forecasts staffing gaps (teachers absent/on-leave) from historical patterns.

Decoupled from the ORM, like timetable_solver.py and attendance_cv.py: callers pass
plain dataclasses built from whatever historical `LeaveRequest` rows exist, get plain
dataclasses back.

HONESTY ABOUT SCALE - this is a demo-scale model, not production-grade
------------------------------------------------------------------------
A real staffing-gap forecaster would train on months/years of attendance history
across many schools. This hackathon's dataset is, at best, a handful of teachers over
a few synthetic weeks (see `scripts/seed_demo_data.py`'s historical leave block) - not
enough signal for a "real" time-series model, and not what this module pretends to be.

The approach is a deliberately simple two-tier hybrid:
1. Rule-based baseline: mean historical gap_count per day-of-week. Always computable,
   even from a single observation, and always what small/sparse inputs fall back to.
2. ML layer: if there's enough historical spread to fit anything meaningful (see
   MIN_OBSERVATIONS_FOR_MODEL / MIN_DISTINCT_WEEKDAYS_FOR_MODEL), a scikit-learn
   PoissonRegressor - the textbook-appropriate choice for non-negative count data -
   is fit on one-hot day-of-week features plus a linear time-index trend feature, and
   its prediction is used instead of the plain per-weekday mean.

With ~6 teachers and ~8 weeks of data (this project's actual scale), tier 2 usually
does engage, but treat its output as "a slightly smarter weighted average", not a
statistically validated forecast. risk_level thresholds are simple fractions of the
school's total teacher count, not calibrated against any real outcome data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from sklearn.linear_model import PoissonRegressor

MIN_OBSERVATIONS_FOR_MODEL = 10
MIN_DISTINCT_WEEKDAYS_FOR_MODEL = 3

# risk_level thresholds as a fraction of total_teacher_count.
LOW_RISK_MAX_FRACTION = 0.15
MEDIUM_RISK_MAX_FRACTION = 0.35


@dataclass(frozen=True)
class HistoricalGapObservation:
    """One past date's observed staffing gap: how many teachers were on approved
    leave that day."""

    date: date
    gap_count: int


@dataclass(frozen=True)
class DailyForecast:
    date: date
    predicted_gap_count: float
    risk_level: str
    """One of: low, medium, high."""


def _risk_level(predicted_gap_count: float, total_teacher_count: int) -> str:
    if total_teacher_count <= 0:
        return "low"
    fraction = predicted_gap_count / total_teacher_count
    if fraction <= LOW_RISK_MAX_FRACTION:
        return "low"
    if fraction <= MEDIUM_RISK_MAX_FRACTION:
        return "medium"
    return "high"


def _weekday_means(history: list[HistoricalGapObservation]) -> dict[int, float]:
    by_weekday: dict[int, list[int]] = {}
    for obs in history:
        by_weekday.setdefault(obs.date.weekday(), []).append(obs.gap_count)
    return {weekday: sum(counts) / len(counts) for weekday, counts in by_weekday.items()}


def _try_fit_poisson_model(history: list[HistoricalGapObservation]) -> PoissonRegressor | None:
    distinct_weekdays = {obs.date.weekday() for obs in history}
    if len(history) < MIN_OBSERVATIONS_FOR_MODEL or len(distinct_weekdays) < MIN_DISTINCT_WEEKDAYS_FOR_MODEL:
        return None

    ordered = sorted(history, key=lambda obs: obs.date)
    earliest = ordered[0].date
    X = np.array(
        [_weekday_one_hot(obs.date.weekday()) + [(obs.date - earliest).days] for obs in ordered], dtype=float
    )
    y = np.array([obs.gap_count for obs in ordered], dtype=float)

    try:
        model = PoissonRegressor(alpha=1.0, max_iter=300)
        model.fit(X, y)
    except (ValueError, ArithmeticError):
        return None
    return model


def _weekday_one_hot(weekday: int) -> list[float]:
    return [1.0 if i == weekday else 0.0 for i in range(7)]


def forecast_staffing_gaps(
    history: list[HistoricalGapObservation],
    forecast_dates: list[date],
    total_teacher_count: int,
) -> list[DailyForecast]:
    """Predict gap_count for each of forecast_dates from `history`. Falls back to 0
    for every date when there's no history at all - "no data, no predicted gaps" is a
    more honest default than fabricating a number."""
    if not history:
        return [DailyForecast(date=d, predicted_gap_count=0.0, risk_level="low") for d in forecast_dates]

    weekday_means = _weekday_means(history)
    overall_mean = sum(obs.gap_count for obs in history) / len(history)
    model = _try_fit_poisson_model(history)

    earliest = min(obs.date for obs in history)

    results = []
    for d in forecast_dates:
        if model is not None:
            features = np.array([_weekday_one_hot(d.weekday()) + [(d - earliest).days]], dtype=float)
            predicted = max(0.0, float(model.predict(features)[0]))
        else:
            predicted = weekday_means.get(d.weekday(), overall_mean)

        results.append(
            DailyForecast(
                date=d,
                predicted_gap_count=round(predicted, 2),
                risk_level=_risk_level(predicted, total_teacher_count),
            )
        )
    return results
