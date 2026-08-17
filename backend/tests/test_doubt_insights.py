"""Tests for Top Doubts (Step 8): clustering branching logic, teacher resolution, and
the teacher authorization boundary.

SCOPE per Day 2's testing amendment: the clustering function (real branching), the
grade-level teacher resolution (real branching, incl. the fallback), and the security
boundary. No payload-shape assertions, no role matrix, no CRUD.

Gemini labelling is never called: every test passes `label=False`, or goes through an
endpoint with logs below the clustering minimum. The labels were verified live once
against real seeded data.
"""

from __future__ import annotations

import uuid

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.knowledge import ChatbotLog
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room, TeacherSubject, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user
from app.services.doubt_insights import (
    DEFAULT_THRESHOLD,
    MIN_LOGS_FOR_CLUSTERING,
    grade_subject_pairs_for_teacher,
    teachers_for_grade_subject,
    top_doubts,
)

ACADEMIC_YEAR = "2026-27"
DIM = 1536


def _override_user(role: str, user_id: int = 999, school_id: int | None = None):
    def _fake():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="t@example.com", role=role, school_id=school_id)

    app.dependency_overrides[get_current_user] = _fake


@pytest.fixture(autouse=True)
def _clear_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _vec(axis: int, *, tilt: float = 0.0, tilt_axis: int = 500) -> list[float]:
    """A near-one-hot vector. `tilt` bends it toward another axis by a known amount, so
    a test can place two questions at a chosen cosine distance from each other instead
    of hoping real embeddings land where the assertion needs them."""
    v = [0.0] * DIM
    v[axis] = 1.0
    if tilt:
        v[tilt_axis] = tilt
    norm = sum(x * x for x in v) ** 0.5
    return [x / norm for x in v]


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
def grade_seed(db_session):
    """One school, one grade, TWO sections, one shared Math teacher - the exact shape
    the cross-section insight depends on."""
    school = School(name="Doubts Test School")
    db_session.add(school)
    db_session.flush()

    math = Subject(name="Math", school_id=school.id)
    science = Subject(name="Science", school_id=school.id)
    db_session.add_all([math, science])
    room = Room(name="R1", capacity=30, school_id=school.id)
    db_session.add(room)
    db_session.flush()

    shared_teacher = _make_user(db_session, "teacher", "shared", school)
    other_teacher = _make_user(db_session, "teacher", "other", school)

    section_a = SchoolClass(name="G4 - A", academic_year=ACADEMIC_YEAR, grade_level=4, section="A", school_id=school.id)
    section_b = SchoolClass(name="G4 - B", academic_year=ACADEMIC_YEAR, grade_level=4, section="B", school_id=school.id)
    db_session.add_all([section_a, section_b])
    db_session.flush()

    # The shared teacher teaches Math to BOTH sections.
    for index, section in enumerate((section_a, section_b)):
        db_session.add(
            TimetableSlot(
                day_of_week=1, period_number=index + 1,
                start_time=__import__("datetime").time(9 + index), end_time=__import__("datetime").time(10 + index),
                subject_id=math.id, teacher_id=shared_teacher.id, class_id=section.id,
                room_id=room.id, academic_year=ACADEMIC_YEAR, is_active=True,
            )
        )
    students = [_make_user(db_session, "student", f"s{i}", school) for i in range(4)]
    db_session.commit()
    return {
        "school": school, "math": math, "science": science, "section_a": section_a, "section_b": section_b,
        "shared_teacher": shared_teacher, "other_teacher": other_teacher, "students": students, "room": room,
    }


def _log(db_session, seed, *, section, student, embedding, query="q", subject=None):
    row = ChatbotLog(
        user_id=student.id, bot_type="student", query=query, response="r", kb_chunks_used={"chunk_ids": []},
        query_embedding=embedding, class_id=section.id,
        subject_id=(subject or seed["math"]).id,
    )
    db_session.add(row)
    return row


# --- BRANCHING: greedy clustering --------------------------------------------------


