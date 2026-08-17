import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.main import app
from app.models.notification import Notification
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.routers.notifications import _notification_event_stream
from app.services.auth import CurrentUser, get_current_user


def _override_user(role: str, user_id: int, school_id: int | None = None):
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
    school = School(name="Notifications Test School")
    db_session.add(school)
    db_session.flush()

    parent_role = db_session.query(Role).filter(Role.name == "parent").one()
    owner = _make_user(db_session, parent_role, "owner", school)
    stranger = _make_user(db_session, parent_role, "stranger", school)

    base = datetime.now(timezone.utc) - timedelta(days=1)
    unread = [
        Notification(
            user_id=owner.id, source_type="early_warning", title=f"Unread {i}", priority="urgent",
            created_at=base + timedelta(minutes=i),
        )
        for i in range(3)
    ]
    read = [
        Notification(
            user_id=owner.id, source_type="fee_reminder", title=f"Read {i}", read_at=datetime.now(timezone.utc),
            created_at=base + timedelta(minutes=10 + i),
        )
        for i in range(2)
    ]
    others = [Notification(user_id=stranger.id, source_type="announcement", title="Not yours")]
    db_session.add_all(unread + read + others)
    db_session.commit()

    return {"school": school, "owner": owner, "stranger": stranger, "unread": unread, "read": read, "others": others}


# --- auth ---


def test_list_401_without_token(client, seed):
    assert client.get("/notifications").status_code == 401


def test_unread_count_401_without_token(client, seed):
    assert client.get("/notifications/unread-count").status_code == 401


def test_read_all_401_without_token(client, seed):
    assert client.put("/notifications/read-all").status_code == 401


# --- GET /notifications ---


