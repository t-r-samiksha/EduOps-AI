"""Pre-flight arithmetic diagnostics for timetable generation.

Runs BEFORE CP-SAT model construction. These checks are pure arithmetic (plus
a couple of small bipartite max-flow computations) and execute in
milliseconds - they exist so a bad input produces specific, quantified,
actionable findings instead of "no feasible timetable exists" after a 30s
solve. Deliberately decoupled from the ORM, same as timetable_solver.py:
callers build plain dataclasses, get back plain Finding dataclasses.

Coverage note: these checks catch the majority of real infeasible inputs, but
are NOT a full equivalent of the CP-SAT model (they mostly reason about
class-level and subject-level aggregates, not every joint interaction the
solver's per-period constraints encode). An input can pass every check here
and still be infeasible - that residual case is what
timetable_solver.diagnose_infeasibility (Part 2) is for.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from math import ceil

from app.services.timetable_solver import SolverRequirement, SolverRoom, SolverSubject, SolverTeacher

# Matches TeacherProfile.max_periods_per_week's own server_default - used only
# to size "how many typical new teachers would close this gap" remedies, not
# as a cap applied to any real teacher.
_DEFAULT_TEACHER_MAX_PERIODS_PER_WEEK = 30

# A subject/teacher pool at or above this demand/capacity ratio is technically
# feasible but tight enough to often cause a slow solve or a late failure once
# combined with the solver's other hard constraints (rooms, unavailability).
_TIGHT_POOL_RATIO = 0.85


@dataclass(frozen=True)
class Remedy:
    action: str
    quantity: int
    detail: str


@dataclass(frozen=True)
class Finding:
    severity: str
    """"error" or "warning". Every error-severity finding carries at least one
    remedy with a concrete quantity; warnings may have none."""
    code: str
    message: str
    numbers: dict[str, int]
    subject: str | None = None
    remedies: list[Remedy] = field(default_factory=list)
    details: dict | None = None
    """Extra structured payload that doesn't fit a flat int-keyed `numbers`
    dict - per-subject breakdowns, affected class/teacher id lists, etc."""


@dataclass(frozen=True)
class ClassInfo:
    """One resolved section for this run - the subset of SchoolClass fields
    these checks need."""

    id: int
    name: str
    home_room_id: int | None
    class_teacher_id: int | None


# --- Small bipartite max-flow helper (Edmonds-Karp) -----------------------
#
# Used to correctly handle overlapping pools (a teacher qualified for two
# subjects, a class-subject pair that could use any of several period slots):
# naive independent per-item sums double-count shared capacity and can pass a
# genuinely infeasible input. Modeling demand-side items and capacity-side
# items as a source -> demand -> capacity -> sink flow network and taking the
# max-flow is exactly Hall's condition for bipartite feasibility.


def _edmonds_karp(source: object, sink: object, graph: dict[object, dict[object, int]]) -> int:
    """Max-flow via repeated BFS augmenting paths. `graph` (adjacency dict of
    residual capacities) is mutated in place; returns the total flow found.
    Generic over node identity, so callers can build 2-layer (bipartite) or
    3-layer (bipartite + an exclusivity layer) networks on top of it."""
    total_flow = 0
    while True:
        parent: dict[object, object] = {source: None}
        queue = deque([source])
        while queue:
            u = queue.popleft()
            if u is sink:
                break
            for v, residual in graph[u].items():
                if residual > 0 and v not in parent:
                    parent[v] = u
                    queue.append(v)
        if sink not in parent:
            break

        path: list[tuple[object, object]] = []
        node = sink
        bottleneck = float("inf")
        while parent[node] is not None:
            u = parent[node]
            bottleneck = min(bottleneck, graph[u][node])
            path.append((u, node))
            node = u

        for u, v in path:
            graph[u][v] -= bottleneck
            graph[v][u] += bottleneck
        total_flow += int(bottleneck)

    return total_flow


def _max_bipartite_flow(
    demands: dict[object, int],
    capacities: dict[object, int],
    edges: set[tuple[object, object]],
    edge_capacity: int | None = None,
) -> tuple[int, dict[tuple[object, object], int]]:
    """Returns (total_flow, flow_by_(demand,capacity)_edge).

    total_flow < sum(demands.values()) means the demand side cannot be fully
    satisfied by the capacity side given the allowed edges - a genuine,
    overlap-aware infeasibility proof, not a heuristic.

    edge_capacity caps how much flow a single (demand, capacity) edge can
    carry - leave None for "unlimited" (e.g. one teacher can supply many
    periods of one subject); pass 1 when each edge represents a single
    indivisible unit.
    """
    SOURCE, SINK = object(), object()
    unlimited = sum(demands.values()) + sum(capacities.values()) + 1
    cap_edge = edge_capacity if edge_capacity is not None else unlimited

    graph: dict[object, dict[object, int]] = defaultdict(lambda: defaultdict(int))
    original: dict[tuple[object, object], int] = {}
    for d, amount in demands.items():
        graph[SOURCE][d] += amount
    for c, amount in capacities.items():
        graph[c][SINK] += amount
    for d, c in edges:
        if d in demands and c in capacities:
            graph[d][c] += cap_edge
            original[(d, c)] = graph[d][c]

    _edmonds_karp(SOURCE, SINK, graph)

    flow_by_edge = {edge: original[edge] - graph[edge[0]][edge[1]] for edge in original}
    total_flow = sum(flow_by_edge.values())
    return total_flow, flow_by_edge


def _lab_peak_flow(demand_by_key: dict[tuple[int, int], int], lab_room_count: int, period_slots: list[tuple[int, int]]) -> int:
    """Exact peak-concurrency feasibility for lab-required demand, via a
    3-layer flow: demand(class,subject) -> (class,slot) [cap 1, a class can't
    be in two places in the same period] -> slot [cap lab_room_count] -> sink.

    A plain 2-layer flow with full demand<->slot connectivity would always
    equal min(total_demand, lab_room_count*total_slots) by Hall's theorem
    (every demand subset's neighborhood is the whole slot set) - i.e. it can
    never be tighter than the weekly aggregate check, making it redundant.
    The (class,slot) exclusivity layer is what can make peak concurrency a
    genuinely tighter, distinct failure: a single class needing two
    lab-required subjects can still only occupy one slot at a time, however
    many lab rooms exist."""
    SOURCE, SINK = object(), object()
    graph: dict[object, dict[object, int]] = defaultdict(lambda: defaultdict(int))
    for key, amount in demand_by_key.items():
        graph[SOURCE][key] += amount
        class_id = key[0]
        for slot in period_slots:
            mid = (class_id, slot)
            graph[key][mid] = 1  # this class-subject can claim this slot at most once
            graph[mid][slot] = 1  # ...and this class can only claim ONE slot-user per slot at all
    for slot in period_slots:
        graph[slot][SINK] = lab_room_count  # the slot itself can host up to lab_room_count classes at once

    return _edmonds_karp(SOURCE, SINK, graph)


# --- Check A: section balance ------------------------------------------------


def _check_section_balance(requirements: list[SolverRequirement], days: int, periods_per_day: int) -> list[Finding]:
    subject_periods: dict[int, int] = {}
    for req in requirements:
        subject_periods.setdefault(req.subject_id, req.periods_per_week)

    required = sum(subject_periods.values())
    available = periods_per_day * days
    diff = required - available
    breakdown = [{"subject_id": sid, "periods_per_week": p} for sid, p in subject_periods.items()]

    if diff == 0:
        return []

    if diff > 0:
        return [
            Finding(
                severity="error",
                code="SECTION_OVER_SUBSCRIBED",
                message=(
                    f"Selected subjects require {required} periods/week per section, but only {available} "
                    f"slots exist ({periods_per_day} periods/day x {days} days/wk) - {diff} too many."
                ),
                numbers={"required": required, "available": available, "difference": diff},
                remedies=[
                    Remedy(
                        action="reduce_periods",
                        quantity=diff,
                        detail=f"reduce total periods/week across the selected subjects by {diff}",
                    ),
                    Remedy(
                        action="increase_capacity",
                        quantity=ceil(diff / days),
                        detail=f"increase periods/day by {ceil(diff / days)} (or add more days/week)",
                    ),
                ],
                details={"per_subject": breakdown},
            )
        ]

    gap = -diff
    return [
        Finding(
            severity="warning",
            code="SECTION_UNDER_SUBSCRIBED",
            message=(
                f"Selected subjects only require {required} of the {available} available periods/week per "
                f"section - {gap} period(s) will be left empty. This may be intentional (free periods)."
            ),
            numbers={"required": required, "available": available, "difference": diff},
            details={"per_subject": breakdown},
        )
    ]


# --- Check B: teacher pool capacity (per subject, overlap-aware) -----------


def _teacher_capacity(teacher: SolverTeacher, uncapped_fallback: int) -> int:
    return teacher.max_periods_per_week if teacher.max_periods_per_week is not None else uncapped_fallback


def _check_teacher_pool_capacity(
    teachers: list[SolverTeacher],
    requirements: list[SolverRequirement],
    subject_names: dict[int, str],
    uncapped_fallback: int,
) -> list[Finding]:
    demand: dict[int, int] = defaultdict(int)
    for req in requirements:
        demand[req.subject_id] += req.periods_per_week
    if not demand:
        return []

    capacity_by_teacher = {t.id: _teacher_capacity(t, uncapped_fallback) for t in teachers}
    naive_capacity: dict[int, int] = {}
    qualified_by_subject: dict[int, list[SolverTeacher]] = defaultdict(list)
    for subj_id in demand:
        qualified = [t for t in teachers if subj_id in t.subject_ids]
        qualified_by_subject[subj_id] = qualified
        naive_capacity[subj_id] = sum(capacity_by_teacher[t.id] for t in qualified)

    naive_fail = {subj for subj, d in demand.items() if d > naive_capacity[subj]}

    # Node identities are namespaced ("subject"/"teacher" tags) before they
    # enter the flow graph - subject_id and teacher_id are plain ints from
    # unrelated tables and CAN collide in real data, which would otherwise
    # silently merge two distinct nodes into one in the flow network.
    demand_nodes = {("subject", subj_id): amount for subj_id, amount in demand.items()}
    capacity_nodes = {("teacher", teacher_id): cap for teacher_id, cap in capacity_by_teacher.items()}
    edges = {(("subject", subj_id), ("teacher", t.id)) for subj_id, ts in qualified_by_subject.items() for t in ts}
    total_flow, flow_by_edge = _max_bipartite_flow(demand_nodes, capacity_nodes, edges)
    served: dict[int, int] = defaultdict(int)
    for (subj_node, _teacher_node), amount in flow_by_edge.items():
        served[subj_node[1]] += amount

    overlap_fail = {subj for subj, d in demand.items() if subj not in naive_fail and d > served.get(subj, 0)}

    # Which other in-demand subjects share at least one teacher with a given
    # subject - named in overlap-caused findings so the admin sees the actual
    # contention, not just an unexplained shortfall.
    teachers_by_subject = {subj: {t.id for t in ts} for subj, ts in qualified_by_subject.items()}

    def _contenders(subj_id: int) -> list[int]:
        mine = teachers_by_subject[subj_id]
        return sorted(
            other for other, other_teachers in teachers_by_subject.items() if other != subj_id and mine & other_teachers
        )

    findings: list[Finding] = []
    for subj_id in sorted(naive_fail | overlap_fail):
        d = demand[subj_id]
        is_overlap = subj_id in overlap_fail
        reported_capacity = served.get(subj_id, 0) if is_overlap else naive_capacity[subj_id]
        shortfall = d - reported_capacity
        additional_teachers_needed = max(1, ceil(shortfall / _DEFAULT_TEACHER_MAX_PERIODS_PER_WEEK))
        name = subject_names.get(subj_id, str(subj_id))

        if is_overlap:
            contenders = [subject_names.get(c, str(c)) for c in _contenders(subj_id)]
            overlap_note = f" (pool shared with {', '.join(contenders)})" if contenders else ""
            message = (
                f"The teacher pool for {name}{overlap_note} can only supply {reported_capacity} of the "
                f"{d} periods/week needed once shared demand is accounted for - {shortfall} short."
            )
        else:
            message = (
                f"{name} needs {d} periods/week but its qualified teachers supply at most "
                f"{reported_capacity} periods/week total - {shortfall} short."
            )

        findings.append(
            Finding(
                severity="error",
                code="TEACHER_POOL_SHORTFALL",
                subject=name,
                message=message,
                numbers={
                    "demand": d,
                    "capacity": reported_capacity,
                    "shortfall": shortfall,
                    "additional_teachers_needed": additional_teachers_needed,
                },
                remedies=[
                    Remedy(
                        action="add_teachers",
                        quantity=additional_teachers_needed,
                        detail=f"{additional_teachers_needed} more teacher(s) qualified for {name}",
                    ),
                    Remedy(
                        action="reduce_periods",
                        quantity=shortfall,
                        detail=f"reduce {name} by {shortfall} period(s)/week",
                    ),
                ],
            )
        )

    for subj_id, d in demand.items():
        if subj_id in naive_fail or subj_id in overlap_fail:
            continue
        cap = naive_capacity[subj_id]
        if cap > 0 and d / cap > _TIGHT_POOL_RATIO:
            name = subject_names.get(subj_id, str(subj_id))
            findings.append(
                Finding(
                    severity="warning",
                    code="TEACHER_POOL_TIGHT",
                    subject=name,
                    message=(
                        f"{name}'s teacher pool is at {d}/{cap} ({d / cap:.0%}) capacity - technically "
                        "feasible but likely to cause a slow solve or a late failure once combined with "
                        "other constraints."
                    ),
                    numbers={"demand": d, "capacity": cap},
                )
            )

    return findings


def _teacher_flow_demand(
    teachers: list[SolverTeacher],
    requirements: list[SolverRequirement],
    capacity_by_teacher: dict[int, int],
) -> dict[int, int]:
    """Each teacher's assigned share of subject demand under ONE feasible (not
    necessarily unique) allocation respecting only raw per-teacher capacity -
    reused by Checks E/F as a concrete stand-in for "how much this run would
    need from this teacher", since no real per-teacher demand exists until
    the solver actually assigns periods."""
    demand: dict[int, int] = defaultdict(int)
    for req in requirements:
        demand[req.subject_id] += req.periods_per_week
    # Namespaced node identities - see _check_teacher_pool_capacity's comment
    # on why raw subject_id/teacher_id ints can't be used directly as nodes.
    demand_nodes = {("subject", subj_id): amount for subj_id, amount in demand.items()}
    capacity_nodes = {("teacher", teacher_id): cap for teacher_id, cap in capacity_by_teacher.items()}
    edges = {
        (("subject", req.subject_id), ("teacher", t.id))
        for req in requirements
        for t in teachers
        if req.subject_id in t.subject_ids
    }
    _total_flow, flow_by_edge = _max_bipartite_flow(demand_nodes, capacity_nodes, edges)
    assigned: dict[int, int] = defaultdict(int)
    for (_subj_node, teacher_node), amount in flow_by_edge.items():
        assigned[teacher_node[1]] += amount
    return dict(assigned)


# --- Check C: room concurrency (incl. home-room pinning) -------------------


def _check_room_concurrency(classes: list[ClassInfo], rooms: list[SolverRoom]) -> list[Finding]:
    """Non-lab room concurrency only - lab rooms are a separate, dedicated
    pool used exclusively by lab-required subjects (see Check D), never by
    home-room pinning or non-lab free choice, so they don't belong in this
    check's "eligible rooms" count."""
    findings: list[Finding] = []
    non_lab_rooms = [r for r in rooms if r.room_type != "lab"]
    eligible_rooms = len(non_lab_rooms)
    room_names = {r.id: str(r.id) for r in rooms}

    home_room_owners: dict[int, list[ClassInfo]] = defaultdict(list)
    for c in classes:
        if c.home_room_id is not None:
            home_room_owners[c.home_room_id].append(c)

    for room_id, owners in home_room_owners.items():
        if len(owners) > 1:
            findings.append(
                Finding(
                    severity="error",
                    code="ROOM_HOME_COLLISION",
                    message=(
                        f"{len(owners)} sections ({', '.join(c.name for c in owners)}) are pinned to the same "
                        f"home room ({room_names.get(room_id, room_id)}) - each pinned section needs its own "
                        "distinct room."
                    ),
                    numbers={"colliding_sections": len(owners)},
                    remedies=[
                        Remedy(
                            action="reassign_home_rooms",
                            quantity=len(owners) - 1,
                            detail=f"give {len(owners) - 1} of these section(s) a different home room",
                        )
                    ],
                    details={"class_ids": [c.id for c in owners], "room_id": room_id},
                )
            )

    unpinned = [c for c in classes if c.home_room_id is None]
    sections_in_run = len(classes)
    if sections_in_run > eligible_rooms:
        shortfall = sections_in_run - eligible_rooms
        findings.append(
            Finding(
                severity="error",
                code="ROOM_CONCURRENCY_SHORTFALL",
                message=(
                    f"{sections_in_run} section(s) each need a room simultaneously, but only {eligible_rooms} "
                    f"room(s) are selected for this run - {shortfall} short."
                ),
                numbers={
                    "sections_needing_rooms": sections_in_run,
                    "rooms_available": eligible_rooms,
                    "shortfall": shortfall,
                },
                remedies=[
                    Remedy(action="add_rooms", quantity=shortfall, detail=f"select {shortfall} more room(s) for this run")
                ],
                details={"unassigned_or_colliding_class_ids": [c.id for c in unpinned] or [c.id for c in classes]},
            )
        )

    return findings


