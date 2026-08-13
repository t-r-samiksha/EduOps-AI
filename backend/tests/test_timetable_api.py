import uuid
from datetime import time

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user


def _override_user(role: str, user_id: int = 999):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role)

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

    school_class = SchoolClass(name="Grade 8 - A", academic_year="2026-27", school_id=school.id)
    db_session.add(school_class)

    subject = Subject(name="Math", school_id=school.id)
    db_session.add(subject)

    room_a = Room(name="Room A", capacity=30, room_type="classroom", school_id=school.id)
    room_b = Room(name="Room B", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add_all([room_a, room_b])

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    teacher1 = User(supabase_id=uuid.uuid4(), email=f"t1-{uuid.uuid4()}@example.com", role_id=teacher_role.id, school_id=school.id)
    teacher2 = User(supabase_id=uuid.uuid4(), email=f"t2-{uuid.uuid4()}@example.com", role_id=teacher_role.id, school_id=school.id)
    db_session.add_all([teacher1, teacher2])
    db_session.flush()

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
        "subject": subject,
        "room_a": room_a,
        "room_b": room_b,
        "teacher1": teacher1,
        "teacher2": teacher2,
        "slot": slot,
    }


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
    _override_user("admin")
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


# --- PUT /timetable/update: conflict detection ---


def test_update_with_no_conflict_applies_change(client, seed):
    # Must be a real user id, not the default fake 999 - PUT /timetable/update now
    # writes an AuditLogEntry with actor_id=user.id, a real FK to users.id.
    _override_user("admin", user_id=seed["teacher1"].id)
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

    _override_user("principal")
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


# --- POST /timetable/generate: end-to-end DB wiring ---


def test_generate_creates_slots_and_deactivates_previous_run(client, seed, db_session):
    from app.models.timetable import ClassSubjectRequirement, TeacherSubject

    db_session.add(TeacherSubject(teacher_id=seed["teacher1"].id, subject_id=seed["subject"].id))
    db_session.add(
        ClassSubjectRequirement(
            class_id=seed["class"].id, subject_id=seed["subject"].id, periods_per_week=2, academic_year="2026-27"
        )
    )
    db_session.commit()

    _override_user("admin")
    resp = client.post(
        "/timetable/generate",
        json={"school_id": seed["school"].id, "academic_year": "2026-27", "class_ids": [seed["class"].id]},
    )
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


def test_generate_returns_422_when_unsolvable(client, seed, db_session):
    from app.models.timetable import ClassSubjectRequirement

    # No TeacherSubject row exists for this subject at all - unsolvable.
    db_session.add(
        ClassSubjectRequirement(
            class_id=seed["class"].id, subject_id=seed["subject"].id, periods_per_week=2, academic_year="2026-27"
        )
    )
    db_session.commit()

    _override_user("principal")
    resp = client.post(
        "/timetable/generate",
        json={"school_id": seed["school"].id, "academic_year": "2026-27", "class_ids": [seed["class"].id]},
    )
    assert resp.status_code == 422