def test_list_returns_only_own_notifications(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    body = client.get("/notifications").json()
    assert body["total"] == 5
    assert all(i["title"] != "Not yours" for i in body["items"])


def test_list_newest_first(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    items = client.get("/notifications").json()["items"]
    assert items[0]["title"] == "Read 1"


def test_list_filter_unread(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    body = client.get("/notifications", params={"read": "false"}).json()
    assert body["total"] == 3
    assert all(i["read_at"] is None for i in body["items"])


def test_list_filter_read(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    body = client.get("/notifications", params={"read": "true"}).json()
    assert body["total"] == 2
    assert all(i["read_at"] is not None for i in body["items"])


def test_list_pagination_splits_pages(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    page1 = client.get("/notifications", params={"page": 1, "page_size": 2}).json()
    page2 = client.get("/notifications", params={"page": 2, "page_size": 2}).json()

    assert page1["total"] == page2["total"] == 5
    assert page1["page"] == 1 and page1["page_size"] == 2
    assert len(page1["items"]) == 2 and len(page2["items"]) == 2
    assert {i["id"] for i in page1["items"]}.isdisjoint({i["id"] for i in page2["items"]})


def test_list_page_beyond_end_is_empty_but_reports_total(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    body = client.get("/notifications", params={"page": 99, "page_size": 20}).json()
    assert body["items"] == []
    assert body["total"] == 5


def test_list_rejects_page_below_one(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    assert client.get("/notifications", params={"page": 0}).status_code == 400


def test_list_rejects_page_size_out_of_range(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    assert client.get("/notifications", params={"page_size": 0}).status_code == 400
    assert client.get("/notifications", params={"page_size": 101}).status_code == 400


def test_list_item_shape(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    item = client.get("/notifications", params={"read": "false"}).json()["items"][0]
    assert set(item) == {
        "id", "source_type", "source_id", "title", "body", "priority",
        "read_at", "acknowledged_at", "created_at",
    }
    assert item["priority"] == "urgent"


def test_list_ignores_user_id_param(client, seed):
    """There is no user_id parameter - passing one must not widen the scope."""
    _override_user("parent", seed["owner"].id, seed["school"].id)
    body = client.get("/notifications", params={"user_id": seed["stranger"].id}).json()
    assert body["total"] == 5
    assert all(i["title"] != "Not yours" for i in body["items"])


# --- unread-count ---


def test_unread_count(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    assert client.get("/notifications/unread-count").json() == {"count": 3}


def test_unread_count_is_per_user(client, seed):
    _override_user("parent", seed["stranger"].id, seed["school"].id)
    assert client.get("/notifications/unread-count").json() == {"count": 1}


# --- mark read ---


def test_mark_read_sets_timestamp(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    target = seed["unread"][0].id
    body = client.put(f"/notifications/{target}/read").json()
    assert body["id"] == target
    assert body["read_at"] is not None
    assert client.get("/notifications/unread-count").json()["count"] == 2


def test_mark_read_is_idempotent(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    target = seed["unread"][0].id
    first = client.put(f"/notifications/{target}/read").json()["read_at"]
    second = client.put(f"/notifications/{target}/read").json()["read_at"]
    assert first == second


def test_mark_read_404_for_another_users_notification(client, seed):
    """404 not 403 - a 403 would confirm the row exists."""
    _override_user("parent", seed["owner"].id, seed["school"].id)
    resp = client.put(f"/notifications/{seed['others'][0].id}/read")
    assert resp.status_code == 404


def test_mark_read_404_for_unknown_id(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    assert client.put("/notifications/-1/read").status_code == 404


# --- read-all ---


def test_read_all_marks_every_unread(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    assert client.put("/notifications/read-all").json() == {"updated": 3}
    assert client.get("/notifications/unread-count").json() == {"count": 0}


def test_read_all_does_not_touch_other_users(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    client.put("/notifications/read-all")

    _override_user("parent", seed["stranger"].id, seed["school"].id)
    assert client.get("/notifications/unread-count").json() == {"count": 1}


def test_read_all_on_empty_inbox_reports_zero(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    client.put("/notifications/read-all")
    assert client.put("/notifications/read-all").json() == {"updated": 0}


# --- acknowledge ---


def test_acknowledge_sets_timestamp(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    body = client.put(f"/notifications/{seed['unread'][0].id}/acknowledge").json()
    assert body["acknowledged_at"] is not None


def test_acknowledge_does_not_imply_read(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    body = client.put(f"/notifications/{seed['unread'][0].id}/acknowledge").json()
    assert body["read_at"] is None
    assert client.get("/notifications/unread-count").json()["count"] == 3


def test_acknowledge_is_idempotent(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    target = seed["unread"][0].id
    first = client.put(f"/notifications/{target}/acknowledge").json()["acknowledged_at"]
    second = client.put(f"/notifications/{target}/acknowledge").json()["acknowledged_at"]
    assert first == second


def test_acknowledge_404_for_another_users_notification(client, seed):
    _override_user("parent", seed["owner"].id, seed["school"].id)
    assert client.put(f"/notifications/{seed['others'][0].id}/acknowledge").status_code == 404


# --- stream ---


def test_stream_payload_shape(db_session, seed):
    """Calls the generator directly with max_events, same approach as the alerts
    stream's tests - TestClient can't cancel an infinite SSE generator."""

    async def _collect():
        return [chunk async for chunk in _notification_event_stream(
            db_session, user_id=seed["owner"].id, max_events=1, poll_interval=0
        )]

    chunks = asyncio.run(_collect())
    assert len(chunks) == 1
    assert chunks[0].startswith("data: ")
    assert chunks[0].endswith("\n\n")

    payload = json.loads(chunks[0][len("data: "):])
    assert payload["unread_count"] == 3
    assert len(payload["latest"]) == 5
    assert payload["latest"][0]["title"] == "Read 1"


def test_stream_is_scoped_to_the_user(db_session, seed):
    async def _collect():
        return [chunk async for chunk in _notification_event_stream(
            db_session, user_id=seed["stranger"].id, max_events=1, poll_interval=0
        )]

    payload = json.loads(asyncio.run(_collect())[0][len("data: "):])
    assert payload["unread_count"] == 1
    assert [i["title"] for i in payload["latest"]] == ["Not yours"]


def test_stream_emits_repeatedly(db_session, seed):
    async def _collect():
        return [chunk async for chunk in _notification_event_stream(
            db_session, user_id=seed["owner"].id, max_events=3, poll_interval=0
        )]

    assert len(asyncio.run(_collect())) == 3


def test_stream_401_without_token(client, seed):
    """The only safe way to drive the endpoint itself from TestClient: an auth
    failure returns before streaming begins. A successful request would hang
    forever - the generator is infinite and TestClient has no real network
    disconnect to trigger cleanup, which is exactly why _notification_event_stream
    takes max_events (same constraint as the alerts stream; see
    tests/test_admin_alerts_api.py:274-278)."""
    assert client.get("/notifications/stream").status_code == 401