# --- Check D: lab concurrency (weekly total + exact peak via max-flow) ----


def _check_lab_concurrency(
    classes: list[ClassInfo],
    requirements: list[SolverRequirement],
    subjects_by_id: dict[int, SolverSubject],
    rooms: list[SolverRoom],
    days: int,
    periods_per_day: int,
) -> list[Finding]:
    lab_room_count = sum(1 for r in rooms if r.room_type == "lab")
    lab_subject_ids = {s.id for s in subjects_by_id.values() if s.required_room_type == "lab"}
    if not lab_subject_ids:
        return []

    demand_by_key: dict[tuple[int, int], int] = {}
    for req in requirements:
        if req.subject_id in lab_subject_ids:
            demand_by_key[(req.class_id, req.subject_id)] = req.periods_per_week
    if not demand_by_key:
        return []

    total_demand = sum(demand_by_key.values())
    weekly_capacity = lab_room_count * periods_per_day * days

    if total_demand > weekly_capacity:
        shortfall = total_demand - weekly_capacity
        per_week = max(periods_per_day * days, 1)
        additional_labs_needed = ceil(shortfall / per_week)
        return [
            Finding(
                severity="error",
                code="LAB_CAPACITY_SHORTFALL",
                message=(
                    f"Lab-required subjects need {total_demand} lab booking(s)/week across "
                    f"{len(demand_by_key)} section-subject pair(s), but {lab_room_count} lab room(s) x "
                    f"{periods_per_day * days} periods/wk only provide {weekly_capacity} - {shortfall} short."
                ),
                numbers={
                    "demand": total_demand,
                    "capacity": weekly_capacity,
                    "shortfall": shortfall,
                    "additional_labs_needed": additional_labs_needed,
                },
                remedies=[
                    Remedy(action="add_labs", quantity=additional_labs_needed, detail=f"add {additional_labs_needed} more lab room(s)"),
                    Remedy(
                        action="reduce_periods",
                        quantity=shortfall,
                        detail=f"reduce lab-required subjects' periods/week by a total of {shortfall}",
                    ),
                ],
            )
        ]

    if lab_room_count == 0:
        return []

    period_slots = [(d, p) for d in range(days) for p in range(periods_per_day)]
    total_flow = _lab_peak_flow(demand_by_key, lab_room_count, period_slots)

    if total_flow < total_demand:
        shortfall = total_demand - total_flow
        per_week = max(periods_per_day * days, 1)
        additional_labs_needed = ceil(shortfall / per_week)
        return [
            Finding(
                severity="error",
                code="LAB_PEAK_CONCURRENCY_SHORTFALL",
                message=(
                    "Weekly lab capacity is sufficient in total, but more sections need a lab simultaneously "
                    f"than the {lab_room_count} lab room(s) can support in any single period - {shortfall} "
                    "booking(s) cannot be placed anywhere without a collision."
                ),
                numbers={
                    "demand": total_demand,
                    "capacity": total_flow,
                    "shortfall": shortfall,
                    "additional_labs_needed": additional_labs_needed,
                },
                remedies=[
                    Remedy(action="add_labs", quantity=additional_labs_needed, detail=f"add {additional_labs_needed} more lab room(s)")
                ],
            )
        ]

    return []


