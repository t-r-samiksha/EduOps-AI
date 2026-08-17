"""Tests for the parent portal aggregate and the Parent Bot.

SCOPE per the standing testing amendment: security-critical and
silently-wrong-critical only. No payload-shape assertions, no role matrix.

The Gemini call is mocked - the real answers (including the medical-question refusal)
were verified by hand against live data.
"""

from __future__ import annotations

import uuid

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.knowledge import ChatbotLog
from app.models.parent_student import ParentStudent
from app.models.risk import RiskFlag
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int, school_id: int | None = None):
    def _fake():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="t@example.com", role=role, school_id=school_id)

    app.dependency_overrides[get_current_user] = _fake


@pytest.fixture(autouse=True)
def _clear_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _make_user(db_session, role_name, prefix, school):
    role = db_session.query(Role).filter(Role.name == role_name).one()
    user = User(
        supabase_id=uuid.uuid4(), email=f"{prefix}-{uuid.uuid4()}@example.com",
        full_name=prefix, role_id=role.id, school_id=school.id,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def portal_seed(db_session):
    """One parent with ONE linked child, plus an unlinked child in the same class - the
    shape needed to prove the link check does real work rather than just role-gating."""
    school = School(name="Portal Test School")
    db_session.add(school)
    db_session.flush()

    school_class = SchoolClass(
        name="P3 - A", academic_year=ACADEMIC_YEAR, grade_level=3, section="A", school_id=school.id
    )
    db_session.add(school_class)
    db_session.flush()

    parent = _make_user(db_session, "parent", "parent", school)
    linked = _make_user(db_session, "student", "linked", school)
    unlinked = _make_user(db_session, "student", "unlinked", school)

    db_session.add_all([
        ParentStudent(parent_id=parent.id, student_id=linked.id),
        Enrollment(student_id=linked.id, class_id=school_class.id, subject_id=None, is_primary=True),
        Enrollment(student_id=unlinked.id, class_id=school_class.id, subject_id=None, is_primary=True),
    ])
    db_session.commit()
    return {
        "school": school, "class": school_class, "parent": parent,
        "linked": linked, "unlinked": unlinked,
    }


# --- SECURITY: the parent-child link is the boundary -------------------------------


def test_parent_cannot_read_summary_for_an_unlinked_child(client, portal_seed):
    """student_id comes from the URL, so the ParentStudent link is the only thing
    stopping a parent reading another family's child. Same class, so class-level scoping
    would NOT catch this."""
    _override_user("parent", portal_seed["parent"].id, portal_seed["school"].id)
    assert client.get(f"/parent/child/{portal_seed['linked'].id}/summary").status_code == 200
    assert client.get(f"/parent/child/{portal_seed['unlinked'].id}/summary").status_code == 403


def test_parent_bot_cannot_be_asked_about_an_unlinked_child(client, portal_seed, monkeypatch):
    """The frontend child selector is never trusted - student_id is revalidated on every
    ask. Mocked generate() so a leak would still be caught even if the model were
    somehow reached."""
    from app.routers import bots

    monkeypatch.setattr(bots, "generate", lambda system, user: "mocked answer")

    _override_user("parent", portal_seed["parent"].id, portal_seed["school"].id)
    ok = client.post(
        "/bots/parent/ask", json={"query": "how is my child?", "student_id": portal_seed["linked"].id}
    )
    assert ok.status_code == 200

    denied = client.post(
        "/bots/parent/ask", json={"query": "how is this child?", "student_id": portal_seed["unlinked"].id}
    )
    assert denied.status_code == 403


def test_admin_cannot_read_a_summary_from_another_school(client, db_session, portal_seed):
    other_school = School(name="Foreign Portal School")
    db_session.add(other_school)
    db_session.flush()
    foreign_class = SchoolClass(
        name="F3 - A", academic_year=ACADEMIC_YEAR, grade_level=3, section="A", school_id=other_school.id
    )
    db_session.add(foreign_class)
    foreign_student = _make_user(db_session, "student", "foreign", other_school)
    db_session.commit()

    _override_user("admin", portal_seed["parent"].id, portal_seed["school"].id)
    # 404 not 403, so an admin cannot probe another school's user ids by status code.
    assert client.get(f"/parent/child/{foreign_student.id}/summary").status_code == 404


def test_student_cannot_read_the_parent_summary_endpoint(client, portal_seed):
    _override_user("student", portal_seed["linked"].id, portal_seed["school"].id)
    assert client.get(f"/parent/child/{portal_seed['linked'].id}/summary").status_code == 403


# --- SILENTLY WRONG: parent asks must not contaminate Top Doubts -------------------


def test_parent_ask_never_writes_a_query_embedding(client, db_session, portal_seed, monkeypatch):
    """THE contamination guard. Top Doubts clusters chatbot_logs by (school, grade,
    subject) to show teachers what STUDENTS are stuck on, and it skips rows with a null
    embedding. If a parent ask ever embedded its query, "how is my child doing" would
    appear in a teacher's cluster feed as though a child had asked it - a silent,
    plausible-looking corruption of the one feature that reads the same table.

    `db_session` is the very session the request ran in (conftest overrides get_db with
    it), so the row is readable here without leaving the test transaction.
    """
    from app.routers import bots

    monkeypatch.setattr(bots, "generate", lambda system, user: "mocked answer")

    _override_user("parent", portal_seed["parent"].id, portal_seed["school"].id)
    resp = client.post(
        "/bots/parent/ask", json={"query": "how is my child doing?", "student_id": portal_seed["linked"].id}
    )
    assert resp.status_code == 200

    row = (
        db_session.query(ChatbotLog)
        .filter(ChatbotLog.bot_type == "parent", ChatbotLog.user_id == portal_seed["parent"].id)
        .order_by(ChatbotLog.id.desc())
        .first()
    )
    assert row is not None, "no parent log was written"
    assert row.query_embedding is None, "parent ask wrote an embedding - Top Doubts is now contaminated"
    assert row.bot_type == "parent"
    assert row.subject_id is None


# --- SILENTLY WRONG: banner and attendance card must agree ------------------------


def test_summary_attendance_window_matches_the_risk_scorer(client, portal_seed):
    """The at-risk banner quotes an attendance figure produced by the nightly scorer's
    30-day lookback. If this endpoint used a different window, the banner and the card
    directly above it would disagree - which is the exact contradiction the seeded data
    used to show (a flag claiming 60% against a child with zero attendance rows)."""
    from scripts.run_nightly_risk_scoring import ATTENDANCE_LOOKBACK_DAYS

    _override_user("parent", portal_seed["parent"].id, portal_seed["school"].id)
    body = client.get(f"/parent/child/{portal_seed['linked'].id}/summary").json()
    assert body["attendance"]["days"] == ATTENDANCE_LOOKBACK_DAYS


def test_summary_risk_is_null_when_no_open_flag(client, db_session, portal_seed):
    """null is the HEALTHY case and the UI hides the banner on it. A resolved flag must
    not resurrect the banner."""
    _override_user("parent", portal_seed["parent"].id, portal_seed["school"].id)
    assert client.get(f"/parent/child/{portal_seed['linked'].id}/summary").json()["risk"] is None

    db_session.add(
        RiskFlag(
            student_id=portal_seed["linked"].id, risk_level="high", score=0.8,
            reasons=["resolved already"], status="resolved",
        )
    )
    db_session.commit()
    assert client.get(f"/parent/child/{portal_seed['linked'].id}/summary").json()["risk"] is None

    db_session.add(
        RiskFlag(
            student_id=portal_seed["linked"].id, risk_level="medium", score=0.4,
            reasons=["attendance rate 48% is below the 90% threshold"], status="open",
        )
    )
    db_session.commit()
    risk = client.get(f"/parent/child/{portal_seed['linked'].id}/summary").json()["risk"]
    assert risk is not None
    assert risk["level"] == "medium"
    assert risk["reasons"] == ["attendance rate 48% is below the 90% threshold"]
