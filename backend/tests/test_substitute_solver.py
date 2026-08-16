from app.services.substitute_solver import SubstituteCandidate, find_fallback_substitutes, find_substitutes

MATH = 1
ORIGINAL_TEACHER = 100


def _candidate(teacher_id: int, **overrides) -> SubstituteCandidate:
    defaults = dict(
        teacher_id=teacher_id,
        qualified_subject_ids=frozenset({MATH}),
        already_busy=False,
        unavailable=False,
        on_leave=False,
        current_workload=5,
        already_substituting=False,
    )
    defaults.update(overrides)
    return SubstituteCandidate(**defaults)


def test_finds_qualified_free_candidate():
    candidates = [_candidate(1)]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)

    assert len(suggestions) == 1
    assert suggestions[0].teacher_id == 1
    assert suggestions[0].score > 0


def test_excludes_original_teacher_even_if_otherwise_eligible():
    candidates = [_candidate(ORIGINAL_TEACHER)]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)
    assert suggestions == []


def test_excludes_unqualified_teacher():
    candidates = [_candidate(1, qualified_subject_ids=frozenset({999}))]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)
    assert suggestions == []


def test_excludes_already_busy_teacher():
    candidates = [_candidate(1, already_busy=True)]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)
    assert suggestions == []


def test_excludes_unavailable_teacher():
    candidates = [_candidate(1, unavailable=True)]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)
    assert suggestions == []


def test_excludes_teacher_on_approved_leave():
    candidates = [_candidate(1, on_leave=True)]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)
    assert suggestions == []


def test_excludes_teacher_already_confirmed_substituting_elsewhere():
    """Regression test for a real double-booking bug: a teacher with nothing on
    their own real timetable at this day/period (already_busy=False) could still
    already be CONFIRMED as someone else's substitute for a different class at
    that exact same day/period - this must be excluded too, not just their own
    static timetable."""
    candidates = [_candidate(1, already_substituting=True)]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)
    assert suggestions == []


def test_returns_empty_list_not_error_when_no_eligible_candidates():
    candidates = [_candidate(1, already_busy=True), _candidate(2, unavailable=True), _candidate(3, on_leave=True)]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)
    assert suggestions == []


def test_workload_balance_prefers_less_loaded_teacher():
    candidates = [_candidate(1, current_workload=20), _candidate(2, current_workload=2)]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)

    assert [s.teacher_id for s in suggestions] == [2, 1]
    assert suggestions[0].score > suggestions[1].score


def test_mixed_eligible_and_ineligible_candidates():
    candidates = [
        _candidate(1, current_workload=10),
        _candidate(2, already_busy=True),
        _candidate(3, unavailable=True),
        _candidate(4, on_leave=True),
        _candidate(5, qualified_subject_ids=frozenset({999})),
        _candidate(6, current_workload=3),
    ]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)

    assert {s.teacher_id for s in suggestions} == {1, 6}
    assert suggestions[0].teacher_id == 6  # lower workload ranks first


def test_respects_max_results():
    candidates = [_candidate(i, current_workload=i) for i in range(1, 6)]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates, max_results=2)
    assert len(suggestions) == 2
    assert [s.teacher_id for s in suggestions] == [1, 2]  # two lowest workloads


def test_all_scores_within_expected_range():
    candidates = [_candidate(i, current_workload=i * 3) for i in range(1, 5)]
    suggestions = find_substitutes(subject_id=MATH, original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)
    for s in suggestions:
        assert 0.7 <= s.score <= 1.0


# --- find_fallback_substitutes (real-world "nobody qualified" escalation) ---


def test_fallback_surfaces_unqualified_but_free_teacher():
    """Regression test for the automatic fallback tier: a teacher who fails the
    subject-qualification filter must still be surfaced (flagged
    qualified=False) as a supervision-only suggestion, since find_substitutes()
    would otherwise leave the admin with nothing but a blind manual pick."""
    candidates = [_candidate(1, qualified_subject_ids=frozenset({999}))]  # not qualified for MATH
    suggestions = find_fallback_substitutes(original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)

    assert len(suggestions) == 1
    assert suggestions[0].teacher_id == 1
    assert suggestions[0].qualified is False
    assert "not qualified" in suggestions[0].reason.lower()


def test_fallback_still_excludes_original_teacher():
    candidates = [_candidate(ORIGINAL_TEACHER, qualified_subject_ids=frozenset())]
    suggestions = find_fallback_substitutes(original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)
    assert suggestions == []


def test_fallback_still_excludes_busy_unavailable_on_leave_and_already_substituting():
    """The fallback tier waives ONLY the subject-qualification filter - every
    other hard filter (real scheduling/physical impossibilities) still applies
    unchanged."""
    candidates = [
        _candidate(1, already_busy=True),
        _candidate(2, unavailable=True),
        _candidate(3, on_leave=True),
        _candidate(4, already_substituting=True),
    ]
    suggestions = find_fallback_substitutes(original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)
    assert suggestions == []


def test_fallback_ranks_by_workload_same_as_normal_suggestions():
    candidates = [_candidate(1, current_workload=20), _candidate(2, current_workload=2)]
    suggestions = find_fallback_substitutes(original_teacher_id=ORIGINAL_TEACHER, candidates=candidates)
    assert [s.teacher_id for s in suggestions] == [2, 1]
    assert all(s.qualified is False for s in suggestions)
