from app.services.timetable_preflight import ClassInfo, run_preflight_checks
from app.services.timetable_solver import SolverRequirement, SolverRoom, SolverSubject, SolverTeacher

CLASS_A, CLASS_B = 100, 101
MATH, ENGLISH, SCIENCE, PHYSICS = 1, 2, 3, 4
CLASSROOM, LAB = "classroom", "lab"


def _errors(findings):
    return [f for f in findings if f.severity == "error"]


def _codes(findings):
    return {f.code for f in findings}


# --- Check A: section balance -----------------------------------------------


def test_check_a_reports_error_when_over_subscribed():
    requirements = [
        SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=6),
        SolverRequirement(class_id=CLASS_A, subject_id=ENGLISH, periods_per_week=5),
    ]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH, ENGLISH}), max_periods_per_week=20)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH), SolverSubject(id=ENGLISH)],
        requirements=requirements,
        classes=[ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1)],
        days=5,
        periods_per_day=2,
    )
    over = [f for f in findings if f.code == "SECTION_OVER_SUBSCRIBED"]
    assert len(over) == 1
    f = over[0]
    assert f.severity == "error"
    assert f.numbers == {"required": 11, "available": 10, "difference": 1}
    assert any(r.action == "reduce_periods" and r.quantity == 1 for r in f.remedies)


def test_check_a_reports_warning_when_under_subscribed():
    requirements = [
        SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=3),
        SolverRequirement(class_id=CLASS_A, subject_id=ENGLISH, periods_per_week=2),
    ]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH, ENGLISH}), max_periods_per_week=20)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH), SolverSubject(id=ENGLISH)],
        requirements=requirements,
        classes=[ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1)],
        days=5,
        periods_per_day=2,
    )
    under = [f for f in findings if f.code == "SECTION_UNDER_SUBSCRIBED"]
    assert len(under) == 1
    assert under[0].severity == "warning"
    assert under[0].numbers == {"required": 5, "available": 10, "difference": -5}
    assert _errors(findings) == []


# --- Check B: teacher pool capacity -----------------------------------------


def test_check_b_reports_naive_per_subject_shortfall():
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=10)]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}), max_periods_per_week=5)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH)],
        requirements=requirements,
        classes=[ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1)],
        days=5,
        periods_per_day=2,
        subject_names={MATH: "Math"},
    )
    shortfall = [f for f in findings if f.code == "TEACHER_POOL_SHORTFALL"]
    assert len(shortfall) == 1
    f = shortfall[0]
    assert f.subject == "Math"
    assert f.numbers == {"demand": 10, "capacity": 5, "shortfall": 5, "additional_teachers_needed": 1}
    assert any(r.action == "add_teachers" and r.quantity == 1 for r in f.remedies)
    assert any(r.action == "reduce_periods" and r.quantity == 5 for r in f.remedies)


def test_check_b_reports_overlap_caused_shortfall_that_naive_per_subject_check_would_miss():
    """Both subjects pass in isolation (10 <= 15 each) - only jointly, since
    they share their sole qualified teacher, does 20 > 15 become infeasible.
    A naive independent-sum check would wrongly pass this input."""
    requirements = [
        SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=10),
        SolverRequirement(class_id=CLASS_A, subject_id=ENGLISH, periods_per_week=10),
    ]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH, ENGLISH}), max_periods_per_week=15)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH), SolverSubject(id=ENGLISH)],
        requirements=requirements,
        classes=[ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1)],
        days=5,
        periods_per_day=4,
        subject_names={MATH: "Math", ENGLISH: "English"},
    )
    shortfall = {f.subject: f for f in findings if f.code == "TEACHER_POOL_SHORTFALL"}
    # Which specific subject absorbs the shortfall in the max-flow solution is
    # not unique (any split of the 15 available periods across the two <=10
    # demands is a valid max-flow) - but at least one must be reported, and
    # the total unmet demand across whichever is/are reported must equal the
    # true joint deficit (20 total demand - 15 shared capacity = 5), proving
    # the overlap was actually detected rather than silently passed by a
    # naive independent per-subject sum.
    assert shortfall, "overlap-caused shortfall must be reported for at least one contending subject"
    assert set(shortfall) <= {"Math", "English"}
    assert sum(f.numbers["shortfall"] for f in shortfall.values()) == 5
    for name, f in shortfall.items():
        other = "English" if name == "Math" else "Math"
        assert other in f.message


