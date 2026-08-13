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


# --- find_invigilators / assign_invigilators_for_exam ---

MONDAY = 0


def _candidate(teacher_id, busy=frozenset(), on_leave=False, workload=0):
    return InvigilatorCandidate(teacher_id=teacher_id, busy_ranges=busy, on_leave=on_leave, current_invigilation_count=workload)


def test_available_candidate_is_eligible():
    candidates = [_candidate(1)]
    suggestions = find_invigilators(day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0), candidates=candidates)
    assert len(suggestions) == 1
    assert suggestions[0].teacher_id == 1


def test_teacher_busy_teaching_overlapping_slot_is_excluded():
    busy = frozenset({TimeRange(day_of_week=MONDAY, start_time=time(10, 0), end_time=time(10, 45))})
    candidates = [_candidate(1, busy=busy)]
    # exam runs 9:00-11:00, overlaps the 10:00-10:45 teaching slot
    suggestions = find_invigilators(day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0), candidates=candidates)
    assert suggestions == []


def test_teacher_busy_on_a_different_day_is_not_excluded():
    busy = frozenset({TimeRange(day_of_week=1, start_time=time(10, 0), end_time=time(10, 45))})  # Tuesday
    candidates = [_candidate(1, busy=busy)]
    suggestions = find_invigilators(day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0), candidates=candidates)
    assert len(suggestions) == 1


def test_teacher_with_non_overlapping_slot_same_day_is_not_excluded():
    busy = frozenset({TimeRange(day_of_week=MONDAY, start_time=time(13, 0), end_time=time(13, 45))})  # afternoon
    candidates = [_candidate(1, busy=busy)]
    suggestions = find_invigilators(day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0), candidates=candidates)
    assert len(suggestions) == 1


def test_teacher_on_leave_is_excluded():
    candidates = [_candidate(1, on_leave=True)]
    suggestions = find_invigilators(day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0), candidates=candidates)
    assert suggestions == []


def test_already_assigned_teacher_is_excluded():
    candidates = [_candidate(1)]
    suggestions = find_invigilators(
        day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0), candidates=candidates,
        already_assigned_teacher_ids=frozenset({1}),
    )
    assert suggestions == []


def test_lower_workload_candidate_ranks_higher():
    candidates = [_candidate(1, workload=5), _candidate(2, workload=0)]
    suggestions = find_invigilators(day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0), candidates=candidates)
    assert suggestions[0].teacher_id == 2  # lower workload wins


def test_no_eligible_candidates_returns_empty_not_error():
    candidates = [_candidate(1, on_leave=True), _candidate(2, on_leave=True)]
    suggestions = find_invigilators(day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0), candidates=candidates)
    assert suggestions == []


def test_assign_invigilators_for_exam_never_double_books_across_rooms():
    candidates = [_candidate(1), _candidate(2)]
    assigned = assign_invigilators_for_exam(room_ids=[100, 101], day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0), candidates=candidates)
    assert len(assigned) == 2
    assigned_teachers = [t for t in assigned.values() if t is not None]
    assert len(assigned_teachers) == len(set(assigned_teachers))  # no duplicate teacher across rooms


def test_assign_invigilators_for_exam_surfaces_unassigned_room_honestly():
    candidates = [_candidate(1)]  # only one eligible teacher for two rooms
    assigned = assign_invigilators_for_exam(room_ids=[100, 101], day_of_week=MONDAY, start_time=time(9, 0), end_time=time(11, 0), candidates=candidates)
    assert list(assigned.values()).count(None) == 1
    assert list(assigned.values()).count(1) == 1
