import asyncio
import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.main import app
from app.models.alerts import AlertDismissal
from app.models.document import Document
from app.models.risk import RiskFlag
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest
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
    student_role = db_session.query(Role).filter(Role.name == "student").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    teacher = _make_user(db_session, teacher_role, "teacher", school)
    student = _make_user(db_session, student_role, "student", school)
    db_session.commit()

    return {"school": school, "admin_user": admin_user, "teacher": teacher, "student": student}


# --- RBAC: 401 no token, 403 wrong role ---


def test_get_alerts_401_without_token(client):
    resp = client.get("/admin/alerts")
    assert resp.status_code == 401


def test_get_alerts_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/admin/alerts")
    assert resp.status_code == 403


def test_summary_401_without_token(client):
    resp = client.get("/admin/alerts/summary")
    assert resp.status_code == 401


def test_summary_403_for_student_role(client):
    _override_user("student")
    resp = client.get("/admin/alerts/summary")
    assert resp.status_code == 403


def test_resolve_401_without_token(client):
    resp = client.post("/admin/alerts/risk_flag:1/resolve")
    assert resp.status_code == 401


def test_resolve_403_for_parent_role(client):
    _override_user("parent")
    resp = client.post("/admin/alerts/risk_flag:1/resolve")
    assert resp.status_code == 403


def test_stream_401_without_token(client):
    resp = client.get("/admin/alerts/stream")
    assert resp.status_code == 401


def test_stream_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/admin/alerts/stream")
    assert resp.status_code == 403


# --- GET /admin/alerts ---