def test_check_b_reports_warning_for_tight_pool_that_still_passes():
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=9)]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}), max_periods_per_week=10)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH)],
        requirements=requirements,
        classes=[ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1)],
        days=1,
        periods_per_day=9,
        subject_names={MATH: "Math"},
    )
    tight = [f for f in findings if f.code == "TEACHER_POOL_TIGHT"]
    assert len(tight) == 1
    assert tight[0].severity == "warning"
    assert tight[0].numbers == {"demand": 9, "capacity": 10}
    assert _errors(findings) == []


# --- Check C: room concurrency ----------------------------------------------


def test_check_c_reports_home_room_collision():
    requirements = [
        SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=3, home_room_id=500),
        SolverRequirement(class_id=CLASS_B, subject_id=MATH, periods_per_week=3, home_room_id=500),
    ]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}), max_periods_per_week=20)],
        rooms=[SolverRoom(id=500, room_type=CLASSROOM), SolverRoom(id=501, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH)],
        requirements=requirements,
        classes=[
            ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=500, class_teacher_id=1),
            ClassInfo(id=CLASS_B, name="Grade 1-B", home_room_id=500, class_teacher_id=1),
        ],
        days=6,
        periods_per_day=10,
    )
    collision = [f for f in findings if f.code == "ROOM_HOME_COLLISION"]
    assert len(collision) == 1
    assert collision[0].numbers == {"colliding_sections": 2}
    assert collision[0].details["class_ids"] == [CLASS_A, CLASS_B]
    assert _errors(findings) == collision


def test_check_c_reports_room_concurrency_shortfall():
    requirements = [
        SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=3),
        SolverRequirement(class_id=CLASS_B, subject_id=MATH, periods_per_week=3),
    ]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}), max_periods_per_week=20)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],  # only 1 room for 2 sections
        subjects=[SolverSubject(id=MATH)],
        requirements=requirements,
        classes=[
            ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=None, class_teacher_id=1),
            ClassInfo(id=CLASS_B, name="Grade 1-B", home_room_id=None, class_teacher_id=1),
        ],
        days=6,
        periods_per_day=10,
    )
    shortfall = [f for f in findings if f.code == "ROOM_CONCURRENCY_SHORTFALL"]
    assert len(shortfall) == 1
    assert shortfall[0].numbers == {"sections_needing_rooms": 2, "rooms_available": 1, "shortfall": 1}
    assert any(r.action == "add_rooms" and r.quantity == 1 for r in shortfall[0].remedies)


# --- Check D: lab concurrency -----------------------------------------------


def test_check_d_reports_weekly_lab_capacity_shortfall():
    requirements = [
        SolverRequirement(class_id=CLASS_A, subject_id=SCIENCE, periods_per_week=60, home_room_id=1),
        SolverRequirement(class_id=CLASS_B, subject_id=SCIENCE, periods_per_week=60, home_room_id=2),
    ]
    findings = run_preflight_checks(
        teachers=[
            SolverTeacher(id=1, subject_ids=frozenset({SCIENCE}), max_periods_per_week=999),
            SolverTeacher(id=2, subject_ids=frozenset({SCIENCE}), max_periods_per_week=999),
        ],
        rooms=[
            SolverRoom(id=1, room_type=CLASSROOM),
            SolverRoom(id=2, room_type=CLASSROOM),
            SolverRoom(id=3, room_type=LAB),
        ],
        subjects=[SolverSubject(id=SCIENCE, required_room_type=LAB)],
        requirements=requirements,
        classes=[
            ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1),
            ClassInfo(id=CLASS_B, name="Grade 1-B", home_room_id=2, class_teacher_id=1),
        ],
        days=5,
        periods_per_day=20,  # total_slots = 100, well above any one teacher's demand (60)
    )
    shortfall = [f for f in findings if f.code == "LAB_CAPACITY_SHORTFALL"]
    assert len(shortfall) == 1
    f = shortfall[0]
    # demand = 120 (60/wk x 2 sections), capacity = 1 lab room x 100 slots/wk = 100
    assert f.numbers == {"demand": 120, "capacity": 100, "shortfall": 20, "additional_labs_needed": 1}
    assert any(r.action == "add_labs" and r.quantity == 1 for r in f.remedies)
    # Teacher/room checks for this fixture must stay clean - isolates Check D.
    assert "TEACHER_POOL_SHORTFALL" not in _codes(findings)
    assert "TEACHER_AVAILABILITY_SHORTFALL" not in _codes(findings)
    assert "ROOM_CONCURRENCY_SHORTFALL" not in _codes(findings)


