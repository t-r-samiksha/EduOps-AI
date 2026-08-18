import uuid

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.risk import Intervention, RiskFlag
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int = 999, school_id: int | None = None):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role, school_id=school_id)

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_user_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _make_user(db_session, role_row, prefix, school):
    email = f"{prefix}-{uuid.uuid4()}@example.com"
    user = User(supabase_id=uuid.uuid4(), email=email, full_name=prefix, role_id=role_row.id, school_id=school.id)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def seed(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    parent_role = db_session.query(Role).filter(Role.name == "parent").one()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    principal_role = db_session.query(Role).filter(Role.name == "principal").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    principal_user = _make_user(db_session, principal_role, "principal", school)
    teacher = _make_user(db_session, teacher_role, "teacher", school)
    other_teacher = _make_user(db_session, teacher_role, "other-teacher", school)

    school_class = SchoolClass(name="Grade 8 - A", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=teacher.id)
    other_class = SchoolClass(name="Grade 9 - B", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=other_teacher.id)
    db_session.add_all([school_class, other_class])
    db_session.flush()

    flagged_student = _make_user(db_session, student_role, "flagged-student", school)
    other_student = _make_user(db_session, student_role, "other-student", school)
    db_session.add_all(
        [
            Enrollment(student_id=flagged_student.id, class_id=school_class.id, subject_id=None, is_primary=True),
            Enrollment(student_id=other_student.id, class_id=school_class.id, subject_id=None, is_primary=True),
        ]
    )

    linked_parent = _make_user(db_session, parent_role, "linked-parent", school)
    unlinked_parent = _make_user(db_session, parent_role, "unlinked-parent", school)
    db_session.add(ParentStudent(parent_id=linked_parent.id, student_id=flagged_student.id))

    db_session.commit()

    return {
        "school": school,
        "class": school_class,
        "other_class": other_class,
        "admin_user": admin_user,
        "principal_user": principal_user,
        "teacher": teacher,
        "other_teacher": other_teacher,
        "flagged_student": flagged_student,
        "other_student": other_student,
        "linked_parent": linked_parent,
        "unlinked_parent": unlinked_parent,
    }


# --- RBAC: 401 no token, 403 wrong role ---


def test_flag_401_without_token(client):
    resp = client.post("/risk/flag", json={"student_id": 1, "risk_level": "high", "reasons": ["test"]})
    assert resp.status_code == 401


def test_flag_403_for_student_role(client):
    _override_user("student")
    resp = client.post("/risk/flag", json={"student_id": 1, "risk_level": "high", "reasons": ["test"]})
    assert resp.status_code == 403


def test_flagged_401_without_token(client):
    resp = client.get("/risk/flagged")
    assert resp.status_code == 401


def test_flagged_403_for_student_role(client):
    _override_user("student")
    resp = client.get("/risk/flagged")
    assert resp.status_code == 403


def test_acknowledge_401_without_token(client):
    resp = client.put("/risk/1/acknowledge")
    assert resp.status_code == 401


def test_acknowledge_403_for_student_role(client):
    _override_user("student")
    resp = client.put("/risk/1/acknowledge")
    assert resp.status_code == 403


def test_intervention_401_without_token(client):
    resp = client.post("/risk/1/intervention", json={"note": "x", "action_taken": "y"})
    assert resp.status_code == 401


def test_intervention_403_for_student_role(client):
    _override_user("student")
    resp = client.post("/risk/1/intervention", json={"note": "x", "action_taken": "y"})
    assert resp.status_code == 403


def test_resolve_401_without_token(client):
    resp = client.put("/risk/1/resolve")
    assert resp.status_code == 401


def test_resolve_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.put("/risk/1/resolve")
    assert resp.status_code == 403


def test_early_warning_401_without_token(client):
    resp = client.get("/admin/early-warning/students")
    assert resp.status_code == 401


def test_early_warning_403_for_parent_role(client):
    _override_user("parent")
    resp = client.get("/admin/early-warning/students")
    assert resp.status_code == 403


# --- POST /risk/flag ---


def test_create_flag_validation_errors(client, seed):
    _override_user("teacher", user_id=seed["teacher"].id)

    resp = client.post("/risk/flag", json={"student_id": seed["flagged_student"].id, "risk_level": "urgent", "reasons": ["x"]})
    assert resp.status_code == 400

    resp = client.post("/risk/flag", json={"student_id": seed["flagged_student"].id, "risk_level": "high", "reasons": []})
    assert resp.status_code == 400

    resp = client.post("/risk/flag", json={"student_id": 999999, "risk_level": "high", "reasons": ["x"]})
    assert resp.status_code == 404


def test_create_flag_returns_alert_ready_enrichment(client, seed):
    _override_user("teacher", user_id=seed["teacher"].id)
    resp = client.post(
        "/risk/flag",
        json={"student_id": seed["flagged_student"].id, "risk_level": "high", "reasons": ["teacher observation: withdrawn"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["student_id"] == seed["flagged_student"].id
    assert body["risk_level"] == "high"
    assert body["score"] == 0.8
    assert body["status"] == "open"
    # Alert-ready enrichment - the integration point for Person C's future notifier.
    assert body["class_id"] == seed["class"].id
    assert body["class_name"] == seed["class"].name
    assert body["homeroom_teacher_id"] == seed["teacher"].id
    assert body["parent_ids"] == [seed["linked_parent"].id]
    assert body["student_name"] == seed["flagged_student"].full_name


def test_create_flag_accepts_score_override(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        "/risk/flag", json={"student_id": seed["flagged_student"].id, "risk_level": "medium", "reasons": ["x"], "score": 0.42}
    )
    assert resp.status_code == 200
    assert resp.json()["score"] == 0.42


# --- Full flow: flag -> acknowledge -> intervention -> resolve ---


def test_full_flag_lifecycle(client, seed):
    _override_user("teacher", user_id=seed["teacher"].id)
    resp = client.post(
        "/risk/flag", json={"student_id": seed["flagged_student"].id, "risk_level": "high", "reasons": ["falling grades"]}
    )
    flag_id = resp.json()["id"]
    assert resp.json()["status"] == "open"

    resp = client.put(f"/risk/{flag_id}/acknowledge")
    assert resp.status_code == 200
    assert resp.json()["status"] == "acknowledged"

    resp = client.put(f"/risk/{flag_id}/acknowledge")
    assert resp.status_code == 400  # already acknowledged

    resp = client.post(f"/risk/{flag_id}/intervention", json={"note": "Called parent to discuss", "action_taken": "called_parent"})
    assert resp.status_code == 200
    intervention_body = resp.json()
    assert intervention_body["risk_flag_id"] == flag_id
    assert intervention_body["created_by"] == seed["teacher"].id
    assert intervention_body["action_taken"] == "called_parent"

    # school_id passed explicitly: resolving now requires the flag's student to be in the
    # caller's school (the cross-tenant fix), matching what GET /risk/flagged already did
    # for this role. A principal with no school sees no flags and so can resolve none.
    _override_user("principal", user_id=seed["principal_user"].id, school_id=seed["school"].id)
    resp = client.put(f"/risk/{flag_id}/resolve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["resolved_by"] == seed["principal_user"].id
    assert body["resolved_at"] is not None

    resp = client.put(f"/risk/{flag_id}/resolve")
    assert resp.status_code == 400  # already resolved


def test_acknowledge_returns_404_for_missing_flag(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put("/risk/999999/acknowledge")
    assert resp.status_code == 404


def test_intervention_returns_404_for_missing_flag(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/risk/999999/intervention", json={"note": "x", "action_taken": "y"})
    assert resp.status_code == 404


def test_intervention_rejects_empty_note(client, db_session, seed):
    flag = RiskFlag(student_id=seed["flagged_student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(flag)
    db_session.commit()
    db_session.refresh(flag)

    _override_user("teacher", user_id=seed["teacher"].id)
    resp = client.post(f"/risk/{flag.id}/intervention", json={"note": "   ", "action_taken": "called_parent"})
    assert resp.status_code == 400


def test_resolve_returns_404_for_missing_flag(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put("/risk/999999/resolve")
    assert resp.status_code == 404


# --- GET /risk/flagged: role scoping ---


@pytest.fixture()
def existing_flag(db_session, seed):
    flag = RiskFlag(student_id=seed["flagged_student"].id, risk_level="high", score=0.8, reasons=["attendance below threshold"], status="open")
    db_session.add(flag)
    db_session.commit()
    db_session.refresh(flag)
    return flag


def test_flagged_teacher_sees_own_class(client, seed, existing_flag):
    _override_user("teacher", user_id=seed["teacher"].id)
    resp = client.get("/risk/flagged")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["student_id"] == seed["flagged_student"].id


def test_flagged_teacher_does_not_see_other_teachers_class(client, seed, existing_flag):
    _override_user("teacher", user_id=seed["other_teacher"].id)
    resp = client.get("/risk/flagged")
    assert resp.status_code == 200
    assert resp.json() == []


def test_flagged_teacher_403_for_other_class_id_filter(client, seed, existing_flag):
    _override_user("teacher", user_id=seed["other_teacher"].id)
    resp = client.get("/risk/flagged", params={"class_id": seed["class"].id})
    assert resp.status_code == 403


def test_flagged_admin_sees_all(client, seed, existing_flag):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/risk/flagged")
    assert resp.status_code == 200
    assert any(f["student_id"] == seed["flagged_student"].id for f in resp.json())


def test_flagged_admin_never_sees_a_different_schools_flags(client, db_session, seed, existing_flag):
    """Regression test for a real cross-tenant leak: GET /risk/flagged used to
    apply NO school scoping at all for admin/principal beyond an explicit
    class_id/student_id filter, so any admin querying with no filters saw
    every school's flagged students - only visible (and only actually found)
    once two real schools existed in the same live DB at once."""
    other_school = School(name="Other School")
    db_session.add(other_school)
    db_session.commit()
    db_session.refresh(other_school)

    _override_user("admin", user_id=999999, school_id=other_school.id)
    resp = client.get("/risk/flagged")
    assert resp.status_code == 200
    assert resp.json() == []


def test_flagged_linked_parent_sees_own_child(client, seed, existing_flag):
    _override_user("parent", user_id=seed["linked_parent"].id)
    resp = client.get("/risk/flagged", params={"student_id": seed["flagged_student"].id})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["student_id"] == seed["flagged_student"].id


def test_flagged_unlinked_parent_403(client, seed, existing_flag):
    _override_user("parent", user_id=seed["unlinked_parent"].id)
    resp = client.get("/risk/flagged", params={"student_id": seed["flagged_student"].id})
    assert resp.status_code == 403


def test_flagged_parent_requires_student_id(client, seed, existing_flag):
    _override_user("parent", user_id=seed["linked_parent"].id)
    resp = client.get("/risk/flagged")
    assert resp.status_code == 400


def test_flagged_excludes_resolved_by_default(client, db_session, seed, existing_flag):
    # admin/principal are now scoped to their own school (see the cross-tenant
    # regression test above) - this test's own fixture school/class is enough
    # to isolate it from any other real data in this live DB.
    existing_flag.status = "resolved"
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/risk/flagged", params={"class_id": seed["class"].id})
    assert resp.status_code == 200
    assert resp.json() == []

    resp = client.get("/risk/flagged", params={"class_id": seed["class"].id, "status": "resolved"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_flagged_filters_by_risk_level(client, db_session, seed, existing_flag):
    low_flag = RiskFlag(student_id=seed["other_student"].id, risk_level="low", score=0.1, reasons=["fine"], status="open")
    db_session.add(low_flag)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/risk/flagged", params={"class_id": seed["class"].id, "risk_level": "high"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["risk_level"] == "high"


# --- GET /admin/early-warning/students ---


def test_early_warning_returns_items_shape(client, seed, existing_flag):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/early-warning/students", params={"class_id": seed["class"].id})
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert set(item.keys()) == {"student_id", "risk_level", "reasons", "flagged_at"}
    assert item["student_id"] == seed["flagged_student"].id


def test_early_warning_teacher_scoped_to_own_class(client, seed, existing_flag):
    _override_user("teacher", user_id=seed["other_teacher"].id)
    resp = client.get("/admin/early-warning/students")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_early_warning_admin_never_sees_a_different_schools_flags(client, db_session, seed, existing_flag):
    """Same real cross-tenant leak as GET /risk/flagged, in this sibling
    endpoint - admin/principal had no school scoping here either."""
    other_school = School(name="Other School 2")
    db_session.add(other_school)
    db_session.commit()
    db_session.refresh(other_school)

    _override_user("admin", user_id=999999, school_id=other_school.id)
    resp = client.get("/admin/early-warning/students")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# --- Subject teachers, not just homeroom teachers ---


def _make_subject_teacher_slot(db_session, seed, teacher):
    """Give `teacher` a timetable slot in seed["class"] without making them its homeroom.

    This is the shape that was broken: a real subject teacher for a section they do not own.
    """
    from datetime import time

    from app.models.subject import Subject
    from app.models.timetable import Room, TimetableSlot

    subject = Subject(name=f"Subject-{uuid.uuid4().hex[:6]}", school_id=seed["school"].id)
    room = Room(
        name=f"Room-{uuid.uuid4().hex[:6]}",
        school_id=seed["school"].id,
        room_type="classroom",
        capacity=30,
    )
    db_session.add_all([subject, room])
    db_session.flush()

    # TimetableSlot carries no school_id - it is derived through class/subject/room - and
    # start_time/end_time are NOT NULL.
    slot = TimetableSlot(
        class_id=seed["class"].id,
        subject_id=subject.id,
        teacher_id=teacher.id,
        room_id=room.id,
        day_of_week=0,
        period_number=1,
        start_time=time(9, 0),
        end_time=time(9, 45),
        academic_year=ACADEMIC_YEAR,
        is_active=True,
    )
    db_session.add(slot)
    db_session.commit()
    return slot


def test_subject_teacher_sees_flags_for_students_they_teach(client, seed, db_session):
    """A teacher who teaches a section but is NOT its homeroom teacher must see its flags.

    THE BUG: risk scoping was homeroom-only (`SchoolClass.class_teacher_id == teacher_id`),
    so a subject teacher's Early-Warning page was always empty - and a teacher with no
    homeroom at all (normal) saw nothing anywhere. It rendered "No flagged students" rather
    than an error, so a permissions gap read as good news.
    """
    flag = RiskFlag(
        student_id=seed["flagged_student"].id,
        risk_level="high",
        score=0.8,
        reasons=["attendance below threshold"],
        status="open",
    )
    db_session.add(flag)
    db_session.commit()

    # other_teacher is homeroom of other_class, NOT of seed["class"] - so pre-fix they saw
    # nothing here. Give them a real teaching slot in seed["class"].
    _make_subject_teacher_slot(db_session, seed, seed["other_teacher"])

    _override_user("teacher", user_id=seed["other_teacher"].id, school_id=seed["school"].id)
    resp = client.get("/risk/flagged")
    assert resp.status_code == 200
    ids = [f["student_id"] for f in resp.json()]
    assert seed["flagged_student"].id in ids, (
        "subject teacher cannot see a flag for a student they teach"
    )


def test_teacher_who_neither_owns_nor_teaches_the_class_sees_nothing(client, seed, db_session):
    """The widened scope must not become 'every teacher sees everything'."""
    flag = RiskFlag(
        student_id=seed["flagged_student"].id,
        risk_level="high",
        score=0.8,
        reasons=["attendance below threshold"],
        status="open",
    )
    db_session.add(flag)
    db_session.commit()

    # No homeroom in seed["class"], and no timetable slot there either.
    _override_user("teacher", user_id=seed["other_teacher"].id, school_id=seed["school"].id)
    resp = client.get("/risk/flagged")
    assert resp.status_code == 200
    assert [f["student_id"] for f in resp.json()] == []


def test_subject_teacher_can_act_on_the_flag_they_can_see(client, seed, db_session):
    """Seeing a flag and acting on it must use the same rule, or the page shows dead buttons."""
    flag = RiskFlag(
        student_id=seed["flagged_student"].id,
        risk_level="medium",
        score=0.5,
        reasons=["grades dipping"],
        status="open",
    )
    db_session.add(flag)
    db_session.commit()
    flag_id = flag.id

    _make_subject_teacher_slot(db_session, seed, seed["other_teacher"])
    _override_user("teacher", user_id=seed["other_teacher"].id, school_id=seed["school"].id)

    assert client.put(f"/risk/{flag_id}/acknowledge").status_code == 200
    resp = client.post(
        f"/risk/{flag_id}/intervention",
        json={"note": "Spoke to the student after class.", "action_taken": "teacher meeting"},
    )
    assert resp.status_code == 200, resp.text


# --- Interventions are readable, and scoped ---


def test_logged_intervention_can_be_read_back(client, seed, db_session):
    """POST /risk/{id}/intervention had NO read counterpart - it was write-only.

    A teacher could log "called parent", the row saved, and nothing in the app ever showed
    it, so the feature was indistinguishable from broken and the next teacher could not tell
    an outreach had already been made.
    """
    flag = RiskFlag(
        student_id=seed["flagged_student"].id,
        risk_level="high",
        score=0.8,
        reasons=["attendance"],
        status="open",
    )
    db_session.add(flag)
    db_session.commit()
    flag_id = flag.id

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)
    created = client.post(
        f"/risk/{flag_id}/intervention",
        json={"note": "Left a voicemail with the guardian.", "action_taken": "called parent"},
    )
    assert created.status_code == 200, created.text

    resp = client.get(f"/risk/{flag_id}/interventions")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["action_taken"] == "called parent"
    assert items[0]["note"] == "Left a voicemail with the guardian."
    # Resolved server-side so the UI can name the actor without a lookup per row.
    assert items[0]["created_by_name"] == "teacher"


def test_intervention_list_is_ordered_newest_first(client, seed, db_session):
    flag = RiskFlag(
        student_id=seed["flagged_student"].id, risk_level="low", score=0.2, reasons=["x"], status="open"
    )
    db_session.add(flag)
    db_session.commit()
    flag_id = flag.id

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)
    for action in ("called parent", "counselor referral"):
        assert (
            client.post(
                f"/risk/{flag_id}/intervention",
                json={"note": f"note for {action}", "action_taken": action},
            ).status_code
            == 200
        )

    items = client.get(f"/risk/{flag_id}/interventions").json()["items"]
    assert [i["action_taken"] for i in items] == ["counselor referral", "called parent"]


def test_teacher_cannot_act_on_a_flag_for_a_student_they_do_not_teach(client, seed, db_session):
    """The acknowledge/intervention/resolve routes had NO ownership check at all.

    Each looked the flag up by id alone, so any authenticated teacher or admin could
    acknowledge, intervene on, or resolve a flag for a student in ANOTHER SCHOOL by
    incrementing the id - and log_intervention would write their name into that school's
    history. The read path was scoped from the start, which is why it went unnoticed.
    """
    flag = RiskFlag(
        student_id=seed["flagged_student"].id, risk_level="high", score=0.8, reasons=["x"], status="open"
    )
    db_session.add(flag)
    db_session.commit()
    flag_id = flag.id

    # other_teacher neither owns nor teaches seed["class"].
    _override_user("teacher", user_id=seed["other_teacher"].id, school_id=seed["school"].id)
    assert client.put(f"/risk/{flag_id}/acknowledge").status_code == 403
    assert (
        client.post(
            f"/risk/{flag_id}/intervention",
            json={"note": "n", "action_taken": "a"},
        ).status_code
        == 403
    )
    assert client.get(f"/risk/{flag_id}/interventions").status_code == 403


def test_admin_from_another_school_cannot_touch_the_flag(client, seed, db_session):
    """404, not 403, so flag ids in other tenants cannot be probed by status code."""
    flag = RiskFlag(
        student_id=seed["flagged_student"].id, risk_level="high", score=0.8, reasons=["x"], status="open"
    )
    db_session.add(flag)

    outsider_school = School(name="Outsider School")
    db_session.add(outsider_school)
    db_session.flush()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    outsider_admin = _make_user(db_session, admin_role, "outsider-admin", outsider_school)
    db_session.commit()
    flag_id = flag.id

    _override_user("admin", user_id=outsider_admin.id, school_id=outsider_school.id)
    assert client.put(f"/risk/{flag_id}/acknowledge").status_code == 404
    assert client.put(f"/risk/{flag_id}/resolve").status_code == 404
    assert client.get(f"/risk/{flag_id}/interventions").status_code == 404
