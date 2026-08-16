import pytest

from app.services.timetable_preflight import ClassInfo, run_preflight_checks
from app.services.timetable_solver import (
    SolverRequirement,
    SolverRoom,
    SolverSubject,
    SolverTeacher,
    UnsolvableError,
    diagnose_infeasibility,
    generate_timetable,
)

# Small fixture: 3 teachers, 5 subjects, 2 rooms, 1 class - matches the sizing
# called out in the task brief, small enough to solve near-instantly while still
# exercising every hard constraint (teacher/room/class double-booking + the
# subject->room-type requirement).

MATH, SCIENCE, ENGLISH, HISTORY, ART = 1, 2, 3, 4, 5
CLASS_A = 100
CLASSROOM, LAB = "classroom", "lab"


def _fixture():
    subjects = [
        SolverSubject(id=MATH),
        SolverSubject(id=SCIENCE, required_room_type=LAB),
        SolverSubject(id=ENGLISH),
        SolverSubject(id=HISTORY),
        SolverSubject(id=ART),
    ]
    teachers = [
        SolverTeacher(id=1, subject_ids=frozenset({MATH, ENGLISH})),
        SolverTeacher(id=2, subject_ids=frozenset({SCIENCE, HISTORY})),
        SolverTeacher(id=3, subject_ids=frozenset({ART, MATH})),
    ]
    rooms = [
        SolverRoom(id=1, room_type=CLASSROOM),
        SolverRoom(id=2, room_type=LAB),
    ]
    requirements = [
        SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=4),
        SolverRequirement(class_id=CLASS_A, subject_id=SCIENCE, periods_per_week=3),
        SolverRequirement(class_id=CLASS_A, subject_id=ENGLISH, periods_per_week=3),
        SolverRequirement(class_id=CLASS_A, subject_id=HISTORY, periods_per_week=2),
        SolverRequirement(class_id=CLASS_A, subject_id=ART, periods_per_week=2),
    ]
    return teachers, rooms, subjects, requirements


def test_generates_a_slot_for_every_required_period():
    teachers, rooms, subjects, requirements = _fixture()
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements).slots

    assert len(schedule) == sum(r.periods_per_week for r in requirements)
    for req in requirements:
        count = sum(1 for s in schedule if s.subject_id == req.subject_id)
        assert count == req.periods_per_week


def test_no_teacher_double_booked():
    teachers, rooms, subjects, requirements = _fixture()
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements).slots

    seen = set()
    for s in schedule:
        key = (s.teacher_id, s.day_of_week, s.period_number)
        assert key not in seen, f"teacher double-booked: {key}"
        seen.add(key)


def test_no_room_double_booked():
    teachers, rooms, subjects, requirements = _fixture()
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements).slots

    seen = set()
    for s in schedule:
        key = (s.room_id, s.day_of_week, s.period_number)
        assert key not in seen, f"room double-booked: {key}"
        seen.add(key)


def test_no_class_double_booked():
    teachers, rooms, subjects, requirements = _fixture()
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements).slots

    seen = set()
    for s in schedule:
        key = (s.class_id, s.day_of_week, s.period_number)
        assert key not in seen, f"class double-booked: {key}"
        seen.add(key)


def test_only_qualified_teachers_assigned():
    teachers, rooms, subjects, requirements = _fixture()
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements).slots

    subjects_by_teacher = {t.id: t.subject_ids for t in teachers}
    for s in schedule:
        assert s.subject_id in subjects_by_teacher[s.teacher_id]


def test_science_only_scheduled_in_lab():
    teachers, rooms, subjects, requirements = _fixture()
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements).slots

    room_types = {r.id: r.room_type for r in rooms}
    for s in schedule:
        if s.subject_id == SCIENCE:
            assert room_types[s.room_id] == LAB