# --- Check E: per-teacher availability --------------------------------------


def _check_teacher_availability(
    teachers: list[SolverTeacher],
    requirements: list[SolverRequirement],
    teacher_names: dict[int, str],
    days: int,
    periods_per_day: int,
    uncapped_fallback: int,
) -> list[Finding]:
    if not requirements:
        return []
    total_slots = days * periods_per_day
    raw_capacity = {t.id: _teacher_capacity(t, uncapped_fallback) for t in teachers}

    # Baseline: what raw per-teacher capacity (ignoring unavailability) can
    # supply - if THIS is already short, Check B already explains it.
    raw_assigned = _teacher_flow_demand(teachers, requirements, raw_capacity)
    demand_total = sum(req.periods_per_week for req in requirements)
    # dedupe by subject since periods_per_week is per (class, subject); reuse
    # the same aggregation Check B uses for "total demand".
    subject_demand: dict[int, int] = defaultdict(int)
    for req in requirements:
        subject_demand[req.subject_id] += req.periods_per_week
    raw_total_demand = sum(subject_demand.values())
    raw_total_served = sum(raw_assigned.values())
    if raw_total_served < raw_total_demand:
        return []  # Check B already covers a raw-capacity shortfall

    effective_availability: dict[int, int] = {}
    blocked_count: dict[int, int] = {}
    tightened_capacity: dict[int, int] = {}
    for t in teachers:
        blocked = len(t.unavailable)
        blocked_count[t.id] = blocked
        effective_availability[t.id] = total_slots - blocked
        tightened_capacity[t.id] = min(raw_capacity[t.id], effective_availability[t.id])

    tightened_assigned = _teacher_flow_demand(teachers, requirements, tightened_capacity)
    tightened_total = sum(tightened_assigned.values())

    if tightened_total >= raw_total_demand:
        return []

    findings = []
    for t in teachers:
        if effective_availability[t.id] >= raw_capacity[t.id]:
            continue  # unavailability isn't actually the binding constraint for this teacher
        assigned = tightened_assigned.get(t.id, 0)
        if assigned < tightened_capacity[t.id]:
            continue  # not saturated - not a bottleneck
        name = teacher_names.get(t.id, str(t.id))
        findings.append(
            Finding(
                severity="error",
                code="TEACHER_AVAILABILITY_SHORTFALL",
                message=(
                    f"{name} would need {assigned} period(s) this run but only has {effective_availability[t.id]} "
                    f"slot(s) free out of {total_slots} ({blocked_count[t.id]} blocked by unavailability)."
                ),
                numbers={
                    "demand": assigned,
                    "effective_availability": effective_availability[t.id],
                    "blocked_slot_count": blocked_count[t.id],
                },
                remedies=[
                    Remedy(
                        action="clear_unavailability",
                        quantity=assigned - effective_availability[t.id],
                        detail=f"free up {assigned - effective_availability[t.id]} of {name}'s blocked slot(s), or assign another qualified teacher",
                    )
                ],
            )
        )
    return findings