def test_check_d_reports_peak_concurrency_shortfall_distinct_from_weekly_total():
    """One class needs two different lab subjects whose combined demand
    exceeds the week's total slots - no number of extra lab rooms fixes this,
    since the class itself can only be in one lab at a time. 3 lab rooms
    (generous) keeps the plain weekly aggregate (3 x 10 = 30) nowhere near
    binding, proving this is a genuinely distinct, tighter failure mode."""
    requirements = [
        SolverRequirement(class_id=CLASS_A, subject_id=SCIENCE, periods_per_week=6, home_room_id=1),
        SolverRequirement(class_id=CLASS_A, subject_id=PHYSICS, periods_per_week=6, home_room_id=1),
    ]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({SCIENCE, PHYSICS}), max_periods_per_week=999)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)] + [SolverRoom(id=100 + i, room_type=LAB) for i in range(3)],
        subjects=[SolverSubject(id=SCIENCE, required_room_type=LAB), SolverSubject(id=PHYSICS, required_room_type=LAB)],
        requirements=requirements,
        classes=[ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1)],
        days=5,
        periods_per_day=2,  # total_slots = 10
    )
    peak = [f for f in findings if f.code == "LAB_PEAK_CONCURRENCY_SHORTFALL"]
    assert len(peak) == 1
    assert peak[0].numbers["demand"] == 12
    assert peak[0].numbers["capacity"] == 10  # bounded by the class's own 10 total slots, not 3 labs x 10
    assert peak[0].numbers["shortfall"] == 2
    # Check A also legitimately fires here (12 required > 10 available for this
    # class) - both are true and both must be reported together.
    assert "SECTION_OVER_SUBSCRIBED" in _codes(findings)


# --- Check E: per-teacher availability --------------------------------------


def test_check_e_reports_teacher_availability_shortfall():
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=8, home_room_id=1)]
    blocked = frozenset((0, p) for p in range(3, 8))  # 5 of 8 slots blocked
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}), unavailable=blocked, max_periods_per_week=20)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH)],
        requirements=requirements,
        classes=[ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1)],
        days=1,
        periods_per_day=8,
        teacher_names={1: "T. Rao"},
    )
    shortfall = [f for f in findings if f.code == "TEACHER_AVAILABILITY_SHORTFALL"]
    assert len(shortfall) == 1
    f = shortfall[0]
    assert f.numbers == {"demand": 3, "effective_availability": 3, "blocked_slot_count": 5}
    assert "T. Rao" in f.message
    assert "TEACHER_POOL_SHORTFALL" not in _codes(findings)


# --- Check F: cross-run collisions ------------------------------------------


def test_check_f_reports_cross_run_collision():
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=5, home_room_id=1)]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}), max_periods_per_week=20)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH)],
        requirements=requirements,
        classes=[ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1)],
        days=1,
        periods_per_day=5,
        teacher_names={1: "T. Rao"},
        existing_bookings_by_teacher={1: 3},
    )
    collision = [f for f in findings if f.code == "CROSS_RUN_COLLISION"]
    assert len(collision) == 1
    f = collision[0]
    assert f.numbers == {"periods_committed_elsewhere": 3, "periods_free": 2, "periods_needed": 5, "shortfall": 3}
    assert "T. Rao" in f.message
    assert "TEACHER_AVAILABILITY_SHORTFALL" not in _codes(findings)
    assert "TEACHER_POOL_SHORTFALL" not in _codes(findings)


