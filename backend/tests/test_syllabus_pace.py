from datetime import date

from app.services.syllabus_pace import (
    AHEAD_THRESHOLD,
    BEHIND_THRESHOLD,
    SyllabusPlanInput,
    compute_pace,
)

PLAN_ID, CLASS_ID, SUBJECT_ID = 1, 2, 3


def _plan(total_units, term_start, term_end, checkpoints_logged):
    return SyllabusPlanInput(
        plan_id=PLAN_ID, class_id=CLASS_ID, subject_id=SUBJECT_ID,
        total_units=total_units, term_start_date=term_start, term_end_date=term_end,
        checkpoints_logged=checkpoints_logged,
    )


def test_task_brief_example_5_weeks_into_10_week_term_30pct_covered_is_behind():
    # 10-week term = 70 days, 5 weeks elapsed = 35 days -> expected_fraction=0.5.
    # 30% of 10 topics covered -> actual_fraction=0.3. drift=-0.2, behind.
    from datetime import timedelta

    plan = _plan(total_units=10, term_start=date(2026, 1, 1), term_end=date(2026, 3, 12), checkpoints_logged=3)
    today = date(2026, 1, 1) + timedelta(days=35)
    result = compute_pace(plan, today)

    assert result.expected_fraction == 0.5
    assert result.actual_fraction == 0.3
    assert result.drift == -0.2
    assert result.status == "behind"


def test_on_pace_when_drift_within_threshold():
    from datetime import timedelta

    term_start = date(2026, 1, 1)
    term_end = term_start + timedelta(days=100)
    today = term_start + timedelta(days=50)  # expected_fraction = 0.5
    plan = _plan(total_units=10, term_start=term_start, term_end=term_end, checkpoints_logged=5)  # actual = 0.5

    result = compute_pace(plan, today)
    assert result.drift == 0.0
    assert result.status == "on_pace"


def test_ahead_when_drift_exceeds_positive_threshold():
    from datetime import timedelta

    term_start = date(2026, 1, 1)
    term_end = term_start + timedelta(days=100)
    today = term_start + timedelta(days=20)  # expected_fraction = 0.2
    plan = _plan(total_units=10, term_start=term_start, term_end=term_end, checkpoints_logged=9)  # actual = 0.9

    result = compute_pace(plan, today)
    assert result.drift >= AHEAD_THRESHOLD
    assert result.status == "ahead"


def test_behind_boundary_is_inclusive():
    from datetime import timedelta

    term_start = date(2026, 1, 1)
    term_end = term_start + timedelta(days=100)
    today = term_start + timedelta(days=50)  # expected_fraction = 0.5
    # total_units=20 so (0.5 + BEHIND_THRESHOLD) * 20 = 7 exactly, no rounding error.
    checkpoints = round((0.5 + BEHIND_THRESHOLD) * 20)
    plan = _plan(total_units=20, term_start=term_start, term_end=term_end, checkpoints_logged=checkpoints)

    result = compute_pace(plan, today)
    assert result.drift == BEHIND_THRESHOLD
    assert result.status == "behind"


def test_no_checkpoints_logged_before_term_starts_is_on_pace_not_behind():
    from datetime import timedelta

    term_start = date(2026, 6, 1)
    term_end = term_start + timedelta(days=100)
    today = date(2026, 1, 1)  # before the term even starts
    plan = _plan(total_units=10, term_start=term_start, term_end=term_end, checkpoints_logged=0)

    result = compute_pace(plan, today)
    assert result.expected_fraction == 0.0  # clamped, not negative
    assert result.status == "on_pace"


def test_term_fully_elapsed_expected_fraction_clamped_to_one():
    from datetime import timedelta

    term_start = date(2026, 1, 1)
    term_end = term_start + timedelta(days=50)
    today = term_start + timedelta(days=200)  # long past the term end
    plan = _plan(total_units=10, term_start=term_start, term_end=term_end, checkpoints_logged=10)

    result = compute_pace(plan, today)
    assert result.expected_fraction == 1.0


def test_degenerate_plan_end_before_start_does_not_crash():
    plan = _plan(total_units=5, term_start=date(2026, 3, 1), term_end=date(2026, 1, 1), checkpoints_logged=2)
    result = compute_pace(plan, date(2026, 2, 1))
    assert result.expected_fraction == 1.0  # treated as term already over


def test_zero_total_units_does_not_divide_by_zero():
    from datetime import timedelta

    plan = _plan(total_units=0, term_start=date(2026, 1, 1), term_end=date(2026, 1, 1) + timedelta(days=10), checkpoints_logged=0)
    result = compute_pace(plan, date(2026, 1, 5))
    assert result.actual_fraction == 0.0


def test_actual_fraction_is_clamped_when_overlogged():
    from datetime import timedelta

    term_start = date(2026, 1, 1)
    plan = _plan(total_units=5, term_start=term_start, term_end=term_start + timedelta(days=10), checkpoints_logged=999)
    result = compute_pace(plan, term_start)
    assert result.actual_fraction == 1.0
