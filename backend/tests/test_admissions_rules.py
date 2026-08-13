from app.services.admissions_rules import check_eligibility, check_transition

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


# --- eligibility ---


def test_offered_grade_is_eligible():
    result = check_eligibility("Grade 8", {"Grade 7", "Grade 8", "Grade 9"})
    assert result.eligible is True
    assert result.reason is None


def test_non_offered_grade_is_not_eligible():
    result = check_eligibility("Grade 13", {"Grade 7", "Grade 8", "Grade 9"})
    assert result.eligible is False
    assert "Grade 13" in result.reason


def test_no_offered_grades_means_nothing_is_eligible():
    result = check_eligibility("Grade 8", set())
    assert result.eligible is False
