"""CP-SAT constraint-satisfaction solver for timetable generation.

Deliberately decoupled from the ORM: callers (the API layer, tests, ad-hoc
scripts) build plain dataclasses describing the problem and get back plain
dataclasses describing the schedule. This keeps the solver runnable and
testable without a database.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class SolverTeacher:
    id: int
    subject_ids: frozenset[int]
    """Subjects this teacher is qualified/available to teach."""
    unavailable: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    """Set of (day_of_week, period_number) the teacher cannot be scheduled in."""


@dataclass(frozen=True)
class SolverRoom:
    id: int
    room_type: str = "classroom"


@dataclass(frozen=True)
class SolverSubject:
    id: int
    required_room_type: str | None = None
    """If set, periods of this subject may only use rooms with a matching room_type."""


@dataclass(frozen=True)
class SolverRequirement:
    """A class needs `periods_per_week` periods of `subject_id` scheduled."""

    class_id: int
    subject_id: int
    periods_per_week: int


@dataclass(frozen=True)
class ScheduledSlot:
    class_id: int
    subject_id: int
    teacher_id: int
    room_id: int
    day_of_week: int
    period_number: int


class UnsolvableError(Exception):
    """Raised when no feasible schedule exists for the given input (either the CP-SAT
    model proved infeasibility, or a requirement has no eligible teacher/room at all)."""


def generate_timetable(
    *,
    teachers: list[SolverTeacher],
    rooms: list[SolverRoom],
    subjects: list[SolverSubject],
    requirements: list[SolverRequirement],
    days: int = 5,
    periods_per_day: int = 6,
    time_limit_seconds: float = 30.0,
) -> list[ScheduledSlot]:
    """Assign each requirement's periods to a (teacher, room, day, period) such that
    no teacher, room, or class is double-booked in the same period. Raises
    UnsolvableError if no such assignment exists."""

    subjects_by_id = {s.id: s for s in subjects}
    day_periods = [(d, p) for d in range(days) for p in range(periods_per_day)]

    model = cp_model.CpModel()

    # x[(req_idx, teacher_id, room_id, day, period)] = 1 if that requirement's
    # period is scheduled with that teacher, in that room, at that day/period.
    x: dict[tuple[int, int, int, int, int], cp_model.IntVar] = {}

    vars_by_req: dict[int, list[cp_model.IntVar]] = defaultdict(list)
    vars_by_req_dp: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_teacher_dp: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_room_dp: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_class_dp: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)

    for req_idx, req in enumerate(requirements):
        if req.subject_id not in subjects_by_id:
            raise UnsolvableError(f"Unknown subject_id {req.subject_id} in requirement for class {req.class_id}")
        subject = subjects_by_id[req.subject_id]

        eligible_teachers = [t for t in teachers if req.subject_id in t.subject_ids]
        if not eligible_teachers:
            raise UnsolvableError(f"No teacher qualified for subject {req.subject_id} (class {req.class_id})")

        eligible_rooms = [
            r for r in rooms if subject.required_room_type is None or r.room_type == subject.required_room_type
        ]
        if not eligible_rooms:
            raise UnsolvableError(f"No room of type '{subject.required_room_type}' for subject {req.subject_id}")

        for teacher in eligible_teachers:
            for room in eligible_rooms:
                for day, period in day_periods:
                    if (day, period) in teacher.unavailable:
                        continue
                    var = model.NewBoolVar(f"x_r{req_idx}_t{teacher.id}_rm{room.id}_d{day}_p{period}")
                    x[(req_idx, teacher.id, room.id, day, period)] = var
                    vars_by_req[req_idx].append(var)
                    vars_by_req_dp[(req_idx, day, period)].append(var)
                    vars_by_teacher_dp[(teacher.id, day, period)].append(var)
                    vars_by_room_dp[(room.id, day, period)].append(var)
                    vars_by_class_dp[(req.class_id, day, period)].append(var)

        if not vars_by_req[req_idx]:
            raise UnsolvableError(
                f"No feasible teacher/room/time combination for class {req.class_id}, subject {req.subject_id} "
                "(likely every qualified teacher is unavailable at every period)"
            )

        # Exactly the required number of periods/week for this class-subject pair.
        model.Add(sum(vars_by_req[req_idx]) == req.periods_per_week)

    # A single requirement can occupy a given day/period at most once (guards against
    # scheduling the same class-subject pair twice in one period when periods_per_week
    # spans more slots than one day offers).
    for req_dp_vars in vars_by_req_dp.values():
        model.Add(sum(req_dp_vars) <= 1)

    # Hard constraint: no teacher double-booked in the same period.
    for dp_vars in vars_by_teacher_dp.values():
        model.Add(sum(dp_vars) <= 1)

    # Hard constraint: no room double-booked in the same period.
    for dp_vars in vars_by_room_dp.values():
        model.Add(sum(dp_vars) <= 1)

    # Hard constraint: no class double-booked in the same period.
    for dp_vars in vars_by_class_dp.values():
        model.Add(sum(dp_vars) <= 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise UnsolvableError("No feasible timetable exists for the given teachers/rooms/requirements")

    schedule = []
    for (req_idx, teacher_id, room_id, day, period), var in x.items():
        if solver.Value(var):
            req = requirements[req_idx]
            schedule.append(
                ScheduledSlot(
                    class_id=req.class_id,
                    subject_id=req.subject_id,
                    teacher_id=teacher_id,
                    room_id=room_id,
                    day_of_week=day,
                    period_number=period,
                )
            )
    return schedule
