"""Exam seating and invigilation scheduling.

SEATING - a straightforward bin-fill, deliberately NOT a CP-SAT problem
------------------------------------------------------------------------------
Assigning students to seats across a fixed set of (room, capacity) pairs has no
interesting constraints beyond "each student gets exactly one seat, no room exceeds
its capacity" - a deterministic greedy fill (rooms in the order given, seats 1..N)
satisfies both trivially and optimally. Using a full CP-SAT model here, the way
timetable_solver.py does for its genuinely combinatorial problem, would be
over-engineering for a problem with no competing objective and no interesting
constraint (there's no seating-adjacency/anti-cheating rule in scope) - search
machinery bought at zero benefit. Raises InsufficientCapacityError rather than
silently overflowing a room or dropping a student.

INVIGILATION - adapted from substitute_solver.py's filter+rank shape, not
timetable_solver's CSP
------------------------------------------------------------------------------------
Per this session's own framing: assigning a qualified/free teacher to a slot is
substitute_solver.py's exact problem shape, just for exam rooms instead of covering
an absent teacher's class. Adapted rather than reused verbatim, because the
constraints genuinely differ:
  - No subject-qualification filter: any teacher can invigilate an exam regardless
    of what subject they teach - unlike substituting, where the sub must be
    qualified in the SAME subject as the class being covered.
  - "Already busy" is a real TIME-RANGE overlap check against TimetableSlot, not an
    exact (day, period) match: an exam's start_time/end_time may span multiple
    regular periods or fall inside one - a candidate is unavailable if any of their
    slots on that weekday overlaps the exam's time range at all.
  - "On leave" checks LeaveRequest for the exam_date, same idea as
    substitute_solver.py.
  - A constraint substitute_solver.py didn't need: a teacher already assigned to
    invigilate ANOTHER room of the SAME exam (necessarily at the identical time)
    can't also invigilate this one - enforced by excluding already-assigned
    candidates as assign_invigilators_for_exam() processes rooms in sequence, not a
    separate CP-SAT constraint (no combinatorial search is needed for this either -
    a single pass suffices since every room's invigilator only needs to avoid
    teachers already claimed by an earlier room in the SAME pass).
Ranking: the same workload-balance idea as substitute_solver.py (fewer existing
invigilation duties scores higher) - a fresh implementation, not shared code,
because the input shape (TimeRange overlap vs. exact slot match) is different enough
that sharing would mean threading an awkward abstraction through both for no benefit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time as time_

BASE_SCORE = 0.7
"""Every eligible (hard-filter-passing) invigilator candidate starts here - same
constant value as substitute_solver.py's, not because the code is shared, but
because the underlying idea (a flat base plus a workload-balance bonus) is the same
philosophy applied to a different problem."""
MAX_WORKLOAD_BONUS = 0.3


class InsufficientCapacityError(Exception):
    """Raised when total room capacity can't seat every student - an honest failure,
    not a silent overflow or dropped student."""


# --- seating -------------------------------------------------------------------------


@dataclass(frozen=True)
class RoomCapacity:
    room_id: int
    capacity: int


@dataclass(frozen=True)
class SeatAssignment:
    student_id: int
    room_id: int
    seat_no: int
    """1-indexed within its room."""


def generate_seating(student_ids: list[int], rooms: list[RoomCapacity]) -> list[SeatAssignment]:
    total_capacity = sum(r.capacity for r in rooms)
    if total_capacity < len(student_ids):
        raise InsufficientCapacityError(
            f"{len(student_ids)} students need seating but only {total_capacity} seats are available across {len(rooms)} room(s)"
        )

    assignments: list[SeatAssignment] = []
    student_iter = iter(student_ids)
    for room in rooms:
        for seat_no in range(1, room.capacity + 1):
            student_id = next(student_iter, None)
            if student_id is None:
                break
            assignments.append(SeatAssignment(student_id=student_id, room_id=room.room_id, seat_no=seat_no))
    return assignments


# --- invigilation ----------------------------------------------------------------------


@dataclass(frozen=True)
class TimeRange:
    day_of_week: int
    """0 = Monday ... 6 = Sunday - matches TimetableSlot's convention."""
    start_time: time_
    end_time: time_


def _overlaps(a_start: time_, a_end: time_, b_start: time_, b_end: time_) -> bool:
    return a_start < b_end and b_start < a_end


@dataclass(frozen=True)
class InvigilatorCandidate:
    teacher_id: int
    busy_ranges: frozenset[TimeRange]
    """This teacher's real, currently-active TimetableSlot occupied ranges."""
    on_leave: bool
    """Has an approved LeaveRequest covering the exam_date."""
    current_invigilation_count: int
    """How many InvigilationAssignments this teacher already has this term - lower
    is preferred as a tiebreak, same workload-spreading idea as
    substitute_solver.py's current_workload."""


@dataclass(frozen=True)
class InvigilatorSuggestion:
    teacher_id: int
    score: float
    reason: str


def _is_available(candidate: InvigilatorCandidate, day_of_week: int, start_time: time_, end_time: time_) -> bool:
    if candidate.on_leave:
        return False
    return not any(
        busy.day_of_week == day_of_week and _overlaps(busy.start_time, busy.end_time, start_time, end_time)
        for busy in candidate.busy_ranges
    )


def find_invigilators(
    *,
    day_of_week: int,
    start_time: time_,
    end_time: time_,
    candidates: list[InvigilatorCandidate],
    already_assigned_teacher_ids: frozenset[int] = frozenset(),
    max_results: int = 3,
) -> list[InvigilatorSuggestion]:
    eligible = [
        c
        for c in candidates
        if c.teacher_id not in already_assigned_teacher_ids and _is_available(c, day_of_week, start_time, end_time)
    ]
    if not eligible:
        return []

    max_workload = max(c.current_invigilation_count for c in eligible)
    suggestions = []
    for c in eligible:
        ratio = (c.current_invigilation_count / max_workload) if max_workload else 0.0
        bonus = MAX_WORKLOAD_BONUS * (1.0 - ratio)
        score = round(BASE_SCORE + bonus, 3)
        suggestions.append(
            InvigilatorSuggestion(
                teacher_id=c.teacher_id, score=score,
                reason=f"available, current invigilation load {c.current_invigilation_count}",
            )
        )

    suggestions.sort(key=lambda s: -s.score)
    return suggestions[:max_results]


def assign_invigilators_for_exam(
    *,
    room_ids: list[int],
    day_of_week: int,
    start_time: time_,
    end_time: time_,
    candidates: list[InvigilatorCandidate],
) -> dict[int, int | None]:
    """One invigilator per room, no teacher double-booked across the exam's own
    rooms (they're all at the identical day/time by definition). Returns
    {room_id: teacher_id}, or {room_id: None} for a room where no eligible
    candidate remained - an honest gap, not silently dropped. Callers (see
    routers/exams.py) surface any None directly in the generation response rather
    than pretending every room got covered."""
    assigned: dict[int, int | None] = {}
    already_assigned: set[int] = set()
    for room_id in room_ids:
        suggestions = find_invigilators(
            day_of_week=day_of_week, start_time=start_time, end_time=end_time,
            candidates=candidates, already_assigned_teacher_ids=frozenset(already_assigned), max_results=1,
        )
        if suggestions:
            assigned[room_id] = suggestions[0].teacher_id
            already_assigned.add(suggestions[0].teacher_id)
        else:
            assigned[room_id] = None
    return assigned
