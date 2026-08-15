import uuid

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room
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
    """An EXISTING school with one class/subject/room already in it - used for
    the "add to something that already has some real data" scenarios, as
    distinct from CHECKPOINT 1's separate from-absolute-zero empirical test."""
    school = School(name="Existing School")
    db_session.add(school)
    db_session.flush()

    school_class = SchoolClass(name="Grade 8 - A", academic_year="2026-27", grade_level=8, section="A", school_id=school.id)
    subject = Subject(name="Math", school_id=school.id)
    room = Room(name="Room 1", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add_all([school_class, subject, room])

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    teacher = User(supabase_id=uuid.uuid4(), email=f"t-{uuid.uuid4()}@example.com", role_id=teacher_role.id, school_id=school.id)
    db_session.add(teacher)
    db_session.commit()
    db_session.refresh(school_class)
    db_session.refresh(subject)
    db_session.refresh(room)
    db_session.refresh(teacher)

    return {"school": school, "class": school_class, "subject": subject, "room": room, "teacher": teacher}


# --- RBAC --------------------------------------------------------------------


def test_create_school_returns_401_without_token(client):
    resp = client.post("/admin/schools", json={"name": "X"})
    assert resp.status_code == 401


@pytest.mark.parametrize("role", ["teacher", "student", "parent"])
def test_create_school_returns_403_for_non_admin_role(client, role):
    _override_user(role)
    resp = client.post("/admin/schools", json={"name": "X"})
    assert resp.status_code == 403


def test_create_class_returns_403_for_non_admin_role(client, seed):
    _override_user("teacher")
    resp = client.post("/admin/classes", json={"school_id": seed["school"].id, "name": "X", "academic_year": "2026-27"})
    assert resp.status_code == 403


# --- School --------------------------------------------------------------------


def test_create_school_cold_start(client):
    _override_user("admin")
    resp = client.post("/admin/schools", json={"name": "Brand New School", "address": "1 Main St"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Brand New School"
    assert body["is_active"] is True


def test_school_deactivate_then_reactivate_roundtrip(client, seed):
    _override_user("principal")
    resp = client.put(f"/admin/schools/{seed['school'].id}/deactivate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    resp = client.put(f"/admin/schools/{seed['school'].id}/reactivate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


def test_get_school_returns_404_for_unknown_id(client):
    _override_user("admin")
    resp = client.get("/admin/schools/999999999")
    assert resp.status_code == 404


# --- SchoolClass -----------------------------------------------------------------


def test_create_class_cold_start_from_real_school(client):
    """Cold-start chain: create a school, then create a class in it - no seed data involved."""
    _override_user("admin")
    school = client.post("/admin/schools", json={"name": "Cold Start School"}).json()

    resp = client.post(
        "/admin/classes",
        json={"school_id": school["id"], "name": "Grade 9 - A", "academic_year": "2027-28", "grade_level": 9, "section": "A"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["school_id"] == school["id"]
    assert body["grade_level"] == 9


def test_create_class_with_negative_grade_level_and_grade_label(client):
    """LKG/UKG/Nursery support: grade_level=-2 (LKG per the documented convention -
    Nursery=-3, LKG=-2, UKG=-1) with a cosmetic grade_label, previously blocked
    entirely (grade_level is int-only, "LKG" as a raw value was a 422)."""
    _override_user("admin")
    school = client.post("/admin/schools", json={"name": "LKG Test School"}).json()

    resp = client.post(
        "/admin/classes",
        json={
            "school_id": school["id"], "name": "LKG - A", "academic_year": "2026-27",
            "grade_level": -2, "grade_label": "LKG", "section": "A",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["grade_level"] == -2
    assert body["grade_label"] == "LKG"

    lookup = client.get("/reference/lookup", params={"school_id": school["id"]}).json()
    lkg_class = next(c for c in lookup["classes"] if c["id"] == body["id"])
    assert lkg_class["grade_level"] == -2
    assert lkg_class["grade_label"] == "LKG"


def test_create_class_without_grade_label_leaves_it_null(client, seed):
    """A plain numeric grade (e.g. Grade 8) has no special name - grade_label
    must stay null, not default to some derived "Grade 8" string (display code
    is what falls back, not the stored data)."""
    _override_user("admin")
    resp = client.post(
        "/admin/classes",
        json={"school_id": seed["school"].id, "name": "Grade 8 - C", "academic_year": "2026-27", "grade_level": 8, "section": "C"},
    )
    assert resp.status_code == 201
    assert resp.json()["grade_label"] is None


def test_create_class_add_to_existing_school(client, seed):
    """The existing school already has one class - adding a second must not
    require re-entering the first."""
    _override_user("admin")
    resp = client.post(
        "/admin/classes",
        json={"school_id": seed["school"].id, "name": "Grade 8 - B", "academic_year": "2026-27", "grade_level": 8, "section": "B"},
    )
    assert resp.status_code == 201

    listed = client.get("/admin/classes", params={"school_id": seed["school"].id}).json()
    names = {c["name"] for c in listed}
    assert names == {"Grade 8 - A", "Grade 8 - B"}


def test_create_class_returns_400_for_unknown_school_id(client):
    _override_user("admin")
    resp = client.post("/admin/classes", json={"school_id": 999999999, "name": "X", "academic_year": "2026-27"})
    assert resp.status_code == 400


def test_create_class_returns_400_for_unknown_class_teacher_id(client, seed):
    _override_user("admin")
    resp = client.post(
        "/admin/classes",
        json={"school_id": seed["school"].id, "name": "X", "academic_year": "2026-27", "class_teacher_id": 999999999},
    )
    assert resp.status_code == 400


def test_deactivated_class_excluded_from_default_list(client, seed):
    _override_user("admin")
    client.put(f"/admin/classes/{seed['class'].id}/deactivate")

    active_only = client.get("/admin/classes", params={"school_id": seed["school"].id}).json()
    assert active_only == []

    with_inactive = client.get("/admin/classes", params={"school_id": seed["school"].id, "include_inactive": True}).json()
    assert len(with_inactive) == 1


def test_update_class(client, seed):
    _override_user("admin")
    resp = client.put(f"/admin/classes/{seed['class'].id}", json={"section": "C"})
    assert resp.status_code == 200
    assert resp.json()["section"] == "C"


# --- home_room_id ----------------------------------------------------------------


def test_create_class_with_home_room_id(client, seed):
    _override_user("admin")
    resp = client.post(
        "/admin/classes",
        json={
            "school_id": seed["school"].id, "name": "Grade 8 - B", "academic_year": "2026-27",
            "grade_level": 8, "section": "B", "home_room_id": seed["room"].id,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["home_room_id"] == seed["room"].id


def test_create_class_returns_400_for_unknown_home_room_id(client, seed):
    _override_user("admin")
    resp = client.post(
        "/admin/classes",
        json={"school_id": seed["school"].id, "name": "Grade 8 - B", "academic_year": "2026-27", "home_room_id": 999999999},
    )
    assert resp.status_code == 400


def test_create_class_returns_400_when_home_room_already_claimed_by_another_active_class(client, db_session, seed):
    _override_user("admin")
    client.put(f"/admin/classes/{seed['class'].id}", json={"home_room_id": seed["room"].id})

    resp = client.post(
        "/admin/classes",
        json={
            "school_id": seed["school"].id, "name": "Grade 8 - B", "academic_year": "2026-27",
            "home_room_id": seed["room"].id,
        },
    )
    assert resp.status_code == 400
    assert seed["class"].name in resp.json()["detail"]


def test_update_class_home_room_id(client, seed):
    _override_user("admin")
    resp = client.put(f"/admin/classes/{seed['class'].id}", json={"home_room_id": seed["room"].id})
    assert resp.status_code == 200
    assert resp.json()["home_room_id"] == seed["room"].id


def test_update_class_returns_400_for_unknown_home_room_id(client, seed):
    _override_user("admin")
    resp = client.put(f"/admin/classes/{seed['class'].id}", json={"home_room_id": 999999999})
    assert resp.status_code == 400


def test_update_class_allows_resaving_its_own_home_room_id(client, seed):
    """A class re-saving the SAME home_room_id it already has must not trip
    the uniqueness check against itself."""
    _override_user("admin")
    client.put(f"/admin/classes/{seed['class'].id}", json={"home_room_id": seed["room"].id})
    resp = client.put(f"/admin/classes/{seed['class'].id}", json={"home_room_id": seed["room"].id, "section": "Z"})
    assert resp.status_code == 200
    assert resp.json()["home_room_id"] == seed["room"].id
    assert resp.json()["section"] == "Z"


def test_update_class_returns_400_when_home_room_claimed_by_a_different_active_class(client, db_session, seed):
    other_class = SchoolClass(name="Grade 9 - A", academic_year="2026-27", grade_level=9, section="A", school_id=seed["school"].id)
    db_session.add(other_class)
    db_session.commit()
    db_session.refresh(other_class)

    _override_user("admin")
    client.put(f"/admin/classes/{seed['class'].id}", json={"home_room_id": seed["room"].id})

    resp = client.put(f"/admin/classes/{other_class.id}", json={"home_room_id": seed["room"].id})
    assert resp.status_code == 400
    assert seed["class"].name in resp.json()["detail"]


def test_deactivating_a_class_frees_its_home_room_for_reuse(client, db_session, seed):
    other_class = SchoolClass(name="Grade 9 - A", academic_year="2026-27", grade_level=9, section="A", school_id=seed["school"].id)
    db_session.add(other_class)
    db_session.commit()
    db_session.refresh(other_class)

    _override_user("admin")
    client.put(f"/admin/classes/{seed['class'].id}", json={"home_room_id": seed["room"].id})
    client.put(f"/admin/classes/{seed['class'].id}/deactivate")

    resp = client.put(f"/admin/classes/{other_class.id}", json={"home_room_id": seed["room"].id})
    assert resp.status_code == 200
    assert resp.json()["home_room_id"] == seed["room"].id


# --- Subject -------------------------------------------------------------------


def test_create_subject_add_to_existing_school(client, seed):
    _override_user("principal")
    resp = client.post("/admin/subjects", json={"school_id": seed["school"].id, "name": "Science", "code": "SCI"})
    assert resp.status_code == 201

    listed = client.get("/admin/subjects", params={"school_id": seed["school"].id}).json()
    names = {s["name"] for s in listed}
    assert names == {"Math", "Science"}


def test_create_subject_returns_400_for_unknown_school_id(client):
    _override_user("admin")
    resp = client.post("/admin/subjects", json={"school_id": 999999999, "name": "X"})
    assert resp.status_code == 400


def test_create_subject_defaults_periods_per_week_and_lab_required(client, seed):
    _override_user("admin")
    resp = client.post("/admin/subjects", json={"school_id": seed["school"].id, "name": "History"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["periods_per_week"] == 3
    assert body["lab_required"] is False


def test_create_subject_with_explicit_periods_per_week_and_lab_required(client, seed):
    _override_user("admin")
    resp = client.post(
        "/admin/subjects",
        json={"school_id": seed["school"].id, "name": "Chemistry", "periods_per_week": 5, "lab_required": True},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["periods_per_week"] == 5
    assert body["lab_required"] is True


def test_update_subject_periods_per_week_and_lab_required(client, seed):
    _override_user("admin")
    resp = client.put(f"/admin/subjects/{seed['subject'].id}", json={"periods_per_week": 6, "lab_required": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["periods_per_week"] == 6
    assert body["lab_required"] is True


def test_subject_deactivate_excludes_from_reference_lookup(client, seed):
    """Integration proof that deactivate actually means something end-to-end -
    GET /reference/lookup (used by every generation form) must stop offering it."""
    _override_user("admin")
    before = client.get("/reference/lookup", params={"school_id": seed["school"].id}).json()
    assert seed["subject"].id in {s["id"] for s in before["subjects"]}

    client.put(f"/admin/subjects/{seed['subject'].id}/deactivate")

    after = client.get("/reference/lookup", params={"school_id": seed["school"].id}).json()
    assert seed["subject"].id not in {s["id"] for s in after["subjects"]}


# --- Room ------------------------------------------------------------------------


def test_create_room_add_to_existing_school(client, seed):
    _override_user("admin")
    resp = client.post("/admin/rooms", json={"school_id": seed["school"].id, "name": "Lab 1", "capacity": 25, "room_type": "lab"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["room_type"] == "lab"

    listed = client.get("/admin/rooms", params={"school_id": seed["school"].id}).json()
    assert len(listed) == 2


def test_create_room_returns_400_for_unknown_school_id(client):
    _override_user("admin")
    resp = client.post("/admin/rooms", json={"school_id": 999999999, "name": "X", "capacity": 10})
    assert resp.status_code == 400


def test_room_deactivate_excludes_from_reference_lookup(client, seed):
    _override_user("admin")
    client.put(f"/admin/rooms/{seed['room'].id}/deactivate")
    after = client.get("/reference/lookup", params={"school_id": seed["school"].id}).json()
    assert seed["room"].id not in {r["id"] for r in after["rooms"]}


def test_update_room(client, seed):
    _override_user("principal")
    resp = client.put(f"/admin/rooms/{seed['room'].id}", json={"capacity": 40, "room_type": "lab"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["capacity"] == 40
    assert body["room_type"] == "lab"