def test_teacher_unavailability_is_respected():
    teachers, rooms, subjects, requirements = _fixture()
    # Teacher 1 is the only teacher qualified for English (3/wk) and shares Math
    # (4/wk) with teacher 3. Restrict teacher 1 to one slot each on 4 DIFFERENT
    # days (not 4 slots on the same day) - English's 3/wk now needs to land on
    # 3 distinct days to satisfy the same-day spread cap below, so all of
    # teacher 1's free time being on a single day would make this fixture
    # genuinely infeasible rather than testing unavailability specifically.
    free_slots = {(0, 0), (1, 0), (2, 0), (3, 0)}
    restricted = [
        SolverTeacher(
            id=1,
            subject_ids=frozenset({MATH, ENGLISH}),
            unavailable=frozenset((d, p) for d in range(5) for p in range(6) if (d, p) not in free_slots),
        ),
        teachers[1],
        teachers[2],
    ]
    schedule = generate_timetable(teachers=restricted, rooms=rooms, subjects=subjects, requirements=requirements).slots
    for s in schedule:
        if s.teacher_id == 1:
            assert (s.day_of_week, s.period_number) in free_slots


def test_raises_when_no_qualified_teacher_for_subject():
    teachers, rooms, subjects, _ = _fixture()
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=ART + 1, periods_per_week=1)]
    subjects = subjects + [SolverSubject(id=ART + 1)]

    with pytest.raises(UnsolvableError):
        generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)


def test_raises_when_no_room_of_required_type():
    teachers, rooms, subjects, requirements = _fixture()
    rooms_without_lab = [SolverRoom(id=1, room_type=CLASSROOM)]

    with pytest.raises(UnsolvableError):
        generate_timetable(teachers=teachers, rooms=rooms_without_lab, subjects=subjects, requirements=requirements)


def test_teacher_max_periods_per_week_is_respected():
    teachers, rooms, subjects, requirements = _fixture()
    # Teacher 1 is the SOLE qualified teacher for English (3/wk) and shares Math
    # (4/wk) with teacher 3. Capping teacher 1 at exactly 3 total periods/week
    # should force every one of their periods to go to English, leaving Math
    # entirely to teacher 3 - still feasible (teacher 3: Art 2 + Math 4 = 6).
    capped = [
        SolverTeacher(id=1, subject_ids=frozenset({MATH, ENGLISH}), max_periods_per_week=3),
        teachers[1],
        teachers[2],
    ]
    schedule = generate_timetable(teachers=capped, rooms=rooms, subjects=subjects, requirements=requirements).slots

    teacher1_periods = [s for s in schedule if s.teacher_id == 1]
    assert len(teacher1_periods) <= 3
    assert len(teacher1_periods) == 3  # not merely under the cap - fully saturated by English
    assert all(s.subject_id == ENGLISH for s in teacher1_periods)
    assert all(s.teacher_id == 3 for s in schedule if s.subject_id == MATH)


def test_raises_when_max_periods_per_week_infeasible():
    teachers, rooms, subjects, requirements = _fixture()
    # English (3/wk) has exactly one qualified teacher (teacher 1) - capping them
    # below English's own demand makes the whole requirement set infeasible
    # regardless of how Math gets routed.
    capped = [
        SolverTeacher(id=1, subject_ids=frozenset({MATH, ENGLISH}), max_periods_per_week=2),
        teachers[1],
        teachers[2],
    ]
    with pytest.raises(UnsolvableError):
        generate_timetable(teachers=capped, rooms=rooms, subjects=subjects, requirements=requirements)


def test_raises_when_infeasible_due_to_overloaded_single_teacher():
    # Only one teacher qualified for Math, and only 2 periods/day available -
    # asking for more Math periods/week than the grid can hold for that teacher
    # (given the teacher must also fit other requirements) should be infeasible.
    teachers = [SolverTeacher(id=1, subject_ids=frozenset({MATH}))]
    rooms = [SolverRoom(id=1, room_type=CLASSROOM)]
    subjects = [SolverSubject(id=MATH)]
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=5)]

    with pytest.raises(UnsolvableError):
        generate_timetable(
            teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements,
            days=1, periods_per_day=2,
        )


# --- Homeroom pinning (Issue 1) -------------------------------------------------


