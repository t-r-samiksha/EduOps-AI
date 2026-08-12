from app.services.substitute_solver import SubstituteCandidate, find_substitutes

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
