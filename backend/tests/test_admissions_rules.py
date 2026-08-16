from app.services.admissions_rules import (
    SectionCandidate,
    check_eligibility,
    check_reject_reason,
    check_transition,
    grade_level_display,
    pick_section,
)

# --- state machine: legal transitions ---


def test_submitted_to_under_review_is_legal():
    result = check_transition("submitted", "under_review")
    assert result.allowed is True
    assert result.reason is None


def test_submitted_to_rejected_is_legal():
    assert check_transition("submitted", "rejected").allowed is True


def test_under_review_to_accepted_is_legal():
    assert check_transition("under_review", "accepted").allowed is True


def test_under_review_to_rejected_is_legal():
    assert check_transition("under_review", "rejected").allowed is True


# --- state machine: illegal transitions, explicitly rejected ---


def test_submitted_to_accepted_directly_is_illegal():
    result = check_transition("submitted", "accepted")
    assert result.allowed is False
    assert "under_review" in result.reason


def test_accepted_is_terminal():
    result = check_transition("accepted", "under_review")
    assert result.allowed is False
    assert "terminal" in result.reason


def test_rejected_is_terminal():
    result = check_transition("rejected", "accepted")
    assert result.allowed is False
    assert "terminal" in result.reason


def test_transition_to_same_status_is_rejected():
    result = check_transition("under_review", "under_review")
    assert result.allowed is False


def test_transition_to_invalid_status_is_rejected():
    result = check_transition("submitted", "not_a_real_status")
    assert result.allowed is False


def test_transition_from_invalid_current_status_is_rejected():
    result = check_transition("not_a_real_status", "under_review")
    assert result.allowed is False


# --- reject requires a real reason ---


def test_reject_without_reason_is_blocked():
    assert check_reject_reason("rejected", None) is not None
    assert check_reject_reason("rejected", "") is not None
    assert check_reject_reason("rejected", "   ") is not None


def test_reject_with_real_reason_is_allowed():
    assert check_reject_reason("rejected", "Grade not offered at this campus") is None


def test_accept_never_requires_a_reason():
    assert check_reject_reason("accepted", None) is None


def test_under_review_never_requires_a_reason():
    assert check_reject_reason("under_review", None) is None


# --- grade_level_display: purely cosmetic, LKG/UKG/Nursery overrides ---


def test_grade_level_display_for_ordinary_grades():
    assert grade_level_display(3) == "Grade 3"
    assert grade_level_display(10) == "Grade 10"


def test_grade_level_display_for_pre_grade_1_levels():
    assert grade_level_display(-3) == "Nursery"
    assert grade_level_display(-2) == "LKG"
    assert grade_level_display(-1) == "UKG"


# --- eligibility: grade LEVEL, not section name (the real bug fix) ---


def test_offered_grade_level_is_eligible():
    result = check_eligibility("8", {"7", "8", "9"})
    assert result.eligible is True
    assert result.reason is None


def test_non_offered_grade_level_is_not_eligible():
    result = check_eligibility("13", {"7", "8", "9"})
    assert result.eligible is False
    assert "Grade 13" in result.reason
    assert "Grade 7" in result.reason and "Grade 8" in result.reason and "Grade 9" in result.reason


def test_no_offered_grades_means_nothing_is_eligible():
    result = check_eligibility("8", set())
    assert result.eligible is False


def test_eligibility_message_uses_friendly_labels_for_pre_grade_1_levels():
    result = check_eligibility("3", {"-2", "-1"})
    assert result.eligible is False
    assert "LKG" in result.reason
    assert "UKG" in result.reason
    # never the raw negative int in the message
    assert "-2" not in result.reason
    assert "-1" not in result.reason


def test_offered_lkg_is_eligible():
    result = check_eligibility("-2", {"-2", "-1", "1"})
    assert result.eligible is True


# --- section assignment: least-filled qualifying section, never overfills ---


def _candidate(class_id: int, grade_level: int, current_count: int, capacity: int = 30) -> SectionCandidate:
    return SectionCandidate(class_id=class_id, grade_level=grade_level, current_count=current_count, capacity=capacity)


def test_picks_the_least_filled_section_at_the_requested_grade_level():
    candidates = [
        _candidate(1, grade_level=3, current_count=20),
        _candidate(2, grade_level=3, current_count=5),
        _candidate(3, grade_level=3, current_count=25),
    ]
    result = pick_section(3, "2026-27", candidates)
    assert result.class_id == 2
    assert result.reason is None


def test_ignores_sections_at_a_different_grade_level():
    candidates = [_candidate(1, grade_level=4, current_count=0)]
    result = pick_section(3, "2026-27", candidates)
    assert result.class_id is None
    assert "Grade 3" in result.reason


def test_ignores_full_sections_even_if_least_filled_among_all():
    candidates = [
        _candidate(1, grade_level=3, current_count=30, capacity=30),  # full
        _candidate(2, grade_level=3, current_count=10, capacity=30),  # has room
    ]
    result = pick_section(3, "2026-27", candidates)
    assert result.class_id == 2


def test_no_available_seats_returns_clear_specific_error_not_silent_overfill():
    candidates = [
        _candidate(1, grade_level=3, current_count=30, capacity=30),
        _candidate(2, grade_level=3, current_count=30, capacity=30),
    ]
    result = pick_section(3, "2026-27", candidates)
    assert result.class_id is None
    assert result.reason == "No available seats in Grade 3 for 2026-27 - all sections full"


def test_no_available_seats_uses_friendly_label_for_pre_grade_1_levels():
    candidates = [_candidate(1, grade_level=-2, current_count=30, capacity=30)]
    result = pick_section(-2, "2026-27", candidates)
    assert result.class_id is None
    assert "LKG" in result.reason


def test_empty_candidate_list_returns_no_seats_error():
    result = pick_section(3, "2026-27", [])
    assert result.class_id is None
    assert "Grade 3" in result.reason
