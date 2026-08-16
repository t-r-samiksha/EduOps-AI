from datetime import time

import pytest

from app.services.exam_scheduler import (
    InsufficientCapacityError,
    InvigilatorCandidate,
    RoomCapacity,
    TimeRange,
    assign_invigilators_for_exam,
    find_invigilators,
    generate_seating,
    suggest_rooms,
)

# --- generate_seating ---


def test_seats_every_student_exactly_once():
    assignments = generate_seating([1, 2, 3, 4, 5], [RoomCapacity(room_id=10, capacity=3), RoomCapacity(room_id=11, capacity=3)])
    assert {a.student_id for a in assignments} == {1, 2, 3, 4, 5}
    assert len(assignments) == 5


def test_no_room_exceeds_its_capacity():
    assignments = generate_seating(list(range(10)), [RoomCapacity(room_id=1, capacity=6), RoomCapacity(room_id=2, capacity=4)])
    counts = {}
    for a in assignments:
        counts[a.room_id] = counts.get(a.room_id, 0) + 1
    assert counts[1] <= 6
    assert counts[2] <= 4


def test_no_seat_double_booked():
    assignments = generate_seating(list(range(8)), [RoomCapacity(room_id=1, capacity=5), RoomCapacity(room_id=2, capacity=5)])
    seat_keys = [(a.room_id, a.seat_no) for a in assignments]
    assert len(seat_keys) == len(set(seat_keys))


def test_seat_numbers_are_1_indexed_and_contiguous_per_room():
    assignments = generate_seating(list(range(3)), [RoomCapacity(room_id=1, capacity=3)])
    assert sorted(a.seat_no for a in assignments) == [1, 2, 3]


def test_insufficient_capacity_raises_not_silently_overflows():
    with pytest.raises(InsufficientCapacityError):
        generate_seating(list(range(10)), [RoomCapacity(room_id=1, capacity=5)])


def test_exact_capacity_fit_succeeds():
    assignments = generate_seating(list(range(5)), [RoomCapacity(room_id=1, capacity=5)])
    assert len(assignments) == 5


def test_empty_student_list_is_fine():
    assert generate_seating([], [RoomCapacity(room_id=1, capacity=5)]) == []


# --- suggest_rooms ---


def test_suggest_rooms_prefers_smallest_single_room_that_fits():
    rooms = [RoomCapacity(room_id=1, capacity=50), RoomCapacity(room_id=2, capacity=35), RoomCapacity(room_id=3, capacity=10)]
    assert suggest_rooms(rooms, headcount=28) == [RoomCapacity(room_id=2, capacity=35)]


def test_suggest_rooms_combines_largest_first_when_no_single_room_fits():
    rooms = [RoomCapacity(room_id=1, capacity=10), RoomCapacity(room_id=2, capacity=15), RoomCapacity(room_id=3, capacity=5)]
    chosen = suggest_rooms(rooms, headcount=20)
    assert chosen[0] == RoomCapacity(room_id=2, capacity=15)  # largest first
    assert sum(r.capacity for r in chosen) >= 20


def test_suggest_rooms_returns_empty_for_zero_headcount():
    assert suggest_rooms([RoomCapacity(room_id=1, capacity=30)], headcount=0) == []


def test_suggest_rooms_returns_empty_when_no_rooms_available():
    assert suggest_rooms([], headcount=10) == []


# --- find_invigilators / assign_invigilators_for_exam ---

MONDAY = 0
EXAM_CLASS = 999
OTHER_CLASS = 1


def _candidate(teacher_id, busy=frozenset(), on_leave=False, workload=0):
    return InvigilatorCandidate(teacher_id=teacher_id, busy_ranges=busy, on_leave=on_leave, current_invigilation_count=workload)


def _find(candidates, **kwargs):
    return find_invigilators(day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0), candidates=candidates, exam_class_id=EXAM_CLASS, **kwargs)


def test_available_candidate_is_eligible():
    suggestions = _find([_candidate(1)])
    assert len(suggestions) == 1
    assert suggestions[0].teacher_id == 1


def test_teacher_busy_teaching_a_different_classs_overlapping_slot_is_excluded():
    busy = frozenset({TimeRange(day_of_week=MONDAY, start_time=time(10, 0), end_time=time(10, 45), class_id=OTHER_CLASS)})
    candidates = [_candidate(1, busy=busy)]
    # exam runs 9:00-11:00, overlaps the 10:00-10:45 teaching slot - but for a
    # DIFFERENT class, so it's a genuine conflict.
    assert _find(candidates) == []


def test_teacher_busy_teaching_the_exams_own_class_at_this_slot_is_not_excluded():
    """Regression: this teacher's "conflict" is teaching the exact class taking
    the exam, at the exact exam time - that period IS the exam, so they're
    actually free then, not busy. Previously wrongly excluded."""
    busy = frozenset({TimeRange(day_of_week=MONDAY, start_time=time(10, 0), end_time=time(10, 45), class_id=EXAM_CLASS)})
    candidates = [_candidate(1, busy=busy)]
    suggestions = _find(candidates)
    assert len(suggestions) == 1
    assert suggestions[0].teacher_id == 1


