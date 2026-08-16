import uuid
from datetime import time

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room, TeacherProfile, TeacherSubject, TeacherUnavailability, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user


def _override_user(role: str, user_id: int = 999, school_id: int | None = None):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role, school_id=school_id)

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_user_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def seed(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()

    school_class = SchoolClass(
        name="Grade 8 - A", academic_year="2026-27", grade_level=8, section="A", school_id=school.id
    )
    class_b = SchoolClass(
        name="Grade 8 - B", academic_year="2026-27", grade_level=8, section="B", school_id=school.id
    )
    db_session.add_all([school_class, class_b])

    subject = Subject(name="Math", school_id=school.id)
    db_session.add(subject)
    db_session.flush()

    room_a = Room(name="Room A", capacity=30, room_type="classroom", school_id=school.id)
    room_b = Room(name="Room B", capacity=30, room_type="classroom", school_id=school.id)
    lab = Room(name="Lab", capacity=30, room_type="lab", school_id=school.id)
    db_session.add_all([room_a, room_b, lab])

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    teacher1 = User(supabase_id=uuid.uuid4(), email=f"t1-{uuid.uuid4()}@example.com", role_id=teacher_role.id, school_id=school.id)
    teacher2 = User(supabase_id=uuid.uuid4(), email=f"t2-{uuid.uuid4()}@example.com", role_id=teacher_role.id, school_id=school.id)
    db_session.add_all([teacher1, teacher2])
    db_session.flush()

    # Every class must have a class teacher before /timetable/generate will run
    # (Check G in timetable_preflight.py) - assigned here so this fixture stays
    # a valid, generation-ready baseline; tests for the missing-class-teacher
    # case build their own class without one instead of mutating this shared seed.
    school_class.class_teacher_id = teacher1.id
    class_b.class_teacher_id = teacher2.id

    db_session.add_all(
        [
            TeacherProfile(teacher_id=teacher1.id, max_periods_per_week=30),
            TeacherProfile(teacher_id=teacher2.id, max_periods_per_week=30),
            TeacherSubject(teacher_id=teacher1.id, subject_id=subject.id),
        ]
    )

    slot = TimetableSlot(
        day_of_week=0,
        period_number=0,
        start_time=time(8, 0),
        end_time=time(8, 45),
        subject_id=subject.id,
        teacher_id=teacher1.id,
        class_id=school_class.id,
        room_id=room_a.id,
        academic_year="2026-27",
        is_active=True,
    )
    db_session.add(slot)
    db_session.commit()
    db_session.refresh(slot)

    return {
        "school": school,
        "class": school_class,
        "class_b": class_b,
        "subject": subject,
        "room_a": room_a,
        "room_b": room_b,
        "lab": lab,
        "teacher1": teacher1,
        "teacher2": teacher2,
        "slot": slot,
    }


def _generate_body(seed, **overrides):
    """The new real POST /timetable/generate shape's minimal valid body against
    the `seed` fixture above - teacher1 qualified for Math, both classes are
    Grade 8 sections A/B."""
    body = {
        "school_id": seed["school"].id,
        "academic_year": "2026-27",
        "grade_levels": [8],
        "sections_per_grade": 1,
        "days_per_week": 5,
        "periods_per_day": 6,
        "subjects": [{"subject_id": seed["subject"].id, "periods_per_week": 2, "lab_required": False}],
        "teacher_selections": [{"teacher_id": seed["teacher1"].id, "included": True}],
        "room_ids": [seed["room_a"].id],
    }
    body.update(overrides)
    return body


# --- RBAC: 401 with no token, 403 with wrong role ---


def test_generate_returns_401_without_token(client):
    resp = client.post("/timetable/generate", json={"school_id": 1, "academic_year": "2026-27"})
    assert resp.status_code == 401


def test_generate_returns_403_for_non_admin_role(client):
    _override_user("student")
    resp = client.post("/timetable/generate", json={"school_id": 1, "academic_year": "2026-27"})
    assert resp.status_code == 403


def test_update_returns_401_without_token(client):
    resp = client.put("/timetable/update", json={"slot_id": 1})
    assert resp.status_code == 401


def test_update_returns_403_for_non_admin_role(client):
    _override_user("teacher")
    resp = client.put("/timetable/update", json={"slot_id": 1})
    assert resp.status_code == 403


def test_active_returns_401_without_token(client):
    resp = client.get("/timetable/active", params={"academic_year": "2026-27"})
    assert resp.status_code == 401


def test_active_allows_every_role_when_scoped(client, seed):
    _override_user("teacher", user_id=seed["teacher1"].id)
    resp = client.get("/timetable/active", params={"academic_year": "2026-27"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["teacher_id"] == seed["teacher1"].id


# --- GET /timetable/active ---


def test_active_admin_can_filter_by_class(client, seed):
    _override_user("admin", school_id=seed["school"].id)
    resp = client.get(
        "/timetable/active", params={"academic_year": "2026-27", "class_id": seed["class"].id}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == seed["slot"].id


def test_active_teacher_only_sees_own_slots(client, seed):
    _override_user("teacher", user_id=seed["teacher2"].id)
    resp = client.get("/timetable/active", params={"academic_year": "2026-27"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_active_admin_never_sees_a_different_schools_slots(client, seed):
    """Regression test for a real cross-tenant leak: an admin/principal query
    used to have no school scoping at all, so ANY admin querying a matching
    academic_year saw every school's slots system-wide, with no class_id/
    teacher_id filter required to trigger it."""
    _override_user("admin", school_id=seed["school"].id + 999999)
    resp = client.get("/timetable/active", params={"academic_year": "2026-27"})
    assert resp.status_code == 200
    assert resp.json() == []


# --- PUT /timetable/update: conflict detection ---


def test_update_with_no_conflict_applies_change(client, seed):
    # Must be a real user id, not the default fake 999 - PUT /timetable/update now
    # writes an AuditLogEntry with actor_id=user.id, a real FK to users.id.
    _override_user("admin", user_id=seed["teacher1"].id, school_id=seed["school"].id)
    resp = client.put(
        "/timetable/update",
        json={"slot_id": seed["slot"].id, "day_of_week": 1, "period_number": 2, "room_id": seed["room_b"].id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["conflicts"] == []
    assert body["slot"]["day_of_week"] == 1
    assert body["slot"]["period_number"] == 2
    assert body["slot"]["room_id"] == seed["room_b"].id


def test_update_flags_teacher_conflict_without_overwriting(client, seed, db_session):
    # teacher1 already has a second slot at day=1/period=0 for a different class.
    other_slot = TimetableSlot(
        day_of_week=1,
        period_number=0,
        start_time=time(8, 0),
        end_time=time(8, 45),
        subject_id=seed["subject"].id,
        teacher_id=seed["teacher1"].id,
        class_id=seed["class"].id,
        room_id=seed["room_b"].id,
        academic_year="2026-27",
        is_active=True,
    )
    db_session.add(other_slot)
    db_session.commit()

    _override_user("principal", school_id=seed["school"].id)
    resp = client.put(
        "/timetable/update",
        json={"slot_id": seed["slot"].id, "day_of_week": 1, "period_number": 0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["slot"] is None
    assert any(c["type"] == "teacher" for c in body["conflicts"])

    # Original slot must be untouched - not silently overwritten.
    db_session.refresh(seed["slot"])
    assert seed["slot"].day_of_week == 0
    assert seed["slot"].period_number == 0


def test_update_returns_404_for_missing_slot(client, seed):
    _override_user("admin")
    resp = client.put("/timetable/update", json={"slot_id": 999999})
    assert resp.status_code == 404


def test_update_returns_404_for_a_real_slot_in_a_different_school(client, seed):
    """Regression test for a real cross-tenant write vulnerability: this
    endpoint used to look up a slot by id alone with no ownership check at
    all, so any admin/principal could reschedule ANY other school's real
    timetable slot."""
    _override_user("admin", school_id=seed["school"].id + 999999)
    resp = client.put("/timetable/update", json={"slot_id": seed["slot"].id, "day_of_week": 1})
    assert resp.status_code == 404


def test_update_rejects_a_real_teacher_room_subject_from_a_different_school(client, seed, db_session):
    """Regression test: teacher_id/room_id/subject_id overrides used to be
    checked only for existing ANYWHERE, so a real id belonging to a different
    school could be cross-assigned onto this school's slot."""
    other_school = School(name="Other School")
    db_session.add(other_school)
    db_session.flush()
    other_room = Room(name="Other Room", capacity=30, room_type="classroom", school_id=other_school.id)
    db_session.add(other_room)
    db_session.commit()
    db_session.refresh(other_room)

    _override_user("admin", school_id=seed["school"].id)
    resp = client.put("/timetable/update", json={"slot_id": seed["slot"].id, "room_id": other_room.id})
    assert resp.status_code == 400


def test_update_returns_clean_400_for_unknown_teacher_room_subject_override(client, seed):
    """Regression test: an unknown teacher_id/room_id/subject_id override used
    to reach the UPDATE and raise an unhandled IntegrityError (see the
    reliability audit's finding) instead of a clean 400."""
    _override_user("admin", school_id=seed["school"].id)
    for field, bad_id in [("teacher_id", 999999999), ("room_id", 999999999), ("subject_id", 999999999)]:
        resp = client.put("/timetable/update", json={"slot_id": seed["slot"].id, field: bad_id})
        assert resp.status_code == 400, f"{field} override should return 400, got {resp.status_code}"


# --- POST /timetable/generate: end-to-end DB wiring, new real request shape ---


def test_generate_creates_slots_and_deactivates_previous_run(client, seed, db_session):
    _override_user("admin", school_id=seed["school"].id)
    resp = client.post("/timetable/generate", json=_generate_body(seed))
    assert resp.status_code == 200
    body = resp.json()
    assert body["slots_created"] == 2
    assert len(body["slots"]) == 2
    for s in body["slots"]:
        assert s["teacher_id"] == seed["teacher1"].id
        assert s["class_id"] == seed["class"].id
        assert s["is_active"] is True

    # The seed fixture's pre-existing slot for this class/year is a previous run
    # and must be superseded, not left dangling alongside the new one.
    db_session.refresh(seed["slot"])
    assert seed["slot"].is_active is False


def test_generate_returns_422_when_unsolvable(client, seed):
    # teacher2 has no TeacherSubject row for Math at all - the only included
    # teacher is unqualified, so this is genuinely unsolvable.
    _override_user("principal", school_id=seed["school"].id)
    body = _generate_body(seed, teacher_selections=[{"teacher_id": seed["teacher2"].id, "included": True}])
    resp = client.post("/timetable/generate", json=body)
    assert resp.status_code == 422


def test_generate_returns_400_for_grade_with_insufficient_sections(client, seed):
    _override_user("admin", school_id=seed["school"].id)
    # sections_per_grade=3 but only 2 sections (A, B) are seeded for grade 8.
    resp = client.post("/timetable/generate", json=_generate_body(seed, sections_per_grade=3))
    assert resp.status_code == 400
    assert "grade 8" in resp.json()["detail"]


def test_generate_returns_400_for_unknown_subject_id(client, seed):
    _override_user("admin", school_id=seed["school"].id)
    body = _generate_body(seed, subjects=[{"subject_id": 999999, "periods_per_week": 2, "lab_required": False}])
    resp = client.post("/timetable/generate", json=body)
    assert resp.status_code == 400


def test_generate_returns_400_for_unknown_room_id(client, seed):
    _override_user("admin", school_id=seed["school"].id)
    resp = client.post("/timetable/generate", json=_generate_body(seed, room_ids=[999999]))
    assert resp.status_code == 400


def test_generate_returns_403_for_school_id_mismatch(client, seed):
    """Regression test for a real cross-tenant vulnerability: the request
    body's school_id used to be trusted outright, so an admin from a
    different school could generate (and thereby overwrite) another school's
    real timetable just by naming that school's id."""
    _override_user("admin", school_id=seed["school"].id + 999999)
    resp = client.post("/timetable/generate", json=_generate_body(seed))
    assert resp.status_code == 403


def test_generate_returns_400_for_a_real_subject_from_a_different_school(client, seed, db_session):
    """Regression test: subject_id was only checked for existing+active
    ANYWHERE, so a real subject belonging to a different school could be used
    to generate this school's timetable."""
    other_school = School(name="Other School")
    db_session.add(other_school)
    db_session.flush()
    other_subject = Subject(name="Other Math", school_id=other_school.id)
    db_session.add(other_subject)
    db_session.commit()
    db_session.refresh(other_subject)

    _override_user("admin", school_id=seed["school"].id)
    resp = client.post(
        "/timetable/generate",
        json=_generate_body(seed, subjects=[{"subject_id": other_subject.id, "periods_per_week": 2, "lab_required": False}]),
    )
    assert resp.status_code == 400


def test_generate_rejects_deactivated_subject(client, seed, db_session):
    seed["subject"].is_active = False
    db_session.commit()
    _override_user("admin", school_id=seed["school"].id)
    resp = client.post("/timetable/generate", json=_generate_body(seed))
    assert resp.status_code == 400


def test_generate_rejects_deactivated_room(client, seed, db_session):
    seed["room_a"].is_active = False
    db_session.commit()
    _override_user("admin", school_id=seed["school"].id)
    resp = client.post("/timetable/generate", json=_generate_body(seed))
    assert resp.status_code == 400


def test_generate_rejects_deactivated_teacher(client, seed, db_session):
    seed["teacher1"].is_active = False
    db_session.commit()
    _override_user("admin", school_id=seed["school"].id)
    resp = client.post("/timetable/generate", json=_generate_body(seed))
    assert resp.status_code == 400


def test_generate_rejects_deactivated_class(client, seed, db_session):
    seed["class"].is_active = False
    db_session.commit()
    _override_user("admin", school_id=seed["school"].id)
    # sections_per_grade=1 with grade 8's only remaining active section being class_b.
    resp = client.post("/timetable/generate", json=_generate_body(seed))
    assert resp.status_code == 200
    slots = resp.json()["slots"]
    assert all(s["class_id"] == seed["class_b"].id for s in slots)


def test_generate_with_negative_grade_level_for_lkg(client, seed, db_session):
    """LKG/UKG/Nursery support: grade_level=-2 (LKG, per the documented
    Nursery=-3/LKG=-2/UKG=-1 convention) must resolve and generate exactly like
    a positive grade_level - grade_levels: list[int] has no special-cased range."""
    lkg_class = SchoolClass(
        name="LKG - A", academic_year="2026-27", grade_level=-2, grade_label="LKG", school_id=seed["school"].id,
        class_teacher_id=seed["teacher1"].id,
    )
    db_session.add(lkg_class)
    db_session.commit()
    db_session.refresh(lkg_class)

    _override_user("admin", school_id=seed["school"].id)
    resp = client.post(
        "/timetable/generate",
        json=_generate_body(seed, grade_levels=[-2], sections_per_grade=1),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["slots_created"] == 2
    assert all(s["class_id"] == lkg_class.id for s in body["slots"])


def test_generate_returns_422_for_lab_required_with_no_lab_room_selected(client, seed):
    # lab_required=True but room_ids only includes a classroom, no lab - the
    # solver must fail honestly (422) rather than silently place it in the
    # wrong room type.
    _override_user("admin", school_id=seed["school"].id)
    body = _generate_body(
        seed,
        subjects=[{"subject_id": seed["subject"].id, "periods_per_week": 2, "lab_required": True}],
        room_ids=[seed["room_a"].id],
    )
    resp = client.post("/timetable/generate", json=body)
    assert resp.status_code == 422


def test_generate_returns_422_when_a_class_has_no_class_teacher(client, seed, db_session):
    seed["class"].class_teacher_id = None
    db_session.commit()

    _override_user("admin", school_id=seed["school"].id)
    resp = client.post("/timetable/generate", json=_generate_body(seed))
    assert resp.status_code == 422
    findings = resp.json()["detail"]["findings"]
    assert any(f["code"] == "CLASS_TEACHER_MISSING" for f in findings)


def test_generate_excludes_teacher_marked_not_included(client, seed, db_session):
    # teacher2 is also qualified for Math - if the exclusion is honored, every
    # generated slot must go to teacher1, never silently falling back to
    # teacher2 despite them being a real, otherwise-eligible candidate.
    db_session.add(TeacherSubject(teacher_id=seed["teacher2"].id, subject_id=seed["subject"].id))
    db_session.commit()

    _override_user("admin", school_id=seed["school"].id)
    body = _generate_body(
        seed,
        teacher_selections=[
            {"teacher_id": seed["teacher1"].id, "included": True},
            {"teacher_id": seed["teacher2"].id, "included": False},
        ],
    )
    resp = client.post("/timetable/generate", json=body)
    assert resp.status_code == 200
    slots = resp.json()["slots"]
    assert len(slots) == 2
    assert all(s["teacher_id"] == seed["teacher1"].id for s in slots)


def test_generate_respects_max_periods_per_week_override(client, seed, db_session):
    # Only teacher1 is qualified for Math across BOTH classes (2/wk each = 4
    # total demand). Override teacher1's cap to 2 - too low to cover both
    # classes alone with no other qualified teacher - genuinely infeasible.
    _override_user("admin", school_id=seed["school"].id)
    body = _generate_body(
        seed,
        grade_levels=[8],
        sections_per_grade=2,
        room_ids=[seed["room_a"].id, seed["room_b"].id],
        teacher_selections=[{"teacher_id": seed["teacher1"].id, "included": True, "max_periods_per_week_override": 2}],
    )
    resp = client.post("/timetable/generate", json=body)
    assert resp.status_code == 422


def test_generate_never_double_books_teacher_across_two_classes(client, seed, db_session):
    """The explicit cross-grade/cross-class guarantee: one teacher qualified for
    Math in BOTH Grade 8 sections (structurally identical to "qualified for both
    7th and 8th grade" - the solver has no grade concept at all, it only tracks
    class_id, so two different sections of the same grade exercise the exact
    same code path as two different grades would). Confirm the real persisted
    TimetableSlot rows never place this teacher in the same day/period twice
    across the two classes."""
    _override_user("admin", school_id=seed["school"].id)
    body = _generate_body(
        seed,
        grade_levels=[8],
        sections_per_grade=2,
        periods_per_day=3,
        days_per_week=5,
        subjects=[{"subject_id": seed["subject"].id, "periods_per_week": 4, "lab_required": False}],
        room_ids=[seed["room_a"].id, seed["room_b"].id],
    )
    resp = client.post("/timetable/generate", json=body)
    assert resp.status_code == 200
    slots = resp.json()["slots"]

    class_ids = {seed["class"].id, seed["class_b"].id}
    assert {s["class_id"] for s in slots} == class_ids
    assert len(slots) == 8  # 4/wk x 2 classes, all routed through the one qualified teacher

    seen_teacher_dp: set[tuple[int, int, int]] = set()
    for s in slots:
        assert s["teacher_id"] == seed["teacher1"].id  # only qualified teacher
        key = (s["teacher_id"], s["day_of_week"], s["period_number"])
        assert key not in seen_teacher_dp, f"teacher double-booked across classes: {key}"
        seen_teacher_dp.add(key)


# --- POST /timetable/generate: home_room_id pinning + warnings + objective reporting ---


def test_generate_pins_non_lab_periods_to_the_classs_home_room(client, seed, db_session):
    seed["class"].home_room_id = seed["room_b"].id
    db_session.commit()

    _override_user("admin", school_id=seed["school"].id)
    body = _generate_body(seed, room_ids=[seed["room_a"].id, seed["room_b"].id])
    resp = client.post("/timetable/generate", json=body)
    assert resp.status_code == 200
    slots = resp.json()["slots"]
    assert len(slots) > 0
    assert all(s["room_id"] == seed["room_b"].id for s in slots), "every non-lab period must stay in the home room"
    assert resp.json()["warnings"] == []


def test_generate_warns_when_a_resolved_class_has_no_home_room_id(client, seed):
    # seed["class"] has no home_room_id set by default.
    _override_user("admin", school_id=seed["school"].id)
    resp = client.post("/timetable/generate", json=_generate_body(seed))
    assert resp.status_code == 200
    warnings = resp.json()["warnings"]
    assert len(warnings) == 1
    assert str(seed["class"].id) in warnings[0]
    assert "home_room_id" in warnings[0]


def test_generate_response_includes_objective_weights_and_values(client, seed, db_session):
    seed["class"].home_room_id = seed["room_a"].id
    db_session.commit()

    _override_user("admin", school_id=seed["school"].id)
    resp = client.post("/timetable/generate", json=_generate_body(seed))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["objective_weights"].keys()) == {"same_day_clustering", "day_variance"}
    assert set(body["objective_values"].keys()) == {"same_day_clustering", "day_variance"}
    assert body["objective_weights"]["same_day_clustering"] > body["objective_weights"]["day_variance"]


# --- POST /timetable/preflight ------------------------------------------------


def test_preflight_reports_feasible_true_for_a_good_request(client, seed):
    _override_user("admin", school_id=seed["school"].id)
    resp = client.post("/timetable/preflight", json=_generate_body(seed))
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is True
    assert body["stage"] is None
    assert not any(f["severity"] == "error" for f in body["findings"])


def test_preflight_reports_structured_error_findings_without_touching_the_db(client, seed, db_session):
    # teacher2 has no TeacherSubject row for Math - genuinely no qualified
    # teacher for it, an empty pool (TEACHER_POOL_SHORTFALL with capacity=0).
    _override_user("admin", school_id=seed["school"].id)
    body = _generate_body(seed, teacher_selections=[{"teacher_id": seed["teacher2"].id, "included": True}])
    resp = client.post("/timetable/preflight", json=body)
    assert resp.status_code == 200
    result = resp.json()
    assert result["feasible"] is False
    assert result["stage"] == "preflight"
    codes = {f["code"] for f in result["findings"]}
    assert "TEACHER_POOL_SHORTFALL" in codes
    shortfall = next(f for f in result["findings"] if f["code"] == "TEACHER_POOL_SHORTFALL")
    assert shortfall["numbers"]["capacity"] == 0
    assert any(r["action"] == "add_teachers" for r in shortfall["remedies"])

    # A read-only check must never touch the database - the seed's own
    # pre-existing slot must be completely untouched, and no new slot must
    # have been created for this class (this is a real shared dev DB with
    # other schools' data in it, so assert scoped to this class, not a
    # global row count).
    db_session.refresh(seed["slot"])
    assert seed["slot"].is_active is True
    assert db_session.query(TimetableSlot).filter(TimetableSlot.class_id == seed["class"].id).count() == 1


def test_preflight_returns_403_for_school_id_mismatch(client, seed):
    _override_user("admin", school_id=seed["school"].id + 999999)
    resp = client.post("/timetable/preflight", json=_generate_body(seed))
    assert resp.status_code == 403


# --- POST /timetable/generate: structured 422 findings (preflight stage) -----


def test_generate_422_preflight_stage_reports_structured_findings(client, seed, db_session):
    # Same scenario as test_generate_respects_max_periods_per_week_override -
    # now asserting the STRUCTURED failure body, not just the status code.
    _override_user("admin", school_id=seed["school"].id)
    body = _generate_body(
        seed,
        grade_levels=[8],
        sections_per_grade=2,
        room_ids=[seed["room_a"].id, seed["room_b"].id],
        teacher_selections=[{"teacher_id": seed["teacher1"].id, "included": True, "max_periods_per_week_override": 2}],
    )
    resp = client.post("/timetable/generate", json=body)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["feasible"] is False
    assert detail["stage"] == "preflight"
    assert any(f["code"] == "TEACHER_POOL_SHORTFALL" and f["severity"] == "error" for f in detail["findings"])

    # A failed pre-flight must never touch the database at all - the solver
    # is never even called.
    db_session.refresh(seed["slot"])
    assert seed["slot"].is_active is True


# --- POST /timetable/generate: structured 422 findings (solve stage) --------


def test_generate_422_solve_stage_reports_the_conflicting_requirement(client, seed, db_session):
    """Constructed so pre-flight passes cleanly (raw free-slot count for the
    sole qualified teacher, 4, matches Math's 4 periods/week exactly) but the
    real CP-SAT model is still infeasible: all 4 free slots land on the same
    day, and the solver's own same-subject-per-day cap forbids using more
    than 1 of them for this class - a constraint-interaction case pure
    arithmetic can't predict, which is exactly what Part 2's diagnostic core
    exists for."""
    for day in range(1, 5):
        for period in range(4):
            db_session.add(
                TeacherUnavailability(
                    teacher_id=seed["teacher1"].id, day_of_week=day, period_number=period, academic_year="2026-27"
                )
            )
    db_session.commit()

    _override_user("admin", school_id=seed["school"].id)
    body = _generate_body(
        seed,
        periods_per_day=4,
        days_per_week=5,
        subjects=[{"subject_id": seed["subject"].id, "periods_per_week": 4, "lab_required": False}],
    )
    resp = client.post("/timetable/generate", json=body)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["feasible"] is False
    assert detail["stage"] == "solve"
    assert len(detail["findings"]) == 1
    finding = detail["findings"][0]
    assert finding["code"] == "SOLVE_CONSTRAINT_CONFLICT"
    assert "Math" in finding["message"] or str(seed["subject"].id) in finding["message"]


# --- Cross-run correctness: a teacher must never be double-booked across ----
# --- two SEPARATE /generate calls (one per grade), not just within one -----


def test_generate_never_double_books_a_teacher_across_two_separate_generate_calls(client, seed, db_session):
    """Regression test for a real correctness gap this task's Check F fix
    closes: generation happens one grade/section at a time (the UI only
    allows selecting one grade per run), and a teacher shared across two
    such runs used to have no cross-run booking awareness at all - nothing
    stopped a LATER call from double-booking them into a slot an EARLIER
    call already gave them for a different class.

    4 total slots/week (2 periods/day x 2 days), teacher1 the sole qualified
    teacher for Math. Run 1 (class A) takes 2 of the 4 slots. Run 2 (class B,
    after deactivating class A so it resolves instead) also needs 2 - if run
    2 is unaware of run 1's commitments it could (wrongly) reuse them; if
    aware, it must use the 2 remaining slots instead and still succeed. (The
    `seed` fixture already gives teacher1 a TeacherSubject row for Math.)"""

    _override_user("admin", school_id=seed["school"].id)

    body1 = _generate_body(
        seed,
        periods_per_day=2,
        days_per_week=2,
        subjects=[{"subject_id": seed["subject"].id, "periods_per_week": 2, "lab_required": False}],
    )
    resp1 = client.post("/timetable/generate", json=body1)
    assert resp1.status_code == 200

    # Deactivate class A so run 2's sections_per_grade=1 resolves class B
    # instead - same real pattern test_generate_rejects_deactivated_class uses.
    seed["class"].is_active = False
    db_session.commit()

    body2 = _generate_body(
        seed,
        periods_per_day=2,
        days_per_week=2,
        subjects=[{"subject_id": seed["subject"].id, "periods_per_week": 2, "lab_required": False}],
        room_ids=[seed["room_b"].id],
    )
    resp2 = client.post("/timetable/generate", json=body2)
    assert resp2.status_code == 200

    active_slots = db_session.query(TimetableSlot).filter(TimetableSlot.is_active.is_(True)).all()
    teacher1_slots = [s for s in active_slots if s.teacher_id == seed["teacher1"].id]
    assert len(teacher1_slots) == 4  # both runs' 2 periods each, all persisted
    seen = set()
    for s in teacher1_slots:
        key = (s.day_of_week, s.period_number)
        assert key not in seen, f"teacher double-booked across two separate /generate calls: {key}"
        seen.add(key)
    assert {s.class_id for s in teacher1_slots} == {seed["class"].id, seed["class_b"].id}
