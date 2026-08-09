import pytest

from app.services.timetable_solver import (
    SolverRequirement,
    SolverRoom,
    SolverSubject,
    SolverTeacher,
    UnsolvableError,
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
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)

    assert len(schedule) == sum(r.periods_per_week for r in requirements)
    for req in requirements:
        count = sum(1 for s in schedule if s.subject_id == req.subject_id)
        assert count == req.periods_per_week


def test_no_teacher_double_booked():
    teachers, rooms, subjects, requirements = _fixture()
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)

    seen = set()
    for s in schedule:
        key = (s.teacher_id, s.day_of_week, s.period_number)
        assert key not in seen, f"teacher double-booked: {key}"
        seen.add(key)


def test_no_room_double_booked():
    teachers, rooms, subjects, requirements = _fixture()
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)

    seen = set()
    for s in schedule:
        key = (s.room_id, s.day_of_week, s.period_number)
        assert key not in seen, f"room double-booked: {key}"
        seen.add(key)


def test_no_class_double_booked():
    teachers, rooms, subjects, requirements = _fixture()
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)

    seen = set()
    for s in schedule:
        key = (s.class_id, s.day_of_week, s.period_number)
        assert key not in seen, f"class double-booked: {key}"
        seen.add(key)


def test_only_qualified_teachers_assigned():
    teachers, rooms, subjects, requirements = _fixture()
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)

    subjects_by_teacher = {t.id: t.subject_ids for t in teachers}
    for s in schedule:
        assert s.subject_id in subjects_by_teacher[s.teacher_id]


def test_science_only_scheduled_in_lab():
    teachers, rooms, subjects, requirements = _fixture()
    schedule = generate_timetable(teachers=teachers, rooms=rooms, subjects=subjects, requirements=requirements)

    room_types = {r.id: r.room_type for r in rooms}
    for s in schedule:
        if s.subject_id == SCIENCE:
            assert room_types[s.room_id] == LAB


def test_teacher_unavailability_is_respected():
    teachers, rooms, subjects, requirements = _fixture()
    # Teacher 1 is the only teacher qualified for English (3/wk) and shares Math
    # (4/wk) with teacher 3. Restrict teacher 1 to 4 slots on day 0 - still enough
    # for English's 3/wk if the solver offloads Math onto teacher 3 instead.
    free_slots = {(0, 0), (0, 1), (0, 2), (0, 3)}
    restricted = [
        SolverTeacher(
            id=1,
            subject_ids=frozenset({MATH, ENGLISH}),
            unavailable=frozenset((d, p) for d in range(5) for p in range(6) if (d, p) not in free_slots),
        ),
        teachers[1],
        teachers[2],
    ]
    schedule = generate_timetable(teachers=restricted, rooms=rooms, subjects=subjects, requirements=requirements)
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