def test_teacher_busy_on_a_different_day_is_not_excluded():
    busy = frozenset({TimeRange(day_of_week=1, start_time=time(10, 0), end_time=time(10, 45), class_id=OTHER_CLASS)})  # Tuesday
    candidates = [_candidate(1, busy=busy)]
    assert len(_find(candidates)) == 1


def test_teacher_with_non_overlapping_slot_same_day_is_not_excluded():
    busy = frozenset({TimeRange(day_of_week=MONDAY, start_time=time(13, 0), end_time=time(13, 45), class_id=OTHER_CLASS)})  # afternoon
    candidates = [_candidate(1, busy=busy)]
    assert len(_find(candidates)) == 1


def test_teacher_on_leave_is_excluded():
    assert _find([_candidate(1, on_leave=True)]) == []


def test_already_assigned_teacher_is_excluded():
    suggestions = _find([_candidate(1)], already_assigned_teacher_ids=frozenset({1}))
    assert suggestions == []


def test_lower_workload_candidate_ranks_higher():
    candidates = [_candidate(1, workload=5), _candidate(2, workload=0)]
    suggestions = _find(candidates)
    assert suggestions[0].teacher_id == 2  # lower workload wins


def test_no_eligible_candidates_returns_empty_not_error():
    assert _find([_candidate(1, on_leave=True), _candidate(2, on_leave=True)]) == []


def test_assign_invigilators_for_exam_never_double_books_across_rooms():
    candidates = [_candidate(1), _candidate(2)]
    assigned = assign_invigilators_for_exam(
        room_ids=[100, 101], day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0),
        candidates=candidates, exam_class_id=EXAM_CLASS,
    )
    assert len(assigned) == 2
    assigned_teachers = [t for t in assigned.values() if t is not None]
    assert len(assigned_teachers) == len(set(assigned_teachers))  # no duplicate teacher across rooms


def test_assign_invigilators_for_exam_surfaces_unassigned_room_honestly():
    candidates = [_candidate(1)]  # only one eligible teacher for two rooms
    assigned = assign_invigilators_for_exam(
        room_ids=[100, 101], day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0),
        candidates=candidates, exam_class_id=EXAM_CLASS,
    )
    assert list(assigned.values()).count(None) == 1
    assert list(assigned.values()).count(1) == 1


# --- 3-tier priority: preferred (regular class teacher) > normal > deprioritized (subject teacher) ---


def test_preferred_teacher_is_chosen_over_an_equally_free_normal_candidate():
    candidates = [_candidate(1), _candidate(2)]  # both otherwise identical/free
    suggestions = _find(candidates, preferred_teacher_ids=frozenset({2}))
    assert suggestions[0].teacher_id == 2
    assert "regularly teaches this class" in suggestions[0].reason


def test_preferred_teacher_wins_even_with_higher_workload_than_a_normal_candidate():
    """Real school practice: the regular class teacher is picked FIRST, not just
    ranked slightly higher - workload only breaks ties WITHIN a tier."""
    candidates = [_candidate(1, workload=0), _candidate(2, workload=10)]
    suggestions = _find(candidates, preferred_teacher_ids=frozenset({2}))
    assert suggestions[0].teacher_id == 2


def test_subject_teacher_is_never_chosen_while_any_other_candidate_is_free():
    candidates = [_candidate(1), _candidate(2)]
    suggestions = _find(candidates, deprioritized_teacher_ids=frozenset({2}))
    assert suggestions[0].teacher_id == 1
    assert "same-subject" not in suggestions[0].reason


def test_subject_teacher_is_used_as_a_last_resort_when_nobody_else_is_eligible():
    candidates = [_candidate(1, on_leave=True), _candidate(2)]  # only the subject teacher is even available
    suggestions = _find(candidates, deprioritized_teacher_ids=frozenset({2}))
    assert len(suggestions) == 1
    assert suggestions[0].teacher_id == 2
    assert "same-subject teacher, last resort" in suggestions[0].reason


def test_subject_exclusion_wins_over_preferred_when_a_candidate_is_both():
    """A teacher whose regular slot for this class happens to BE this exam's own
    subject must still be treated as last-resort, not preferred - the bias
    concern is about the subject match, regardless of scheduling convenience."""
    candidates = [_candidate(1), _candidate(2)]
    suggestions = _find(candidates, preferred_teacher_ids=frozenset({2}), deprioritized_teacher_ids=frozenset({2}))
    assert suggestions[0].teacher_id == 1  # the other free candidate, not the conflicted "preferred" one


def test_assign_invigilators_for_exam_passes_through_tier_preferences():
    candidates = [_candidate(1), _candidate(2)]
    assigned = assign_invigilators_for_exam(
        room_ids=[100], day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0),
        candidates=candidates, exam_class_id=EXAM_CLASS, preferred_teacher_ids=frozenset({2}),
    )
    assert assigned[100] == 2
