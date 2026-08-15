import uuid

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room, TeacherProfile, TeacherSubject
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

    school_class = SchoolClass(
        name="Grade 8 - A", academic_year="2026-27", grade_level=8, section="A", school_id=school.id
    )
    unparsed_class = SchoolClass(name="Reception", academic_year="2026-27", school_id=school.id)
    db_session.add_all([school_class, unparsed_class])

    subject = Subject(name="Math", school_id=school.id, periods_per_week=4, lab_required=True)
    db_session.add(subject)
    db_session.flush()

    room = Room(name="Lab 1", capacity=30, room_type="lab", school_id=school.id)
    db_session.add(room)

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    teacher = User(supabase_id=uuid.uuid4(), email=f"t-{uuid.uuid4()}@example.com", role_id=teacher_role.id, school_id=school.id)
    no_profile_teacher = User(
        supabase_id=uuid.uuid4(), email=f"t2-{uuid.uuid4()}@example.com", role_id=teacher_role.id, school_id=school.id
    )
    db_session.add_all([teacher, no_profile_teacher])
    db_session.flush()

    db_session.add_all(
        [
            TeacherProfile(teacher_id=teacher.id, max_periods_per_week=24),
            TeacherSubject(teacher_id=teacher.id, subject_id=subject.id),
        ]
    )
    db_session.commit()

    return {
        "school": school,
        "class": school_class,
        "unparsed_class": unparsed_class,
        "subject": subject,
        "room": room,
        "teacher": teacher,
        "no_profile_teacher": no_profile_teacher,
    }


def test_lookup_returns_401_without_token(client):
    resp = client.get("/reference/lookup", params={"school_id": 1})
    assert resp.status_code == 401


def test_lookup_enriched_teacher_fields(client, seed):
    _override_user("admin")
    resp = client.get("/reference/lookup", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    teachers = {t["id"]: t for t in resp.json()["teachers"]}

    with_profile = teachers[seed["teacher"].id]
    assert with_profile["max_periods_per_week"] == 24
    assert with_profile["subject_ids"] == [seed["subject"].id]

    without_profile = teachers[seed["no_profile_teacher"].id]
    assert without_profile["max_periods_per_week"] is None
    assert without_profile["subject_ids"] == []


def test_lookup_enriched_room_fields(client, seed):
    _override_user("teacher", user_id=seed["teacher"].id)
    resp = client.get("/reference/lookup", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    rooms = {r["id"]: r for r in resp.json()["rooms"]}
    assert rooms[seed["room"].id]["room_type"] == "lab"


def test_lookup_enriched_class_fields(client, seed):
    _override_user("principal")
    resp = client.get("/reference/lookup", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    classes = {c["id"]: c for c in resp.json()["classes"]}

    parsed = classes[seed["class"].id]
    assert parsed["grade_level"] == 8
    assert parsed["section"] == "A"

    unparsed = classes[seed["unparsed_class"].id]
    assert unparsed["grade_level"] is None
    assert unparsed["section"] is None


def test_lookup_enriched_subject_fields(client, seed):
    _override_user("admin")
    resp = client.get("/reference/lookup", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    subjects = {s["id"]: s for s in resp.json()["subjects"]}
    row = subjects[seed["subject"].id]
    assert row["periods_per_week"] == 4
    assert row["lab_required"] is True