def test_check_f_is_silent_when_no_teacher_has_cross_run_bookings():
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=5, home_room_id=1)]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}), max_periods_per_week=20)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH)],
        requirements=requirements,
        classes=[ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1)],
        days=1,
        periods_per_day=5,
    )
    assert "CROSS_RUN_COLLISION" not in _codes(findings)


# --- Check G: every class must have a class teacher --------------------------


def test_check_g_reports_error_when_a_class_has_no_class_teacher():
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=3, home_room_id=1)]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}), max_periods_per_week=20)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH)],
        requirements=requirements,
        classes=[ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=None)],
        days=5,
        periods_per_day=2,
    )
    missing = [f for f in findings if f.code == "CLASS_TEACHER_MISSING"]
    assert len(missing) == 1
    f = missing[0]
    assert f.severity == "error"
    assert f.numbers == {"classes_missing_teacher": 1}
    assert f.details["class_ids"] == [CLASS_A]
    assert "Grade 1-A" in f.message
    assert any(r.action == "assign_class_teacher" and r.quantity == 1 for r in f.remedies)


def test_check_g_reports_every_class_missing_a_teacher_together():
    requirements = [
        SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=3, home_room_id=1),
        SolverRequirement(class_id=CLASS_B, subject_id=MATH, periods_per_week=3, home_room_id=2),
    ]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}), max_periods_per_week=20)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM), SolverRoom(id=2, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH)],
        requirements=requirements,
        classes=[
            ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=None),
            ClassInfo(id=CLASS_B, name="Grade 1-B", home_room_id=2, class_teacher_id=None),
        ],
        days=5,
        periods_per_day=2,
    )
    missing = [f for f in findings if f.code == "CLASS_TEACHER_MISSING"]
    assert len(missing) == 1
    assert missing[0].numbers == {"classes_missing_teacher": 2}
    assert set(missing[0].details["class_ids"]) == {CLASS_A, CLASS_B}


def test_check_g_silent_when_every_class_has_a_class_teacher():
    requirements = [SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=3, home_room_id=1)]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}), max_periods_per_week=20)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH)],
        requirements=requirements,
        classes=[ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1)],
        days=5,
        periods_per_day=2,
    )
    assert "CLASS_TEACHER_MISSING" not in _codes(findings)


# --- Combined: multiple checks failing together -----------------------------


def test_multiple_checks_fail_simultaneously_and_all_are_reported():
    requirements = [
        SolverRequirement(class_id=CLASS_A, subject_id=MATH, periods_per_week=10, home_room_id=1),
        SolverRequirement(class_id=CLASS_A, subject_id=ENGLISH, periods_per_week=5, home_room_id=1),
        SolverRequirement(class_id=CLASS_B, subject_id=MATH, periods_per_week=10, home_room_id=1),
        SolverRequirement(class_id=CLASS_B, subject_id=ENGLISH, periods_per_week=5, home_room_id=1),
    ]
    findings = run_preflight_checks(
        teachers=[SolverTeacher(id=1, subject_ids=frozenset({MATH}), max_periods_per_week=8)],
        rooms=[SolverRoom(id=1, room_type=CLASSROOM)],
        subjects=[SolverSubject(id=MATH), SolverSubject(id=ENGLISH)],
        requirements=requirements,
        classes=[
            ClassInfo(id=CLASS_A, name="Grade 1-A", home_room_id=1, class_teacher_id=1),
            ClassInfo(id=CLASS_B, name="Grade 1-B", home_room_id=1, class_teacher_id=1),
        ],
        days=5,
        periods_per_day=2,
        subject_names={MATH: "Math", ENGLISH: "English"},
    )
    codes = _codes(findings)
    assert "SECTION_OVER_SUBSCRIBED" in codes
    assert "TEACHER_POOL_SHORTFALL" in codes
    assert "ROOM_HOME_COLLISION" in codes
    # No qualified teacher exists for English at all in this fixture, so its
    # pool is empty rather than merely short - still must surface as a
    # shortfall (capacity 0), not be silently skipped.
    assert any(f.code == "TEACHER_POOL_SHORTFALL" and f.subject == "English" for f in findings)
