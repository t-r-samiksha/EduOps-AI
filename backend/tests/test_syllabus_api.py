import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.syllabus import AnomalyFlag, SyllabusPlan
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int = 999):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role)

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

    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    teacher = _make_user(db_session, teacher_role, "teacher", school)
    other_teacher = _make_user(db_session, teacher_role, "other-teacher", school)

    subject = Subject(name="Math", school_id=school.id)
    db_session.add(subject)
    db_session.flush()
    room = Room(name="R1", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add(room)
    db_session.flush()

    school_class = SchoolClass(name="8A", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=teacher.id)
    db_session.add(school_class)
    db_session.flush()

    # `teacher` actually teaches (class, subject) per an active TimetableSlot -
    # `other_teacher` does not, and is the negative case for role-scoping.
    db_session.add(
        TimetableSlot(
            day_of_week=0, period_number=0, start_time=time(8, 0), end_time=time(8, 45),
            subject_id=subject.id, teacher_id=teacher.id, class_id=school_class.id, room_id=room.id,
            academic_year=ACADEMIC_YEAR, is_active=True,
        )
    )
    db_session.commit()

    return {
        "school": school, "class": school_class, "subject": subject,
        "admin_user": admin_user, "teacher": teacher, "other_teacher": other_teacher,
    }


# --- RBAC ---


def test_create_plan_401_without_token(client):
    resp = client.post("/syllabus/plan", json={})
    assert resp.status_code == 401


def test_create_plan_403_for_student_role(client):
    _override_user("student")
    resp = client.post("/syllabus/plan", json={})
    assert resp.status_code == 403


def test_log_checkpoint_401_without_token(client):
    resp = client.post("/syllabus/checkpoint", json={})
    assert resp.status_code == 401


def test_log_checkpoint_403_for_student_role(client):
    _override_user("student")
    resp = client.post("/syllabus/checkpoint", json={})
    assert resp.status_code == 403


def test_summary_401_without_token(client):
    resp = client.get("/syllabus/summary")
    assert resp.status_code == 401


def test_summary_403_for_parent_role(client):
    _override_user("parent")
    resp = client.get("/syllabus/summary")
    assert resp.status_code == 403


def test_anomalies_401_without_token(client):
    resp = client.get("/admin/anomalies")
    assert resp.status_code == 401


def test_anomalies_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/admin/anomalies")
    assert resp.status_code == 403


def test_anomalies_resolve_401_without_token(client):
    resp = client.put("/admin/anomalies/1/resolve")
    assert resp.status_code == 401


def test_anomalies_resolve_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.put("/admin/anomalies/1/resolve")
    assert resp.status_code == 403


# --- POST /syllabus/plan ---


def test_create_plan_succeeds_for_teacher(client, seed):
    _override_user("teacher", user_id=seed["teacher"].id)
    resp = client.post(
        "/syllabus/plan",
        json={
            "class_id": seed["class"].id, "subject_id": seed["subject"].id, "academic_year": ACADEMIC_YEAR,
            "total_units": 10, "term_start_date": "2026-01-01", "term_end_date": "2026-03-12",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_units"] == 10
    assert body["created_by"] == seed["teacher"].id


def test_create_plan_rejects_duplicate_class_subject_year(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    body = {
        "class_id": seed["class"].id, "subject_id": seed["subject"].id, "academic_year": ACADEMIC_YEAR,
        "total_units": 10, "term_start_date": "2026-01-01", "term_end_date": "2026-03-12",
    }
    assert client.post("/syllabus/plan", json=body).status_code == 200
    resp = client.post("/syllabus/plan", json=body)
    assert resp.status_code == 400


def test_create_plan_rejects_bad_dates(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        "/syllabus/plan",
        json={
            "class_id": seed["class"].id, "subject_id": seed["subject"].id, "academic_year": ACADEMIC_YEAR,
            "total_units": 10, "term_start_date": "2026-03-12", "term_end_date": "2026-01-01",
        },
    )
    assert resp.status_code == 400


def test_create_plan_rejects_nonpositive_total_units(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        "/syllabus/plan",
        json={
            "class_id": seed["class"].id, "subject_id": seed["subject"].id, "academic_year": ACADEMIC_YEAR,
            "total_units": 0, "term_start_date": "2026-01-01", "term_end_date": "2026-03-12",
        },
    )
    assert resp.status_code == 400


# --- Full flow: plan -> checkpoint -> summary ---


def test_full_checkpoint_to_summary_flow(client, seed):
    _override_user("teacher", user_id=seed["teacher"].id)
    plan_resp = client.post(
        "/syllabus/plan",
        json={
            "class_id": seed["class"].id, "subject_id": seed["subject"].id, "academic_year": ACADEMIC_YEAR,
            "total_units": 10, "term_start_date": "2026-01-01", "term_end_date": "2026-03-12",
        },
    )
    plan_id = plan_resp.json()["id"]

    resp = client.post("/syllabus/checkpoint", json={"plan_id": plan_id, "topic_label": "Algebra basics", "sequence_number": 1})
    assert resp.status_code == 200
    assert resp.json()["logged_by"] == seed["teacher"].id

    summary = client.get("/syllabus/summary", params={"class_id": seed["class"].id, "subject_id": seed["subject"].id}).json()
    item = next(i for i in summary["items"] if i["plan_id"] == plan_id)
    assert item["checkpoints_logged"] == 1
    assert item["total_units"] == 10


def test_checkpoint_rejects_teacher_not_teaching_that_subject(client, seed):
    _override_user("teacher", user_id=seed["teacher"].id)
    plan_id = client.post(
        "/syllabus/plan",
        json={
            "class_id": seed["class"].id, "subject_id": seed["subject"].id, "academic_year": ACADEMIC_YEAR,
            "total_units": 10, "term_start_date": "2026-01-01", "term_end_date": "2026-03-12",
        },
    ).json()["id"]

    _override_user("teacher", user_id=seed["other_teacher"].id)
    resp = client.post("/syllabus/checkpoint", json={"plan_id": plan_id, "topic_label": "X", "sequence_number": 1})
    assert resp.status_code == 403


def test_checkpoint_returns_404_for_missing_plan(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/syllabus/checkpoint", json={"plan_id": 999999, "topic_label": "X", "sequence_number": 1})
    assert resp.status_code == 404


def test_checkpoint_rejects_empty_topic_label(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    plan_id = client.post(
        "/syllabus/plan",
        json={
            "class_id": seed["class"].id, "subject_id": seed["subject"].id, "academic_year": ACADEMIC_YEAR,
            "total_units": 10, "term_start_date": "2026-01-01", "term_end_date": "2026-03-12",
        },
    ).json()["id"]
    resp = client.post("/syllabus/checkpoint", json={"plan_id": plan_id, "topic_label": "   ", "sequence_number": 1})
    assert resp.status_code == 400


# --- GET /syllabus/summary: role scoping ---


def test_summary_teacher_only_sees_own_subjects(client, seed):
    _override_user("teacher", user_id=seed["teacher"].id)
    plan_id = client.post(
        "/syllabus/plan",
        json={
            "class_id": seed["class"].id, "subject_id": seed["subject"].id, "academic_year": ACADEMIC_YEAR,
            "total_units": 10, "term_start_date": "2026-01-01", "term_end_date": "2026-03-12",
        },
    ).json()["id"]

    _override_user("teacher", user_id=seed["teacher"].id)
    own = client.get("/syllabus/summary", params={"class_id": seed["class"].id}).json()
    assert any(i["plan_id"] == plan_id for i in own["items"])

    _override_user("teacher", user_id=seed["other_teacher"].id)
    others = client.get("/syllabus/summary", params={"class_id": seed["class"].id}).json()
    assert all(i["plan_id"] != plan_id for i in others["items"])


def test_summary_admin_sees_plan_with_correct_pace_fields(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    # UTC, not date.today(). GET /syllabus/summary computes elapsed days from
    # datetime.now(timezone.utc).date() (routers/syllabus.py), so building the term
    # window from a LOCAL date made this test fail whenever local and UTC dates
    # disagree - i.e. every run between 00:00 and 05:30 IST, where it computed
    # 34/70 = 0.486 instead of 35/70 = 0.5. A latent bug in the test, not the
    # endpoint: the server is consistently UTC, the test was not.
    today = datetime.now(timezone.utc).date()
    plan_id = client.post(
        "/syllabus/plan",
        json={
            "class_id": seed["class"].id, "subject_id": seed["subject"].id, "academic_year": ACADEMIC_YEAR,
            "total_units": 10, "term_start_date": str(today - timedelta(days=35)), "term_end_date": str(today + timedelta(days=35)),
        },
    ).json()["id"]

    summary = client.get("/syllabus/summary", params={"class_id": seed["class"].id, "subject_id": seed["subject"].id}).json()
    item = next(i for i in summary["items"] if i["plan_id"] == plan_id)
    assert item["expected_fraction"] == 0.5
    assert item["actual_fraction"] == 0.0
    assert item["status"] == "behind"


# --- GET /admin/anomalies, PUT /admin/anomalies/{id}/resolve ---


@pytest.fixture()
def anomaly(db_session, seed):
    flag = AnomalyFlag(
        type="teacher_overload", entity_type="users", entity_id=seed["teacher"].id, severity="urgent",
        detail={"periods_per_week": 40, "peer_baseline": 10.0, "message": "Teacher overloaded"}, status="open",
    )
    db_session.add(flag)
    db_session.commit()
    db_session.refresh(flag)
    return flag


def test_list_anomalies_returns_created_flag(client, seed, anomaly):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/anomalies", params={"type": "teacher_overload"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    match = next(i for i in items if i["id"] == anomaly.id)
    assert match["severity"] == "urgent"
    assert match["entity_id"] == seed["teacher"].id
    assert match["status"] == "open"


def test_list_anomalies_filters_by_severity(client, seed, anomaly):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/anomalies", params={"severity": "normal"})
    ids = {i["id"] for i in resp.json()["items"]}
    assert anomaly.id not in ids  # the fixture flag is urgent, not normal


def test_resolve_anomaly_sets_status_and_actor(client, seed, anomaly):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(f"/admin/anomalies/{anomaly.id}/resolve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["resolved_by"] == seed["admin_user"].id
    assert body["resolved_at"] is not None


def test_resolve_anomaly_twice_returns_400(client, seed, anomaly):
    _override_user("admin", user_id=seed["admin_user"].id)
    assert client.put(f"/admin/anomalies/{anomaly.id}/resolve").status_code == 200
    resp = client.put(f"/admin/anomalies/{anomaly.id}/resolve")
    assert resp.status_code == 400


def test_resolve_anomaly_404_for_missing_id(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put("/admin/anomalies/999999/resolve")
    assert resp.status_code == 404


# --- Command Center integration: anomaly_flag as the 7th alert source ---


def test_anomaly_flag_appears_in_admin_alerts_feed(client, seed, anomaly):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/alerts")
    assert resp.status_code == 200
    items = resp.json()["items"]
    match = next(i for i in items if i["id"] == f"anomaly_flag:{anomaly.id}")
    assert match["source"] == "anomaly_flag"
    assert match["severity"] == "urgent"
    assert match["message"] == "Teacher overloaded"


def test_resolving_via_admin_alerts_changes_real_anomaly_flag_status(client, db_session, seed, anomaly):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/alerts/anomaly_flag:{anomaly.id}/resolve")
    assert resp.status_code == 200
    assert resp.json() == {"id": f"anomaly_flag:{anomaly.id}", "resolved": True}

    db_session.refresh(anomaly)
    assert anomaly.status == "resolved"
    assert anomaly.resolved_by == seed["admin_user"].id

    # And it's gone from both feeds now.
    feed_ids = {i["id"] for i in client.get("/admin/alerts").json()["items"]}
    assert f"anomaly_flag:{anomaly.id}" not in feed_ids
    anomaly_ids = {i["id"] for i in client.get("/admin/anomalies").json()["items"]}
    assert anomaly.id not in anomaly_ids