def test_non_lab_periods_pinned_to_home_room():
    """Two ordinary classrooms exist (either would have been "eligible" under
    the old free-choice-among-all-non-lab-rooms behavior) - with home_room_id
    set, every Math period must land in room 1, never room 3."""
    subjects = [SolverSubject(id=MATH), SolverSubject(id=SCIENCE, required_room_type=LAB)]
    teachers = [SolverTeacher(id=1, subject_ids=frozenset({MATH, SCIENCE}))]
    rooms = [
        SolverRoom(id=1, room_type=CLASSROOM),
        SolverRoom(id=2, room_type=LAB),
        SolverRoom(id=3, room_type=CLASSROOM),
    ]
    requirements = [
        SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=4, home_room_id=1),
        SolverRequirement(class_id=CLASS_A, subject_id=SCIENCE, periods_per_week=2, home_room_id=1),
    ]
    result = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)

    math_rooms = {s.room_id for s in result.slots if s.subject_id == MATH}
    science_rooms = {s.room_id for s in result.slots if s.subject_id == SCIENCE}
    assert math_rooms == {1}, "non-lab subject must stay in the home room only"
    assert science_rooms == {2}, "lab-required subject must still go to the lab, home_room_id notwithstanding"
    assert result.warnings == []


def test_missing_home_room_falls_back_to_free_choice_and_warns():
    teachers, rooms, subjects, requirements = _fixture()
    # None of _fixture()'s requirements set home_room_id - confirm the old
    # free-choice behavior still works (no crash, full schedule produced) and
    # that a warning naming the class is now surfaced.
    result = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)
    assert len(result.slots) == sum(r.periods_per_week for r in requirements)
    assert len(result.warnings) == 1
    assert str(CLASS_A) in result.warnings[0]
    assert "home_room_id" in result.warnings[0]


def test_missing_home_room_warns_once_per_class_not_per_requirement():
    teachers, rooms, subjects, requirements = _fixture()
    # _fixture() already has 5 requirements all for CLASS_A with no home_room_id -
    # the warning must be deduplicated per class, not repeated per requirement.
    result = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)
    assert len(result.warnings) == 1


def test_home_room_id_not_in_room_selection_raises_clearly():
    subjects = [SolverSubject(id=MATH)]
    teachers = [SolverTeacher(id=1, subject_ids=frozenset({MATH}))]
    rooms = [SolverRoom(id=1, room_type=CLASSROOM)]
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=2, home_room_id=999)]

    with pytest.raises(UnsolvableError, match="home_room_id"):
        generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)


# --- Same-subject-per-day spread (Issue 2) --------------------------------------


def _count_by_day(slots):
    counts: dict[int, int] = {}
    for s in slots:
        counts[s.day_of_week] = counts.get(s.day_of_week, 0) + 1
    return counts


def test_subject_never_repeats_in_one_day_when_not_required():
    """3 periods/week on a 5-day week: 3 <= 5, so every day can hold at most
    one - clustering (e.g. twice on Monday, once on Wednesday) is never
    mathematically necessary and must not happen."""
    subjects = [SolverSubject(id=ENGLISH)]
    teachers = [SolverTeacher(id=1, subject_ids=frozenset({ENGLISH}))]
    rooms = [SolverRoom(id=1, room_type=CLASSROOM)]
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=ENGLISH, periods_per_week=3, home_room_id=1)]

    result = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements, days=5, periods_per_day=6)
    counts = _count_by_day(result.slots)
    assert len(result.slots) == 3
    assert all(c <= 1 for c in counts.values()), f"a day had more than one occurrence: {counts}"
    assert result.objective_values["same_day_clustering"] == 0


