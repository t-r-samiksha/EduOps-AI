from datetime import date, timedelta

from app.services.staffing_forecast import (
    MIN_DISTINCT_WEEKDAYS_FOR_MODEL,
    MIN_OBSERVATIONS_FOR_MODEL,
    HistoricalGapObservation,
    forecast_staffing_gaps,
)

MONDAY = date(2026, 8, 3)
FRIDAY = date(2026, 8, 7)


def _dates_for_weekday(start: date, weekday: int, count: int) -> list[date]:
    offset = (weekday - start.weekday()) % 7
    first = start + timedelta(days=offset)
    return [first - timedelta(weeks=w) for w in range(count)]


def test_no_history_forecasts_zero_for_every_date():
    forecast_dates = [MONDAY + timedelta(days=i) for i in range(7)]
    results = forecast_staffing_gaps([], forecast_dates, total_teacher_count=6)

    assert len(results) == 7
    assert all(r.predicted_gap_count == 0.0 for r in results)
    assert all(r.risk_level == "low" for r in results)
    assert [r.date for r in results] == forecast_dates


def test_output_shape_matches_requested_dates_in_order():
    history = [HistoricalGapObservation(date=MONDAY - timedelta(days=7), gap_count=1)]
    forecast_dates = [MONDAY, MONDAY + timedelta(days=3), FRIDAY]

    results = forecast_staffing_gaps(history, forecast_dates, total_teacher_count=6)

    assert [r.date for r in results] == forecast_dates
    for r in results:
        assert r.risk_level in ("low", "medium", "high")
        assert r.predicted_gap_count >= 0.0


def test_sparse_history_falls_back_to_weekday_mean():
    # Below MIN_OBSERVATIONS_FOR_MODEL - must use the rule-based per-weekday mean,
    # not attempt to fit the ML layer.
    history = [
        HistoricalGapObservation(date=d, gap_count=2) for d in _dates_for_weekday(MONDAY, 4, 3)  # 3 past Fridays, gap=2
    ]
    assert len(history) < MIN_OBSERVATIONS_FOR_MODEL

    results = forecast_staffing_gaps(history, [FRIDAY], total_teacher_count=6)
    assert results[0].predicted_gap_count == 2.0


def test_risk_level_thresholds():
    # total_teacher_count=10: low <=1.5, medium <=3.5, else high (per the module's
    # LOW/MEDIUM_RISK_MAX_FRACTION of 0.15/0.35).
    history_low = [HistoricalGapObservation(date=MONDAY - timedelta(days=7), gap_count=1)]
    history_medium = [HistoricalGapObservation(date=MONDAY - timedelta(days=7), gap_count=3)]
    history_high = [HistoricalGapObservation(date=MONDAY - timedelta(days=7), gap_count=8)]

    assert forecast_staffing_gaps(history_low, [MONDAY], 10)[0].risk_level == "low"
    assert forecast_staffing_gaps(history_medium, [MONDAY], 10)[0].risk_level == "medium"
    assert forecast_staffing_gaps(history_high, [MONDAY], 10)[0].risk_level == "high"


def test_ml_layer_engages_with_enough_history_and_finds_weekday_pattern():
    # Mirrors the seed script's pattern: heavy Friday absences, light Monday
    # baseline, enough distinct weeks/weekdays to clear both MIN_ thresholds.
    history = []
    for d in _dates_for_weekday(MONDAY, 4, 6):  # 6 past Fridays
        history.append(HistoricalGapObservation(date=d, gap_count=3))
    for d in _dates_for_weekday(MONDAY, 0, 6):  # 6 past Mondays
        history.append(HistoricalGapObservation(date=d, gap_count=0))
    for d in _dates_for_weekday(MONDAY, 2, 4):  # 4 past Wednesdays
        history.append(HistoricalGapObservation(date=d, gap_count=1))

    assert len(history) >= MIN_OBSERVATIONS_FOR_MODEL
    assert len({obs.date.weekday() for obs in history}) >= MIN_DISTINCT_WEEKDAYS_FOR_MODEL

    next_monday = MONDAY + timedelta(days=7)
    next_friday = FRIDAY + timedelta(days=7)
    results = forecast_staffing_gaps(history, [next_monday, next_friday], total_teacher_count=6)

    by_date = {r.date: r for r in results}
    assert by_date[next_friday].predicted_gap_count > by_date[next_monday].predicted_gap_count


def test_negative_predictions_are_clamped_to_zero():
    # Degenerate but legal input: a single zero-gap observation. The model (or
    # fallback) must never predict a negative gap count.
    history = [HistoricalGapObservation(date=MONDAY - timedelta(days=7), gap_count=0)]
    results = forecast_staffing_gaps(history, [MONDAY], total_teacher_count=6)
    assert results[0].predicted_gap_count >= 0.0
