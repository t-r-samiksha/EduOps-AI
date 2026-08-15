"""CP-SAT constraint-satisfaction solver for timetable generation.

Deliberately decoupled from the ORM: callers (the API layer, tests, ad-hoc
scripts) build plain dataclasses describing the problem and get back plain
dataclasses describing the schedule. This keeps the solver runnable and
testable without a database.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

logger = logging.getLogger("eduops.timetable_solver")


@dataclass(frozen=True)
class SolverTeacher:
    id: int
    subject_ids: frozenset[int]
    """Subjects this teacher is qualified/available to teach."""
    unavailable: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    """Set of (day_of_week, period_number) the teacher cannot be scheduled in."""
    max_periods_per_week: int | None = None
    """Hard cap on this teacher's TOTAL assigned periods across the whole week,
    summed across every class/subject they're assigned to - not per-day, per
    subject, or per class. None means uncapped (no constraint added for this
    teacher)."""


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
    home_room_id: int | None = None
    """This class's designated homeroom (SchoolClass.home_room_id). Only
    consulted when the subject itself has no required_room_type (a lab-
    required subject always freely chooses among lab-type rooms regardless of
    this field) - forces every non-lab period for this requirement into this
    one room, a hard constraint, not a preference. None means "not configured"
    - falls back to free choice among every room passed to the solver, and
    the caller is expected to warn the admin about it (see generate_timetable's
    `warnings` return value)."""


@dataclass(frozen=True)
class ScheduledSlot:
    class_id: int
    subject_id: int
    teacher_id: int
    room_id: int
    day_of_week: int
    period_number: int


@dataclass(frozen=True)
class GenerationResult:
    slots: list[ScheduledSlot]
    warnings: list[str]
    """Non-fatal configuration gaps found while building this run - e.g. a
    class with no home_room_id, whose non-lab periods therefore got today's
    old free-choice-among-all-rooms behavior instead of being pinned."""
    objective_weights: dict[str, int]
    """The two soft-preference terms' weights, by name, as actually used for
    this run - reported so the weights can be tuned later without having to
    read this module's source to find them."""
    objective_values: dict[str, int]
    """Each term's actual achieved value at the returned solution (0 is
    perfect - no clustering / no day-to-day variance at all)."""


class UnsolvableError(Exception):
    """Raised when no feasible schedule exists for the given input (either the CP-SAT
    model proved infeasibility, or a requirement has no eligible teacher/room at all)."""


@dataclass(frozen=True)
class InfeasibilityFinding:
    """The result of diagnose_infeasibility - names the SPECIFIC requirements
    CP-SAT's own infeasibility core says are in conflict, not a generic
    message. requirement_indices is empty when the core couldn't be
    isolated or mapped (see diagnose_infeasibility's docstring)."""

    code: str
    message: str
    requirement_indices: list[int]
    details: dict


# Same-subject-same-day clustering is penalized far more heavily than uneven
# day-to-day totals - "English three times on Monday" is a much worse outcome
# than "Monday has 6 periods and Friday has 5", so clustering must dominate
# the objective whenever the two preferences trade off against each other.
_SAME_DAY_CLUSTERING_WEIGHT = 1000
_DAY_VARIANCE_WEIGHT = 1

# Fixed so repeated runs against the same input are comparable (see this
# function's own docstring for the num_search_workers caveat - a fixed seed
# does NOT by itself guarantee bit-for-bit identical output when multiple
# search workers race each other).
_RANDOM_SEED = 42