# --- Check F: cross-run collisions (other grades' existing bookings) -------


def _check_cross_run_collisions(
    teachers: list[SolverTeacher],
    requirements: list[SolverRequirement],
    existing_bookings_by_teacher: dict[int, int],
    teacher_names: dict[int, str],
    days: int,
    periods_per_day: int,
    uncapped_fallback: int,
) -> list[Finding]:
    if not existing_bookings_by_teacher:
        return []
    total_slots = days * periods_per_day
    raw_capacity = {t.id: _teacher_capacity(t, uncapped_fallback) for t in teachers}
    assigned = _teacher_flow_demand(teachers, requirements, raw_capacity)

    findings = []
    for t in teachers:
        committed_elsewhere = existing_bookings_by_teacher.get(t.id, 0)
        if committed_elsewhere == 0:
            continue
        periods_free = total_slots - committed_elsewhere
        needed = assigned.get(t.id, 0)
        if needed > periods_free:
            name = teacher_names.get(t.id, str(t.id))
            shortfall = needed - periods_free
            findings.append(
                Finding(
                    severity="error",
                    code="CROSS_RUN_COLLISION",
                    message=(
                        f"{name} already has {committed_elsewhere} period(s)/week committed to previously "
                        f"generated grades this academic year, leaving {periods_free} of {total_slots} free - "
                        f"this run needs {needed} from them, {shortfall} more than they have left."
                    ),
                    numbers={
                        "periods_committed_elsewhere": committed_elsewhere,
                        "periods_free": periods_free,
                        "periods_needed": needed,
                        "shortfall": shortfall,
                    },
                    remedies=[
                        Remedy(
                            action="assign_other_teacher",
                            quantity=shortfall,
                            detail=f"cover {shortfall} of this run's period(s) with a different qualified teacher, or reduce demand by {shortfall}",
                        )
                    ],
                )
            )
    return findings


