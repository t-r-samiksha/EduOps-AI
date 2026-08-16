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
  - No subject-qualification HARD filter (unlike substituting, where the sub must
    be qualified in the SAME subject as the class being covered) - but subject
    DOES now soft-influence ranking, see the 3-tier priority below.
  - "Already busy" is a real TIME-RANGE overlap check against TimetableSlot, not an
    exact (day, period) match: an exam's start_time/end_time may span multiple
    regular periods or fall inside one - a candidate is unavailable if any of their
    slots on that weekday overlaps the exam's time range at all. EXCEPT: a slot for
    the exam's OWN class doesn't count as a conflict (see TimeRange.class_id) -
    that period is being replaced BY the exam, so its regular teacher is actually
    free then, not busy.
  - "On leave" checks LeaveRequest for the exam_date, same idea as
    substitute_solver.py.
  - A constraint substitute_solver.py didn't need: a teacher already assigned to
    invigilate ANOTHER room of the SAME exam (necessarily at the identical time)
    can't also invigilate this one - enforced by excluding already-assigned
    candidates as assign_invigilators_for_exam() processes rooms in sequence, not a
    separate CP-SAT constraint (no combinatorial search is needed for this either -
    a single pass suffices since every room's invigilator only needs to avoid
    teachers already claimed by an earlier room in the SAME pass).

3-TIER PRIORITY (added this session, real school practice, not just "least loaded
wins"): among candidates who pass the hard filters above (available, not on leave,
not already claimed this run), find_invigilators() tries, in order:
  1. preferred_teacher_ids - whoever normally teaches THIS exact class at this
     exact slot (any subject) - the natural pick, no scheduling churn for them.
  2. Anyone else free, ranked by workload (today's original behavior).
  3. deprioritized_teacher_ids - whoever normally teaches this exam's OWN subject
     to this class - last resort only, to avoid a subject teacher invigilating
     their own subject's test. This wins over tier 1 if a candidate is in both
     (e.g. their regular slot for this class happens to BE this subject) - the
     bias concern applies regardless of why they'd otherwise be convenient.
The first non-empty tier is used; workload-ranking (below) applies within
whichever tier fires.

Ranking within a tier: the same workload-balance idea as substitute_solver.py
(fewer existing invigilation duties scores higher) - a fresh implementation, not
shared code, because the input shape (TimeRange overlap vs. exact slot match) is
different enough that sharing would mean threading an awkward abstraction through
both for no benefit.
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


def suggest_rooms(available_rooms: list[RoomCapacity], headcount: int) -> list[RoomCapacity]:
    """Picks a real subset of the given (already-availability-filtered) rooms that
    covers headcount, minimizing both room count and wasted seats: prefers the
    single smallest room that fits everyone; falls back to combining rooms
    largest-first until capacity is met. A suggestion for the caller to accept or
    override, not a forced choice - see routers/exams.py's room-suggestions
    endpoint, which returns this alongside every other available room."""
    if headcount <= 0:
        return []

    fitting_single = [r for r in available_rooms if r.capacity >= headcount]
    if fitting_single:
        return [min(fitting_single, key=lambda r: r.capacity)]

    chosen: list[RoomCapacity] = []
    total = 0
    for room in sorted(available_rooms, key=lambda r: -r.capacity):
        if total >= headcount:
            break
        chosen.append(room)
        total += room.capacity
    return chosen


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
    class_id: int
    """Which class this busy slot belongs to. A slot for the SAME class as the
    exam being scheduled is NOT a real conflict - that period IS the exam, so the
    teacher who'd normally have it is actually free then, not busy. Only a slot
    for a DIFFERENT class blocks a candidate. See _is_available()."""


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


def _is_available(candidate: InvigilatorCandidate, day_of_week: int, start_time: time_, end_time: time_, exam_class_id: int) -> bool:
    if candidate.on_leave:
        return False
    return not any(
        busy.day_of_week == day_of_week and busy.class_id != exam_class_id and _overlaps(busy.start_time, busy.end_time, start_time, end_time)
        for busy in candidate.busy_ranges
    )


def _rank(eligible: list[InvigilatorCandidate], reason_suffix: str) -> list[InvigilatorSuggestion]:
    max_workload = max(c.current_invigilation_count for c in eligible)
    suggestions = []
    for c in eligible:
        ratio = (c.current_invigilation_count / max_workload) if max_workload else 0.0
        bonus = MAX_WORKLOAD_BONUS * (1.0 - ratio)
        score = round(BASE_SCORE + bonus, 3)
        suggestions.append(
            InvigilatorSuggestion(
                teacher_id=c.teacher_id, score=score,
                reason=f"available, current invigilation load {c.current_invigilation_count}{reason_suffix}",
            )
        )
    suggestions.sort(key=lambda s: -s.score)
    return suggestions


def find_invigilators(
    *,
    day_of_week: int,
    start_time: time_,
    end_time: time_,
    candidates: list[InvigilatorCandidate],
    exam_class_id: int,
    already_assigned_teacher_ids: frozenset[int] = frozenset(),
    # Teachers who normally have THIS exact class at this exact day/time slot -
    # the natural first choice, since they were already going to be with this
    # class then; the exam just replaces what would've been their regular period.
    preferred_teacher_ids: frozenset[int] = frozenset(),
    # Teachers who normally teach this exam's own subject to this exact class -
    # the last resort, to avoid a subject teacher invigilating their own
    # subject's test unless truly nobody else is available. Wins over
    # preferred_teacher_ids if a candidate is in both (e.g. their regular slot
    # for this class happens to BE this subject) - the subject exclusion is
    # about avoiding bias, not logistics.
    deprioritized_teacher_ids: frozenset[int] = frozenset(),
    max_results: int = 3,
) -> list[InvigilatorSuggestion]:
    eligible = [
        c
        for c in candidates
        if c.teacher_id not in already_assigned_teacher_ids and _is_available(c, day_of_week, start_time, end_time, exam_class_id)
    ]
    if not eligible:
        return []

    preferred = [c for c in eligible if c.teacher_id in preferred_teacher_ids and c.teacher_id not in deprioritized_teacher_ids]
    if preferred:
        return _rank(preferred, " - regularly teaches this class then")[:max_results]

    normal = [c for c in eligible if c.teacher_id not in preferred_teacher_ids and c.teacher_id not in deprioritized_teacher_ids]
    if normal:
        return _rank(normal, "")[:max_results]

    last_resort = [c for c in eligible if c.teacher_id in deprioritized_teacher_ids]
    if last_resort:
        return _rank(last_resort, " - same-subject teacher, last resort")[:max_results]

    return []


def assign_invigilators_for_exam(
    *,
    room_ids: list[int],
    day_of_week: int,
    start_time: time_,
    end_time: time_,
    candidates: list[InvigilatorCandidate],
    exam_class_id: int,
    preferred_teacher_ids: frozenset[int] = frozenset(),
    deprioritized_teacher_ids: frozenset[int] = frozenset(),
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
            candidates=candidates, exam_class_id=exam_class_id, already_assigned_teacher_ids=frozenset(already_assigned),
            preferred_teacher_ids=preferred_teacher_ids, deprioritized_teacher_ids=deprioritized_teacher_ids, max_results=1,
        )
        if suggestions:
            assigned[room_id] = suggestions[0].teacher_id
            already_assigned.add(suggestions[0].teacher_id)
        else:
            assigned[room_id] = None
    return assigned