def test_near_questions_from_two_sections_form_one_cross_section_cluster(db_session, grade_seed):
    """THE feature. Same confusion in two rooms must be ONE cluster carrying both
    section names - aggregating by class_id would split it and bury the signal."""
    near = _vec(0)
    nearly = _vec(0, tilt=0.15)
    _log(db_session, grade_seed, section=grade_seed["section_a"], student=grade_seed["students"][0], embedding=near)
    _log(db_session, grade_seed, section=grade_seed["section_b"], student=grade_seed["students"][1], embedding=nearly)
    _log(db_session, grade_seed, section=grade_seed["section_a"], student=grade_seed["students"][2], embedding=near)
    db_session.commit()

    clusters = top_doubts(db_session, school_id=grade_seed["school"].id, grade_level=4, label=False)
    assert len(clusters) == 1
    assert clusters[0].question_count == 3
    assert clusters[0].sections == ["G4 - A", "G4 - B"]
    assert clusters[0].distinct_student_count == 3


def test_distant_questions_stay_in_separate_clusters(db_session, grade_seed):
    """Orthogonal vectors are distance 1.0, far above any sane threshold. If these
    merged, the threshold comparison would be inverted or unapplied."""
    for index, student in enumerate(grade_seed["students"][:3]):
        _log(db_session, grade_seed, section=grade_seed["section_a"], student=student, embedding=_vec(index * 100))
    db_session.commit()

    clusters = top_doubts(db_session, school_id=grade_seed["school"].id, grade_level=4, label=False)
    assert len(clusters) == 3
    assert all(c.question_count == 1 for c in clusters)


def test_threshold_controls_merging(db_session, grade_seed):
    """The tuned DEFAULT_THRESHOLD is a real boundary, not decoration - the same input
    must split at a tighter threshold and merge at a looser one."""
    a = _vec(0)
    b = _vec(0, tilt=0.9)  # deliberately mid-distance
    for student, embedding in zip(grade_seed["students"], (a, b, a)):
        _log(db_session, grade_seed, section=grade_seed["section_a"], student=student, embedding=embedding)
    db_session.commit()

    tight = top_doubts(db_session, school_id=grade_seed["school"].id, grade_level=4, threshold=0.05, label=False)
    loose = top_doubts(db_session, school_id=grade_seed["school"].id, grade_level=4, threshold=0.95, label=False)
    assert len(tight) > len(loose)
    assert len(loose) == 1


def test_clusters_ranked_by_size_then_distinct_students(db_session, grade_seed):
    """A cluster from many children must outrank one child asking repeatedly."""
    big = _vec(0)
    small = _vec(400)
    for student in grade_seed["students"][:3]:
        _log(db_session, grade_seed, section=grade_seed["section_a"], student=student, embedding=big)
    _log(db_session, grade_seed, section=grade_seed["section_a"], student=grade_seed["students"][3], embedding=small)
    db_session.commit()

    clusters = top_doubts(db_session, school_id=grade_seed["school"].id, grade_level=4, label=False)
    assert clusters[0].question_count == 3
    assert clusters[0].question_count >= clusters[-1].question_count


def test_logs_without_an_embedding_are_skipped_not_crashed(db_session, grade_seed):
    """query_embedding is nullable (a backfilled row, or a log written on a path that
    didn't embed). Clustering must skip those rather than blow up on None."""
    for student in grade_seed["students"][:3]:
        _log(db_session, grade_seed, section=grade_seed["section_a"], student=student, embedding=_vec(0))
    _log(db_session, grade_seed, section=grade_seed["section_a"], student=grade_seed["students"][3], embedding=None)
    db_session.commit()

    clusters = top_doubts(db_session, school_id=grade_seed["school"].id, grade_level=4, label=False)
    assert sum(c.question_count for c in clusters) == 3


def test_degrades_to_recent_questions_below_the_clustering_minimum(db_session, grade_seed):
    """Fewer than MIN_LOGS_FOR_CLUSTERING must return honest unlabelled recents - never
    a crash and never a blank panel."""
    _log(db_session, grade_seed, section=grade_seed["section_a"], student=grade_seed["students"][0],
         embedding=_vec(0), query="only question")
    db_session.commit()
    assert MIN_LOGS_FOR_CLUSTERING > 1

    clusters = top_doubts(db_session, school_id=grade_seed["school"].id, grade_level=4, label=False)
    assert len(clusters) == 1
    assert clusters[0].label is None
    assert clusters[0].sample_questions == ["only question"]