# --- Check G: every class must have a class teacher -------------------------


def _check_class_teacher_assigned(classes: list[ClassInfo]) -> list[Finding]:
    """Every class must have a designated class teacher before a timetable can
    be generated for it - a school-operations policy decision (not a solver
    feasibility constraint), enforced here since this is the one shared gate
    both POST /preflight and POST /generate already run through."""
    missing = [c for c in classes if c.class_teacher_id is None]
    if not missing:
        return []
    names = ", ".join(c.name for c in missing)
    return [
        Finding(
            severity="error",
            code="CLASS_TEACHER_MISSING",
            message=(
                f"{len(missing)} section(s) have no class teacher assigned ({names}) - every class must have "
                "one before a timetable can be generated for it. Assign one in School Management > Classes."
            ),
            numbers={"classes_missing_teacher": len(missing)},
            remedies=[
                Remedy(
                    action="assign_class_teacher",
                    quantity=len(missing),
                    detail=f"assign a class teacher to {len(missing)} section(s): {names}",
                )
            ],
            details={"class_ids": [c.id for c in missing]},
        )
    ]


def run_preflight_checks(
    *,
    teachers: list[SolverTeacher],
    rooms: list[SolverRoom],
    subjects: list[SolverSubject],
    requirements: list[SolverRequirement],
    classes: list[ClassInfo],
    days: int,
    periods_per_day: int,
    subject_names: dict[int, str] | None = None,
    teacher_names: dict[int, str] | None = None,
    existing_bookings_by_teacher: dict[int, int] | None = None,
) -> list[Finding]:
    """Runs ALL checks (A-F) and returns every failure together - never stops
    at the first, so an admin sees every problem in one pass."""
    subject_names = subject_names or {}
    teacher_names = teacher_names or {}
    existing_bookings_by_teacher = existing_bookings_by_teacher or {}
    subjects_by_id = {s.id: s for s in subjects}
    uncapped_fallback = days * periods_per_day

    findings: list[Finding] = []
    findings += _check_section_balance(requirements, days, periods_per_day)
    findings += _check_teacher_pool_capacity(teachers, requirements, subject_names, uncapped_fallback)
    findings += _check_room_concurrency(classes, rooms)
    findings += _check_lab_concurrency(classes, requirements, subjects_by_id, rooms, days, periods_per_day)
    findings += _check_teacher_availability(teachers, requirements, teacher_names, days, periods_per_day, uncapped_fallback)
    findings += _check_cross_run_collisions(
        teachers, requirements, existing_bookings_by_teacher, teacher_names, days, periods_per_day, uncapped_fallback
    )
    findings += _check_class_teacher_assigned(classes)
    return findings