def generate_timetable(
    *,
    teachers: list[SolverTeacher],
    rooms: list[SolverRoom],
    subjects: list[SolverSubject],
    requirements: list[SolverRequirement],
    days: int = 5,
    periods_per_day: int = 6,
    time_limit_seconds: float = 30.0,
) -> GenerationResult:
    """Assign each requirement's periods to a (teacher, room, day, period) such that
    no teacher, room, or class is double-booked in the same period, every non-lab
    requirement stays in its class's home room (when configured), and same-subject
    same-day clustering / day-to-day load variance are minimized as soft
    preferences. Raises UnsolvableError if no feasible assignment exists at all
    (the hard constraints, not the soft preferences, are what can make a run
    infeasible).

    Reproducibility note: `solver.parameters.random_seed` is fixed, but CP-SAT's
    `num_search_workers` runs several search strategies in parallel and returns
    whichever proves/finds a solution first - with more than one worker, that
    race is real wall-clock-timing-dependent, so a fixed seed alone does not
    guarantee identical output run-to-run. Only `num_search_workers=1` gives
    true determinism (at a real cost to solve time on larger inputs)."""

    subjects_by_id = {s.id: s for s in subjects}
    rooms_by_id = {r.id: r for r in rooms}
    day_periods = [(d, p) for d in range(days) for p in range(periods_per_day)]
    class_ids = sorted({req.class_id for req in requirements})

    # Logged BEFORE any variable/constraint is built, so a requirement that
    # never reaches the solver (dropped/rewritten upstream in the router) is
    # distinguishable from one that reaches it but can't be satisfied for a
    # real availability reason.
    logger.info(
        "generate_timetable called: days=%s periods_per_day=%s teachers=%d rooms=%d subjects=%d requirements=%d",
        days, periods_per_day, len(teachers), len(rooms), len(subjects), len(requirements),
    )
    for req in requirements:
        logger.info(
            "  SolverRequirement(class_id=%s, subject_id=%s, periods_per_week=%s, home_room_id=%s)",
            req.class_id, req.subject_id, req.periods_per_week, req.home_room_id,
        )

    model = cp_model.CpModel()

    # x[(req_idx, teacher_id, room_id, day, period)] = 1 if that requirement's
    # period is scheduled with that teacher, in that room, at that day/period.
    x: dict[tuple[int, int, int, int, int], cp_model.IntVar] = {}

    vars_by_req: dict[int, list[cp_model.IntVar]] = defaultdict(list)
    vars_by_req_dp: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_req_day: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    """All of one requirement's vars for one day, across every period that day -
    used for the same-subject-same-day cap/clustering objective below."""
    vars_by_teacher_dp: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_room_dp: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_class_dp: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_class_day: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    """All of one class's vars (any subject) for one day - used for the
    day-to-day load variance objective below."""
    vars_by_teacher: dict[int, list[cp_model.IntVar]] = defaultdict(list)
    """All of a teacher's assignment vars across every day/period/room/requirement -
    unlike vars_by_teacher_dp, NOT keyed by day/period, so summing one teacher's
    entries directly gives their total assigned periods for the whole week."""

    warnings: list[str] = []
    _homeroom_warned: set[int] = set()

    cap_by_req: dict[int, int] = {}

    for req_idx, req in enumerate(requirements):
        if req.subject_id not in subjects_by_id:
            raise UnsolvableError(f"Unknown subject_id {req.subject_id} in requirement for class {req.class_id}")
        subject = subjects_by_id[req.subject_id]

        eligible_teachers = [t for t in teachers if req.subject_id in t.subject_ids]
        if not eligible_teachers:
            raise UnsolvableError(f"No teacher qualified for subject {req.subject_id} (class {req.class_id})")
        total_day_periods = len(day_periods)
        for t in eligible_teachers:
            free = total_day_periods - sum(1 for dp in day_periods if dp in t.unavailable)
            logger.info(
                "  eligible teacher for subject_id=%s (class_id=%s): teacher_id=%s free_slots=%d/%d max_periods_per_week=%s",
                req.subject_id, req.class_id, t.id, free, total_day_periods, t.max_periods_per_week,
            )

        # Room eligibility: a lab-required subject always freely chooses among
        # lab-type rooms (unchanged - that part was never the bug). Everything
        # else is now PINNED to the class's home_room_id as a hard constraint,
        # not left to free choice among every non-lab room, unless the class
        # genuinely has no home_room_id configured (a real, warned-about gap,
        # not a silent one).
        if subject.required_room_type is not None:
            eligible_rooms = [r for r in rooms if r.room_type == subject.required_room_type]
            if not eligible_rooms:
                raise UnsolvableError(f"No room of type '{subject.required_room_type}' for subject {req.subject_id}")
        elif req.home_room_id is not None:
            if req.home_room_id not in rooms_by_id:
                raise UnsolvableError(
                    f"Class {req.class_id}'s home_room_id {req.home_room_id} is not among the rooms "
                    "selected for this run"
                )
            eligible_rooms = [rooms_by_id[req.home_room_id]]
        else:
            if req.class_id not in _homeroom_warned:
                _homeroom_warned.add(req.class_id)
                warnings.append(
                    f"Class {req.class_id} has no home_room_id configured - its non-lab periods may be "
                    "assigned to different rooms across the week. Set a home room for it in School "
                    "Management's Classes tab to pin it."
                )
            eligible_rooms = list(rooms)

        for teacher in eligible_teachers:
            for room in eligible_rooms:
                for day, period in day_periods:
                    if (day, period) in teacher.unavailable:
                        continue
                    var = model.NewBoolVar(f"x_r{req_idx}_t{teacher.id}_rm{room.id}_d{day}_p{period}")
                    x[(req_idx, teacher.id, room.id, day, period)] = var
                    vars_by_req[req_idx].append(var)
                    vars_by_req_dp[(req_idx, day, period)].append(var)
                    vars_by_req_day[(req_idx, day)].append(var)
                    vars_by_teacher_dp[(teacher.id, day, period)].append(var)
                    vars_by_room_dp[(room.id, day, period)].append(var)
                    vars_by_class_dp[(req.class_id, day, period)].append(var)
                    vars_by_class_day[(req.class_id, day)].append(var)
                    vars_by_teacher[teacher.id].append(var)

        if not vars_by_req[req_idx]:
            raise UnsolvableError(
                f"No feasible teacher/room/time combination for class {req.class_id}, subject {req.subject_id} "
                "(likely every qualified teacher is unavailable at every period)"
            )

        # Exactly the required number of periods/week for this class-subject pair.
        model.Add(sum(vars_by_req[req_idx]) == req.periods_per_week)

        # The tightest per-day cap that still leaves periods_per_week feasible
        # across `days` days - 1 whenever periods_per_week fits within the
        # week (the common case: every subject appears at most once per day),
        # only rising above 1 when the numbers genuinely force it (e.g. 8
        # periods/week on a 5-day week needs at least ceil(8/5)=2 on 3 days).
        cap_by_req[req_idx] = max(1, -(-req.periods_per_week // days))

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

    # Hard constraint: a teacher's TOTAL assigned periods across the whole week
    # (summed across every class/subject, not just one) must not exceed their
    # max_periods_per_week (default or per-run override) - a teacher with none
    # of their vars in this dict (never eligible for anything) is skipped, and a
    # teacher with max_periods_per_week=None is left uncapped.
    teachers_by_id = {t.id: t for t in teachers}
    for teacher_id, teacher_vars in vars_by_teacher.items():
        cap = teachers_by_id[teacher_id].max_periods_per_week
        if cap is not None:
            model.Add(sum(teacher_vars) <= cap)

    # Hard constraint (via each var's own domain, not a separate model.Add):
    # a requirement's per-day total can never exceed cap_by_req - this alone
    # guarantees "at most once per day" whenever periods_per_week <= days, and
    # "at most the mathematically-necessary minimum" otherwise. Soft on top:
    # minimize how much of that cap actually gets used (prefer 0 or 1 over the
    # cap on as many days as possible, even when the cap itself is >1).
    overflow_vars: list[cp_model.IntVar] = []
    for (req_idx, day), day_vars in vars_by_req_day.items():
        cap = cap_by_req[req_idx]
        day_total = model.NewIntVar(0, min(len(day_vars), cap), f"daytotal_r{req_idx}_d{day}")
        model.Add(day_total == sum(day_vars))
        if cap > 1:
            overflow = model.NewIntVar(0, cap - 1, f"overflow_r{req_idx}_d{day}")
            model.Add(overflow >= day_total - 1)
            overflow_vars.append(overflow)

    # Soft: minimize the spread (max - min) of a class's total periods/day
    # across the week, so gaps like "6 periods Monday, 0 Friday" get smoothed
    # out wherever the hard constraints leave room to do so.
    variance_terms: list[cp_model.IntVar] = []
    for class_id in class_ids:
        day_totals = []
        for day in range(days):
            day_vars = vars_by_class_day.get((class_id, day), [])
            if not day_vars:
                continue
            dt = model.NewIntVar(0, len(day_vars), f"classday_{class_id}_{day}")
            model.Add(dt == sum(day_vars))
            day_totals.append(dt)
        if len(day_totals) < 2:
            continue
        max_v = model.NewIntVar(0, periods_per_day, f"classmax_{class_id}")
        min_v = model.NewIntVar(0, periods_per_day, f"classmin_{class_id}")
        model.AddMaxEquality(max_v, day_totals)
        model.AddMinEquality(min_v, day_totals)
        variance_terms.append(max_v - min_v)

    same_day_clustering_expr = sum(overflow_vars) if overflow_vars else None
    day_variance_expr = sum(variance_terms) if variance_terms else None

    if same_day_clustering_expr is not None or day_variance_expr is not None:
        objective = 0
        if same_day_clustering_expr is not None:
            objective += _SAME_DAY_CLUSTERING_WEIGHT * same_day_clustering_expr
        if day_variance_expr is not None:
            objective += _DAY_VARIANCE_WEIGHT * day_variance_expr
        model.Minimize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = _RANDOM_SEED
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
    return GenerationResult(
        slots=schedule,
        warnings=warnings,
        objective_weights={"same_day_clustering": _SAME_DAY_CLUSTERING_WEIGHT, "day_variance": _DAY_VARIANCE_WEIGHT},
        objective_values={
            "same_day_clustering": solver.Value(same_day_clustering_expr) if same_day_clustering_expr is not None else 0,
            "day_variance": solver.Value(day_variance_expr) if day_variance_expr is not None else 0,
        },
    )


def diagnose_infeasibility(
    *,
    teachers: list[SolverTeacher],
    rooms: list[SolverRoom],
    subjects: list[SolverSubject],
    requirements: list[SolverRequirement],
    days: int = 5,
    periods_per_day: int = 6,
    time_limit_seconds: float = 30.0,
    class_names: dict[int, str] | None = None,
    subject_names: dict[int, str] | None = None,
    teacher_names: dict[int, str] | None = None,
) -> InfeasibilityFinding:
    """Called only when generate_timetable raises UnsolvableError despite the
    input passing every pre-flight arithmetic check (timetable_preflight.py)
    - i.e. the infeasibility comes from CONSTRAINT INTERACTION (teacher/room
    contention across specific requirements) that pure arithmetic can't
    predict, not a raw capacity shortfall.

    Rebuilds a similar model, but with each requirement's own hard "exactly
    periods_per_week" constraint gated behind a dedicated assumption literal
    (model.NewBoolVar + .OnlyEnforceIf + model.AddAssumptions), leaving the
    physical double-booking constraints (teacher/room/class) as always-true
    bedrock, not assumptions - those aren't independently relaxable
    "requirements", they're facts about reality. On INFEASIBLE,
    solver.SufficientAssumptionsForInfeasibility() returns the minimal set of
    assumption literals that together cause it - i.e. the specific
    requirements actually in conflict, translated back into a plain-language
    sentence naming them and the shared teacher pool they're contending for.
    """
    class_names = class_names or {}
    subject_names = subject_names or {}
    teacher_names = teacher_names or {}

    subjects_by_id = {s.id: s for s in subjects}
    rooms_by_id = {r.id: r for r in rooms}
    day_periods = [(d, p) for d in range(days) for p in range(periods_per_day)]

    model = cp_model.CpModel()
    x: dict[tuple[int, int, int, int, int], cp_model.IntVar] = {}
    vars_by_req: dict[int, list[cp_model.IntVar]] = defaultdict(list)
    vars_by_req_day: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_teacher_dp: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_room_dp: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_class_dp: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    vars_by_teacher: dict[int, list[cp_model.IntVar]] = defaultdict(list)

    assumptions: dict[int, cp_model.IntVar] = {}

    for req_idx, req in enumerate(requirements):
        subject = subjects_by_id.get(req.subject_id)
        if subject is None:
            continue
        eligible_teachers = [t for t in teachers if req.subject_id in t.subject_ids]
        if subject.required_room_type is not None:
            eligible_rooms = [r for r in rooms if r.room_type == subject.required_room_type]
        elif req.home_room_id is not None and req.home_room_id in rooms_by_id:
            eligible_rooms = [rooms_by_id[req.home_room_id]]
        else:
            eligible_rooms = list(rooms)
        if not eligible_teachers or not eligible_rooms:
            continue

        for teacher in eligible_teachers:
            for room in eligible_rooms:
                for day, period in day_periods:
                    if (day, period) in teacher.unavailable:
                        continue
                    var = model.NewBoolVar(f"x_r{req_idx}_t{teacher.id}_rm{room.id}_d{day}_p{period}")
                    x[(req_idx, teacher.id, room.id, day, period)] = var
                    vars_by_req[req_idx].append(var)
                    vars_by_req_day[(req_idx, day)].append(var)
                    vars_by_teacher_dp[(teacher.id, day, period)].append(var)
                    vars_by_room_dp[(room.id, day, period)].append(var)
                    vars_by_class_dp[(req.class_id, day, period)].append(var)
                    vars_by_teacher[teacher.id].append(var)

        if not vars_by_req[req_idx]:
            continue

        assume = model.NewBoolVar(f"assume_req_{req_idx}")
        assumptions[req_idx] = assume
        model.Add(sum(vars_by_req[req_idx]) == req.periods_per_week).OnlyEnforceIf(assume)

        # Same-day clustering cap (must mirror generate_timetable's hard "at
        # most ceil(periods_per_week/days) per day" rule) - without this, a
        # requirement whose only free slots are clustered on one day would
        # wrongly look satisfiable to this diagnostic model, exactly the gap
        # that let a real bug's constraint interaction hide from pre-flight.
        cap = max(1, -(-req.periods_per_week // days))
        for day in range(days):
            day_vars = vars_by_req_day.get((req_idx, day), [])
            if day_vars:
                model.Add(sum(day_vars) <= cap).OnlyEnforceIf(assume)

    # Bedrock physical constraints - always enforced, never assumption-gated.
    for dp_vars in vars_by_teacher_dp.values():
        model.Add(sum(dp_vars) <= 1)
    for dp_vars in vars_by_room_dp.values():
        model.Add(sum(dp_vars) <= 1)
    for dp_vars in vars_by_class_dp.values():
        model.Add(sum(dp_vars) <= 1)
    teachers_by_id = {t.id: t for t in teachers}
    for teacher_id, teacher_vars in vars_by_teacher.items():
        cap = teachers_by_id[teacher_id].max_periods_per_week
        if cap is not None:
            model.Add(sum(teacher_vars) <= cap)

    if not assumptions:
        return InfeasibilityFinding(
            code="INFEASIBLE_NO_MAPPABLE_REQUIREMENT",
            message=(
                "No feasible timetable exists, and no requirement had any eligible teacher/room combination "
                "to isolate as the cause."
            ),
            requirement_indices=[],
            details={},
        )

    model.AddAssumptions(list(assumptions.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 1  # a diagnostic core must be reproducible, not a scheduling output
    solver.parameters.random_seed = _RANDOM_SEED
    status = solver.Solve(model)

    if status != cp_model.INFEASIBLE:
        # Either it turned out feasible after all (can happen only if the
        # original infeasibility depended on a soft/derived constraint this
        # diagnostic model doesn't encode) or the solve didn't finish in
        # time - either way, no usable core exists.
        return InfeasibilityFinding(
            code="INFEASIBLE_CORE_UNAVAILABLE",
            message="No feasible timetable exists, but the specific cause could not be isolated by this diagnostic pass.",
            requirement_indices=[],
            details={"assumption_status": solver.StatusName(status)},
        )

    core_literal_indices = set(solver.SufficientAssumptionsForInfeasibility())
    core_req_indices = sorted(req_idx for req_idx, var in assumptions.items() if var.Index() in core_literal_indices)

    if not core_req_indices:
        # Empty/unmappable core - fall back to the full assumption set that
        # was active, per this function's own contract, rather than a
        # generic message with no actionable detail at all.
        core_req_indices = sorted(assumptions.keys())

    core_reqs = [requirements[i] for i in core_req_indices]
    subject_ids_in_core = {req.subject_id for req in core_reqs}
    contending_teachers = [t for t in teachers if subject_ids_in_core & t.subject_ids]
    total_slots = len(day_periods)
    combined_free = sum(
        max(0, min(t.max_periods_per_week if t.max_periods_per_week is not None else total_slots, total_slots)
            - len(t.unavailable))
        for t in contending_teachers
    )
    teacher_names_str = " or ".join(teacher_names.get(t.id, str(t.id)) for t in contending_teachers) or "no qualified teacher"

    parts = []
    for req in core_reqs:
        cname = class_names.get(req.class_id, str(req.class_id))
        sname = subject_names.get(req.subject_id, str(req.subject_id))
        parts.append(f"{cname} {sname} ({req.periods_per_week} periods)")
    requirement_list = " and ".join(parts)
    require_verb = "requires" if len(core_reqs) == 1 else "both require"
    have_clause = "has" if len(contending_teachers) == 1 else "together have"
    total_demand_in_core = sum(req.periods_per_week for req in core_reqs)

    message = (
        f"{requirement_list} {require_verb} {teacher_names_str}, who {have_clause} only {combined_free} free "
        f"slot(s) - not enough to cover every one of these requirements at once."
    )
    if combined_free >= total_demand_in_core:
        # The raw slot count looks sufficient in aggregate - the real
        # conflict is almost certainly distributional (this app's own
        # same-subject-per-day clustering cap forces spreading periods
        # across distinct days, so slots concentrated on too few days can't
        # be fully used even when the total count would otherwise cover it).
        message += (
            " The combined free-slot count is not itself the shortfall - the free slots are spread across "
            "too few distinct days to satisfy the once-per-day spread limit."
        )

    return InfeasibilityFinding(
        code="SOLVE_CONSTRAINT_CONFLICT",
        message=message,
        requirement_indices=core_req_indices,
        details={
            "requirements": [
                {"class_id": r.class_id, "subject_id": r.subject_id, "periods_per_week": r.periods_per_week}
                for r in core_reqs
            ],
            "contending_teacher_ids": [t.id for t in contending_teachers],
            "combined_free_slots": combined_free,
        },
    )