def test_get_alerts_returns_items_with_expected_shape(client, db_session, seed):
    flag = RiskFlag(student_id=seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(flag)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    item = next(i for i in body["items"] if i["id"] == f"risk_flag:{flag.id}")
    assert item["source"] == "risk_flag"
    assert item["severity"] == "urgent"
    assert item["entity_type"] == "risk_flags"
    assert item["entity_id"] == flag.id
    assert item["resolved"] is False


def test_get_alerts_filters_by_severity(client, db_session, seed):
    high = RiskFlag(student_id=seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    medium = RiskFlag(student_id=seed["student"].id, risk_level="medium", score=0.5, reasons=["y"], status="open")
    db_session.add_all([high, medium])
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/alerts", params={"severity": "urgent"})
    ids = {i["id"] for i in resp.json()["items"]}
    assert f"risk_flag:{high.id}" in ids
    assert f"risk_flag:{medium.id}" not in ids


def test_get_alerts_filters_by_since(client, db_session, seed):
    old_flag = RiskFlag(student_id=seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(old_flag)
    db_session.commit()
    db_session.refresh(old_flag)
    old_flag.flagged_at = datetime.now(timezone.utc) - timedelta(days=10)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/alerts", params={"since": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()})
    ids = {i["id"] for i in resp.json()["items"]}
    assert f"risk_flag:{old_flag.id}" not in ids


def test_get_alerts_rejects_invalid_severity(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/alerts", params={"severity": "critical"})
    assert resp.status_code == 400


# --- GET /admin/alerts/summary ---


def test_summary_counts_reflect_feed(client, db_session, seed):
    flag = RiskFlag(student_id=seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(flag)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id)
    feed = client.get("/admin/alerts").json()["items"]
    summary = client.get("/admin/alerts/summary").json()

    assert summary["total"] == len(feed)
    assert summary["by_severity"]["urgent"] + summary["by_severity"]["normal"] == len(feed)
    assert sum(summary["by_source"].values()) == len(feed)
    assert summary["by_source"].get("risk_flag", 0) >= 1


# --- POST /admin/alerts/{id}/resolve: routing per source ---


def test_resolve_risk_flag_changes_real_status(client, db_session, seed):
    flag = RiskFlag(student_id=seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(flag)
    db_session.commit()
    db_session.refresh(flag)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/alerts/risk_flag:{flag.id}/resolve")
    assert resp.status_code == 200
    assert resp.json() == {"id": f"risk_flag:{flag.id}", "resolved": True}

    db_session.refresh(flag)
    assert flag.status == "resolved"
    assert flag.resolved_by == seed["admin_user"].id
    assert flag.resolved_at is not None

    # No AlertDismissal row was created for this source - the real status IS the
    # resolution.
    assert db_session.query(AlertDismissal).filter(AlertDismissal.alert_id == f"risk_flag:{flag.id}").first() is None


def test_resolve_risk_flag_already_resolved_returns_400(client, db_session, seed):
    flag = RiskFlag(student_id=seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="resolved")
    db_session.add(flag)
    db_session.commit()
    db_session.refresh(flag)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/alerts/risk_flag:{flag.id}/resolve")
    assert resp.status_code == 400


def test_resolve_leave_request_creates_dismissal_not_status_change(client, db_session, seed):
    lr = LeaveRequest(teacher_id=seed["teacher"].id, start_date=date.today(), end_date=date.today(), reason="sick", status="pending")
    db_session.add(lr)
    db_session.commit()
    db_session.refresh(lr)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/alerts/leave_request:{lr.id}/resolve")
    assert resp.status_code == 200

    db_session.refresh(lr)
    assert lr.status == "pending"  # untouched - resolving the alert must NOT fake an approve/reject
    dismissal = db_session.query(AlertDismissal).filter(AlertDismissal.alert_id == f"leave_request:{lr.id}").one()
    assert dismissal.dismissed_by == seed["admin_user"].id

    # And the alert genuinely disappears from the feed now.
    feed_ids = {i["id"] for i in client.get("/admin/alerts").json()["items"]}
    assert f"leave_request:{lr.id}" not in feed_ids


def test_resolve_leave_request_twice_returns_400(client, db_session, seed):
    lr = LeaveRequest(teacher_id=seed["teacher"].id, start_date=date.today(), end_date=date.today(), reason="sick", status="pending")
    db_session.add(lr)
    db_session.commit()
    db_session.refresh(lr)

    _override_user("admin", user_id=seed["admin_user"].id)
    assert client.post(f"/admin/alerts/leave_request:{lr.id}/resolve").status_code == 200
    resp = client.post(f"/admin/alerts/leave_request:{lr.id}/resolve")
    assert resp.status_code == 400


def test_resolve_document_failed_creates_dismissal(client, db_session, seed):
    doc = Document(uploaded_by=seed["admin_user"].id, document_type="admission_form", file_url="x", status="failed")
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    _override_user("principal", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/alerts/document_failed:{doc.id}/resolve")
    assert resp.status_code == 200
    assert db_session.query(AlertDismissal).filter(AlertDismissal.alert_id == f"document_failed:{doc.id}").first() is not None


def test_resolve_malformed_alert_id_returns_400(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/admin/alerts/not-a-valid-id/resolve")
    assert resp.status_code == 400


def test_resolve_unknown_source_returns_404(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/admin/alerts/nonexistent_source:1/resolve")
    assert resp.status_code == 404


def test_resolve_unknown_entity_id_returns_404(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/admin/alerts/leave_request:999999/resolve")
    assert resp.status_code == 404


# --- GET /admin/alerts/stream ---
# Not tested via a full HTTP round-trip: a genuinely-infinite `while True: yield;
# await asyncio.sleep(...)` generator has no real network disconnect to trigger
# cleanup through TestClient's streaming interface, so it hangs forever if driven
# that way. _alert_event_stream()'s max_events parameter exists specifically so
# tests can call the generator directly instead - see its docstring in
# routers/admin_alerts.py. The RBAC tests above (401/403) don't have this problem:
# require_role() raises before the endpoint body - and therefore the generator -
# ever runs, so those return immediately over real HTTP.


async def _collect(agen, n):
    results = []
    async for item in agen:
        results.append(item)
        if len(results) >= n:
            break
    return results


def test_stream_generator_emits_correctly_formatted_sse_event(db_session, seed):
    from app.routers.admin_alerts import _alert_event_stream

    flag = RiskFlag(student_id=seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(flag)
    db_session.commit()

    events = asyncio.run(_collect(_alert_event_stream(db_session, max_events=1), 1))
    assert len(events) == 1
    assert events[0].startswith("data:")
    assert events[0].endswith("\n\n")

    payload = json.loads(events[0][len("data:") :].strip())
    assert isinstance(payload, list)
    assert any(a["id"] == f"risk_flag:{flag.id}" for a in payload)


def test_stream_generator_respects_max_events(db_session, seed):
    from app.routers.admin_alerts import _alert_event_stream

    events = asyncio.run(_collect(_alert_event_stream(db_session, max_events=2, poll_interval=0), 10))
    assert len(events) == 2


# --- fee_overdue as 8th source: real HTTP-level integration ---


def test_overdue_fee_appears_in_get_admin_alerts(client, db_session, seed):
    from datetime import date, timedelta

    from app.models.fees import FeeRecord, FeeSchedule

    schedule = FeeSchedule(school_id=seed["school"].id, academic_year="2026-27", fee_type="tuition", amount=15000.0, due_date=date.today() - timedelta(days=10))
    db_session.add(schedule)
    db_session.flush()
    record = FeeRecord(student_id=seed["student"].id, fee_schedule_id=schedule.id, amount_due=15000.0, amount_paid=0.0, status="overdue", due_date=schedule.due_date)
    db_session.add(record)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/alerts")
    assert resp.status_code == 200
    items = resp.json()["items"]
    match = next(i for i in items if i["id"] == f"fee_overdue:{record.id}")
    assert match["source"] == "fee_overdue"
    assert match["entity_type"] == "fee_records"


# --- cross-tenant school scoping: real HTTP-level regression --------------------
# The exact bug the user caught live: GET /admin/alerts (and, discovered while fixing
# it, POST /admin/alerts/{id}/resolve) had no school scoping at all, so an admin
# passing a real school_id (which every real admin/principal has via
# services/auth.get_current_user -> User.school_id) still saw/could resolve every
# OTHER school's alerts too. These tests pass school_id explicitly via _override_user
# (unlike every test above, which relies on the None default for single-school
# scenarios) to exercise the real scoped code path.


@pytest.fixture()
def other_seed(db_session):
    school = School(name="Other Test School")
    db_session.add(school)
    db_session.flush()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    admin_user = _make_user(db_session, admin_role, "admin", school)
    student = _make_user(db_session, student_role, "student", school)
    db_session.commit()
    return {"school": school, "admin_user": admin_user, "student": student}


def test_get_alerts_with_school_id_excludes_other_schools_risk_flag(client, db_session, seed, other_seed):
    theirs = RiskFlag(student_id=other_seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(theirs)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/alerts")
    assert resp.status_code == 200
    assert f"risk_flag:{theirs.id}" not in {i["id"] for i in resp.json()["items"]}

    _override_user("admin", user_id=other_seed["admin_user"].id, school_id=other_seed["school"].id)
    resp = client.get("/admin/alerts")
    assert f"risk_flag:{theirs.id}" in {i["id"] for i in resp.json()["items"]}


def test_summary_with_school_id_excludes_other_schools_risk_flag(client, db_session, seed, other_seed):
    theirs = RiskFlag(student_id=other_seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(theirs)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/alerts/summary")
    assert resp.json()["by_source"].get("risk_flag", 0) == 0


def test_resolve_with_school_id_returns_404_for_other_schools_risk_flag(client, db_session, seed, other_seed):
    """The write-side twin of the read-side leak above: without alert_belongs_to_school
    guarding this endpoint, an admin from `seed`'s school could resolve a flag that
    isn't even visible to them in GET /admin/alerts, just by knowing/guessing its id."""
    theirs = RiskFlag(student_id=other_seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(theirs)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(f"/admin/alerts/risk_flag:{theirs.id}/resolve")
    assert resp.status_code == 404

    db_session.refresh(theirs)
    assert theirs.status == "open"  # untouched

    _override_user("admin", user_id=other_seed["admin_user"].id, school_id=other_seed["school"].id)
    resp = client.post(f"/admin/alerts/risk_flag:{theirs.id}/resolve")
    assert resp.status_code == 200
    db_session.refresh(theirs)
    assert theirs.status == "resolved"


def test_stream_generator_with_school_id_excludes_other_schools_risk_flag(db_session, seed, other_seed):
    from app.routers.admin_alerts import _alert_event_stream

    theirs = RiskFlag(student_id=other_seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(theirs)
    db_session.commit()

    events = asyncio.run(_collect(_alert_event_stream(db_session, school_id=seed["school"].id, max_events=1), 1))
    payload = json.loads(events[0][len("data:") :].strip())
    assert not any(a["id"] == f"risk_flag:{theirs.id}" for a in payload)