def test_other_schools_logs_never_leak_into_a_grade(db_session, grade_seed):
    """Cross-tenant: grade_level 4 exists in other schools too, so the school filter is
    load-bearing, not incidental."""
    other_school = School(name="Foreign School")
    db_session.add(other_school)
    db_session.flush()
    foreign_class = SchoolClass(
        name="G4 - A", academic_year=ACADEMIC_YEAR, grade_level=4, section="A", school_id=other_school.id
    )
    db_session.add(foreign_class)
    foreign_student = _make_user(db_session, "student", "foreign", other_school)
    db_session.flush()
    db_session.add(
        ChatbotLog(
            user_id=foreign_student.id, bot_type="student", query="foreign question", response="r",
            kb_chunks_used={"chunk_ids": []}, query_embedding=_vec(0), class_id=foreign_class.id, subject_id=None,
        )
    )
    for student in grade_seed["students"][:3]:
        _log(db_session, grade_seed, section=grade_seed["section_a"], student=student, embedding=_vec(0), query="ours")
    db_session.commit()

    clusters = top_doubts(db_session, school_id=grade_seed["school"].id, grade_level=4, label=False)
    assert all("foreign question" not in c.sample_questions for c in clusters)
    assert sum(c.question_count for c in clusters) == 3


# --- BRANCHING: teacher resolution -------------------------------------------------


def test_teacher_resolution_prefers_timetable_slots(db_session, grade_seed):
    """Actual teaching assignment, not mere qualification. The other teacher is
    QUALIFIED for Math but has no slots, so must not be resolved."""
    db_session.add(TeacherSubject(teacher_id=grade_seed["other_teacher"].id, subject_id=grade_seed["math"].id))
    db_session.commit()

    resolved = teachers_for_grade_subject(
        db_session, school_id=grade_seed["school"].id, grade_level=4, subject_id=grade_seed["math"].id
    )
    assert resolved == [grade_seed["shared_teacher"].id]
    assert grade_seed["other_teacher"].id not in resolved


def test_teacher_resolution_falls_back_to_teacher_subjects_without_slots(db_session, grade_seed):
    """A grade with no generated timetable would otherwise have nobody to notify."""
    db_session.add(TeacherSubject(teacher_id=grade_seed["other_teacher"].id, subject_id=grade_seed["science"].id))
    db_session.commit()

    resolved = teachers_for_grade_subject(
        db_session, school_id=grade_seed["school"].id, grade_level=4, subject_id=grade_seed["science"].id
    )
    assert resolved == [grade_seed["other_teacher"].id]


def test_grade_subject_pairs_reflect_what_a_teacher_actually_teaches(db_session, grade_seed):
    pairs = grade_subject_pairs_for_teacher(db_session, teacher_id=grade_seed["shared_teacher"].id)
    assert (4, grade_seed["math"].id, "Math") in pairs
    assert grade_subject_pairs_for_teacher(db_session, teacher_id=grade_seed["other_teacher"].id) == []


# --- SECURITY: endpoint authorization ----------------------------------------------


def test_teacher_cannot_query_a_subject_they_do_not_teach(client, db_session, grade_seed):
    """Same class of hole as the Doubt Bot's class_id check - without it any teacher
    could read any grade's confusions by editing the query string."""
    _override_user("teacher", user_id=grade_seed["shared_teacher"].id, school_id=grade_seed["school"].id)
    denied = client.get(
        "/bots/insights/top-doubts", params={"grade_level": 4, "subject_id": grade_seed["science"].id}
    )
    assert denied.status_code == 403

    allowed = client.get(
        "/bots/insights/top-doubts", params={"grade_level": 4, "subject_id": grade_seed["math"].id}
    )
    assert allowed.status_code == 200


def test_teacher_cannot_query_a_grade_they_do_not_teach(client, grade_seed):
    _override_user("teacher", user_id=grade_seed["shared_teacher"].id, school_id=grade_seed["school"].id)
    assert client.get("/bots/insights/top-doubts", params={"grade_level": 9}).status_code == 403


def test_student_is_rejected_from_the_insights_endpoint(client, grade_seed):
    """Top Doubts is a teaching tool - a student must not read what their class is
    collectively confused about."""
    _override_user("student", user_id=grade_seed["students"][0].id, school_id=grade_seed["school"].id)
    assert client.get("/bots/insights/top-doubts", params={"grade_level": 4}).status_code == 403


def test_insights_endpoint_requires_authentication(client):
    assert client.get("/bots/insights/top-doubts", params={"grade_level": 4}).status_code == 401
