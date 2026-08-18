"""Tests for Teacher Assistant Bot API (POST /bots/teacher/ask).

Verifies teacher-scoped RAG retrieval, citation metadata, quiz & lesson planning modes,
cross-grade authorization checks, and student rejection.
"""

from __future__ import annotations

from datetime import time
import uuid
import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.knowledge import ChatbotLog
from app.models.resource import Resource
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user
from app.services.llm import EMBEDDING_DIMENSIONS
from app.services.retrieval import RetrievedChunk

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int, school_id: int | None):
    def _fake_user():
        return CurrentUser(
            id=user_id,
            sub=str(uuid.uuid4()),
            email=f"teacher_{user_id}@example.com",
            role=role,
            school_id=school_id,
        )

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _get_or_create_role(db_session, role_name: str) -> Role:
    role = db_session.query(Role).filter(Role.name == role_name).first()
    if not role:
        role = Role(name=role_name)
        db_session.add(role)
        db_session.flush()
    return role


def _make_school_and_teacher(db_session, email_prefix="teacher"):
    for r_name in ("admin", "principal", "teacher", "student", "parent"):
        _get_or_create_role(db_session, r_name)

    school = School(name=f"School-{uuid.uuid4()}")
    db_session.add(school)
    db_session.flush()

    teacher_role = _get_or_create_role(db_session, "teacher")
    teacher = User(
        supabase_id=uuid.uuid4(),
        email=f"{email_prefix}-{uuid.uuid4()}@example.com",
        full_name="Meera Sharma",
        role_id=teacher_role.id,
        school_id=school.id,
    )
    db_session.add(teacher)
    db_session.flush()

    subject = Subject(name="Physics", school_id=school.id)
    db_session.add(subject)
    db_session.flush()

    school_class = SchoolClass(
        name="Class 9A",
        grade_level=9,
        school_id=school.id,
        academic_year=ACADEMIC_YEAR,
    )
    db_session.add(school_class)
    db_session.flush()

    room = Room(name="Room 101", capacity=30, school_id=school.id)
    db_session.add(room)
    db_session.flush()

    slot = TimetableSlot(
        day_of_week=0,
        period_number=1,
        start_time=time(9, 0),
        end_time=time(9, 45),
        class_id=school_class.id,
        subject_id=subject.id,
        teacher_id=teacher.id,
        room_id=room.id,
        academic_year=ACADEMIC_YEAR,
        is_active=True,
    )
    db_session.add(slot)
    db_session.flush()

    return school, teacher, subject, school_class


def test_teacher_asks_grounded_quiz_question_with_citations(db_session, client, monkeypatch):
    school, teacher, subject, school_class = _make_school_and_teacher(db_session)
    res = Resource(
        school_id=school.id,
        uploaded_by=teacher.id,
        title="Physics Unit 1 Notes",
        grade_level=9,
        subject_id=subject.id,
        file_url="https://example.com/physics.pdf",
        mime_type="application/pdf",
        file_size=1024,
    )
    db_session.add(res)
    db_session.commit()

    query_vector = [0.0] * EMBEDDING_DIMENSIONS
    query_vector[0] = 1.0
    monkeypatch.setattr("app.routers.bots.embed_query", lambda q: query_vector)
    monkeypatch.setattr(
        "app.routers.bots.search_chunks_for_teacher",
        lambda db, **kwargs: [
            RetrievedChunk(
                chunk_id=101,
                source_id=res.id,
                chunk_text="Newton's First Law: An object remains at rest or in uniform motion unless acted on by force.",
                distance=0.1,
                title="Physics Unit 1 Notes",
                subject_id=subject.id,
            )
        ],
    )
    monkeypatch.setattr(
        "app.routers.bots.generate",
        lambda sys, usr: "Generated 5 MCQs on Newton's First Law.\n\nQuestion 1: What is inertia?\nA) Force\nB) Resistance to change\nCorrect Answer: B",
    )

    _override_user("teacher", user_id=teacher.id, school_id=school.id)

    response = client.post(
        "/bots/teacher/ask",
        json={"query": "Create 5 MCQs from Physics Unit 1", "grade_level": 9, "subject_id": subject.id},
    )
    assert response.status_code == 200
    data = response.json()

    assert "Generated 5 MCQs" in data["answer"]
    assert data["mode"] == "quiz"
    assert len(data["citations"]) >= 1
    assert data["citations"][0]["title"] == "Physics Unit 1 Notes"
    assert "Newton's First Law" in data["citations"][0]["snippet"]

    # Verify ChatbotLog was written
    log = (
        db_session.query(ChatbotLog)
        .filter(ChatbotLog.user_id == teacher.id, ChatbotLog.bot_type == "teacher")
        .first()
    )
    assert log is not None
    assert log.query == "Create 5 MCQs from Physics Unit 1"
    assert log.kb_chunks_used is not None


def test_teacher_asks_lesson_plan(db_session, client, monkeypatch):
    school, teacher, subject, school_class = _make_school_and_teacher(db_session)
    query_vector = [0.0] * EMBEDDING_DIMENSIONS
    monkeypatch.setattr("app.routers.bots.embed_query", lambda q: query_vector)
    monkeypatch.setattr(
        "app.routers.bots.search_chunks_for_teacher",
        lambda db, **kwargs: [],
    )
    monkeypatch.setattr(
        "app.routers.bots.generate",
        lambda sys, usr: "### 40-Minute Lesson Plan: Kinematics\n- Objectives: ...\n- Warm-Up (5 min): ...",
    )

    _override_user("teacher", user_id=teacher.id, school_id=school.id)

    response = client.post(
        "/bots/teacher/ask",
        json={"query": "Create a 40-minute lesson plan for Kinematics", "grade_level": 9},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "lesson_plan"
    assert "Lesson Plan" in data["answer"]


def test_unauthorized_teacher_wrong_grade_rejected(db_session, client):
    school, teacher, subject, school_class = _make_school_and_teacher(db_session)
    _override_user("teacher", user_id=teacher.id, school_id=school.id)

    # Teacher teaches grade 9, attempting to query grade 12
    response = client.post(
        "/bots/teacher/ask",
        json={"query": "Give me notes for Grade 12", "grade_level": 12},
    )
    assert response.status_code == 403
    assert "You do not teach this grade" in response.json()["detail"]


def test_empty_query_rejected(db_session, client):
    school, teacher, subject, school_class = _make_school_and_teacher(db_session)
    _override_user("teacher", user_id=teacher.id, school_id=school.id)

    response = client.post("/bots/teacher/ask", json={"query": "   "})
    assert response.status_code == 400
    assert "query must not be empty" in response.json()["detail"]


def test_student_cannot_call_teacher_bot(db_session, client):
    school, teacher, subject, school_class = _make_school_and_teacher(db_session)
    student_role = _get_or_create_role(db_session, "student")
    student = User(
        supabase_id=uuid.uuid4(),
        email=f"student-{uuid.uuid4()}@example.com",
        full_name="Student One",
        role_id=student_role.id,
        school_id=school.id,
    )
    db_session.add(student)
    db_session.commit()

    _override_user("student", user_id=student.id, school_id=school.id)

    response = client.post("/bots/teacher/ask", json={"query": "Create 5 MCQs"})
    assert response.status_code == 403