def test_subject_clusters_only_when_mathematically_forced():
    """8 periods/week on a 5-day week: ceil(8/5) = 2, so at least 3 days MUST
    hit 2 (3*2 + 2*1 = 8) - confirm the solver uses exactly that minimum,
    never 3+ in a day and never more clustered days than the minimum forces."""
    subjects = [SolverSubject(id=MATH)]
    teachers = [SolverTeacher(id=1, subject_ids=frozenset({MATH}))]
    rooms = [SolverRoom(id=1, room_type=CLASSROOM)]
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=8, home_room_id=1)]

    result = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements, days=5, periods_per_day=6)
    counts = _count_by_day(result.slots)
    assert len(result.slots) == 8
    assert max(counts.values()) == 2, f"no day should exceed the ceil(8/5)=2 cap: {counts}"
    clustered_days = sum(1 for c in counts.values() if c == 2)
    assert clustered_days == 3, f"expected exactly 3 clustered days (8 - 5 days = 3), got {clustered_days}: {counts}"
    # Overflow (day_total - 1, summed) is exactly 3 at this forced minimum - one
    # unit of "clustering" per necessarily-doubled day, never more.
    assert result.objective_values["same_day_clustering"] == 3


def test_day_variance_objective_is_reported():
    teachers, rooms, subjects, requirements = _fixture()
    result = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)
    assert "day_variance" in result.objective_values
    assert "day_variance" in result.objective_weights
    assert result.objective_weights["same_day_clustering"] > result.objective_weights["day_variance"]


# --- Infeasibility diagnostics (Part 2): CP-SAT core, for inputs that pass ---
# --- every pre-flight arithmetic check yet are still genuinely infeasible ---


def test_diagnose_infeasibility_names_the_conflicting_requirement_for_a_case_preflight_cannot_catch():
    """4 free slots exist for the sole qualified teacher - enough in raw
    count to cover Math's 4 periods/week - but all 4 land on the SAME day,
    and the solver's own same-subject-per-day cap (ceil(4/5)=1 here) forbids
    using more than 1 of them for this class. Pre-flight's Check E only
    counts raw free-slot totals, so it cannot see this - it takes the real
    CP-SAT model's own infeasibility core to name the actual conflict."""
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=4, home_room_id=1)]
    free_slots = {(0, 0), (0, 1), (0, 2), (0, 3)}
    teacher = SolverTeacher(
        id=1,
        subject_ids=frozenset({MATH}),
        max_periods_per_week=20,
        unavailable=frozenset((d, p) for d in range(5) for p in range(4) if (d, p) not in free_slots),
    )
    rooms = [SolverRoom(id=1, room_type=CLASSROOM)]
    subjects = [SolverSubject(id=MATH)]
    classes = [ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1)]

    findings = run_preflight_checks(
        teachers=[teacher], rooms=rooms, subjects=subjects, requirements=requirements, classes=classes,
        days=5, periods_per_day=4,
    )
    assert not any(f.severity == "error" for f in findings), f"expected pre-flight to pass cleanly, got {findings}"

    with pytest.raises(UnsolvableError):
        generate_timetable(teachers=[teacher], rooms=rooms, subjects=subjects, requirements=requirements, days=5, periods_per_day=4)

    diagnosis = diagnose_infeasibility(
        teachers=[teacher], rooms=rooms, subjects=subjects, requirements=requirements, days=5, periods_per_day=4,
        class_names={CLASS_A: "Grade 1-A"}, subject_names={MATH: "Math"}, teacher_names={1: "T1"},
    )
    assert diagnosis.code == "SOLVE_CONSTRAINT_CONFLICT"
    assert diagnosis.requirement_indices == [0]
    assert "Grade 1-A" in diagnosis.message
    assert "Math" in diagnosis.message
    assert "T1" in diagnosis.message
    assert diagnosis.details["contending_teacher_ids"] == [1]


def test_diagnose_infeasibility_falls_back_when_no_requirement_is_mappable():
    """No requirement has any eligible teacher at all - there's nothing to
    isolate a core from, so this must fall back cleanly rather than crash."""
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=ART + 100, periods_per_week=1)]
    diagnosis = diagnose_infeasibility(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}))],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=ART + 100)],
        requirements=requirements,
    )
    assert diagnosis.code == "INFEASIBLE_NO_MAPPABLE_REQUIREMENT"
    assert diagnosis.requirement_indices == []
