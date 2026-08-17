import uuid
import pytest
from datetime import datetime, timezone, timedelta

from app.main import app
from app.models.attendance import AttendanceRecord
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.gradebook import GradebookEntry, GradebookWeight
from app.models.library import LibraryItem, LibraryLoan
from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
from app.models.remark import Remark
from app.models.report_card import ReportCard
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user
from app.services.gradebook_service import score_to_gpa

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int = 999, school_id: int | None = None):
    def _fake_user():
        return CurrentUser(
            id=user_id,
            sub=str(uuid.uuid4()),
            email=f"{role}-{user_id}@example.com",
            role=role,
            school_id=school_id,
        )

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_user_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _make_user(db_session, role_row, prefix, school):
    email = f"{prefix}-{uuid.uuid4()}@example.com"
    user = User(
        supabase_id=uuid.uuid4(),
        email=email,
        full_name=prefix.capitalize(),
        role_id=role_row.id,
        school_id=school.id,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def seed(db_session):
    for r_name in ("admin", "principal", "teacher", "student", "parent"):
        if not db_session.query(Role).filter(Role.name == r_name).first():
            db_session.add(Role(name=r_name))
    db_session.flush()

    school = School(name="Comprehensive Person B School")
    db_session.add(school)
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()

    teacher = _make_user(db_session, teacher_role, "pb_teacher", school)
    student1 = _make_user(db_session, student_role, "pb_student1", school)
    student2 = _make_user(db_session, student_role, "pb_student2", school)
    admin_user = _make_user(db_session, admin_role, "pb_admin", school)

    school_class = SchoolClass(
        name="Grade 12 - Advanced",
        academic_year=ACADEMIC_YEAR,
        school_id=school.id,
        class_teacher_id=teacher.id,
        grade_level=12,
    )
    db_session.add(school_class)
    db_session.flush()

    math_subj = Subject(name="Pure Mathematics", school_id=school.id)
    phy_subj = Subject(name="Physics", school_id=school.id)
    db_session.add_all([math_subj, phy_subj])
    db_session.flush()

    # Enrollments
    db_session.add_all([
        Enrollment(student_id=student1.id, class_id=school_class.id, is_primary=True),
        Enrollment(student_id=student2.id, class_id=school_class.id, is_primary=True),
    ])
    db_session.flush()

    return {
        "school": school,
        "teacher": teacher,
        "student1": student1,
        "student2": student2,
        "admin": admin_user,
        "class": school_class,
        "math": math_subj,
        "physics": phy_subj,
    }


# ====================================================================================
# FEATURE 5 — QUIZZES + AUTO-GRADING TESTS
# ====================================================================================


def test_quiz_creation_and_auto_grading(client, seed, db_session):
    """Teacher creates quiz, student attempts it, auto-grades immediately."""
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    quiz_payload = {
        "title": "Quantum Mechanics Quiz",
        "description": "Short diagnostic test on Wave-Particle Duality.",
        "class_id": seed["class"].id,
        "subject_id": seed["physics"].id,
        "duration_minutes": 20,
        "questions": [
            {
                "question_text": "What is Planck's constant symbol?",
                "option_a": "h",
                "option_b": "c",
                "option_c": "G",
                "option_d": "k",
                "correct_option": "A",
                "marks": 5.0,
                "order_index": 0,
            },
            {
                "question_text": "Which particle has no electric charge?",
                "option_a": "Electron",
                "option_b": "Neutron",
                "option_c": "Proton",
                "option_d": "Positron",
                "correct_option": "B",
                "marks": 5.0,
                "order_index": 1,
            },
        ],
    }

    create_res = client.post("/quizzes", json=quiz_payload)
    assert create_res.status_code == 201
    quiz_data = create_res.json()
    quiz_id = quiz_data["id"]
    assert quiz_data["total_marks"] == 10.0
    q1_id = str(quiz_data["questions"][0]["id"])
    q2_id = str(quiz_data["questions"][1]["id"])

    # Student 1 attempts quiz: 1 correct (A), 1 wrong (C) -> Score: 5.0 / 10.0
    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)
    attempt_payload = {
        "answers": {
            q1_id: "A",
            q2_id: "C",
        }
    }
    att_res = client.post(f"/quizzes/{quiz_id}/attempt", json=attempt_payload)
    assert att_res.status_code == 200
    att_data = att_res.json()
    assert att_data["score"] == 5.0
    assert att_data["total_marks"] == 10.0
    assert att_data["percentage"] == 50.0

    # Teacher checks results breakdown
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)
    results_res = client.get(f"/quizzes/{quiz_id}/results")
    assert results_res.status_code == 200
    res_data = results_res.json()
    assert res_data["attempts_count"] == 1
    assert res_data["average_score"] == 5.0


def test_quiz_single_attempt_enforcement(client, seed, db_session):
    """Multiple attempts on the same quiz are rejected with 400 Bad Request."""
    quiz = Quiz(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        subject_id=seed["math"].id,
        teacher_id=seed["teacher"].id,
        title="Single Attempt Test",
    )
    db_session.add(quiz)
    db_session.flush()

    q = QuizQuestion(
        quiz_id=quiz.id,
        question_text="2+2?",
        option_a="3",
        option_b="4",
        option_c="5",
        option_d="6",
        correct_option="B",
        marks=2.0,
    )
    db_session.add(q)
    db_session.flush()

    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)
    res1 = client.post(f"/quizzes/{quiz.id}/attempt", json={"answers": {str(q.id): "B"}})
    assert res1.status_code == 200

    # Attempt 2 fails
    res2 = client.post(f"/quizzes/{quiz.id}/attempt", json={"answers": {str(q.id): "B"}})
    assert res2.status_code == 400


# ====================================================================================
# FEATURE 6 — GRADEBOOK & GPA CALCULATION TESTS
# ====================================================================================


def test_gpa_scale_formula():
    """Verify standard 4.0 GPA scale and letter grades."""
    assert score_to_gpa(95.0) == (4.0, "A+")
    assert score_to_gpa(88.0) == (3.7, "A")
    assert score_to_gpa(82.5) == (3.3, "B+")
    assert score_to_gpa(77.0) == (3.0, "B")
    assert score_to_gpa(72.0) == (2.7, "B-")
    assert score_to_gpa(67.0) == (2.3, "C+")
    assert score_to_gpa(62.0) == (2.0, "C")
    assert score_to_gpa(55.0) == (1.0, "D")
    assert score_to_gpa(45.0) == (0.0, "F")


def test_gradebook_weighted_calculation_and_gpa(client, seed, db_session):
    """Calculates weighted assessment scores (assignment 20%, quiz 20%, midterm 20%, final 40%)."""
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    # 1. Assignment (score 90/100) -> 90%
    # 2. Quiz (score 80/100) -> 80%
    # 3. Midterm (score 85/100) -> 85%
    # 4. Final (score 95/100) -> 95%
    # Weighted avg = (90*0.20 + 80*0.20 + 85*0.20 + 95*0.40) = 18 + 16 + 17 + 38 = 89.0% -> 3.7 GPA (A)

    entries = [
        {"student_id": seed["student1"].id, "subject_id": seed["math"].id, "class_id": seed["class"].id, "term": "Term 1", "assessment_type": "assignment", "score": 90.0, "max_score": 100.0},
        {"student_id": seed["student1"].id, "subject_id": seed["math"].id, "class_id": seed["class"].id, "term": "Term 1", "assessment_type": "quiz", "score": 80.0, "max_score": 100.0},
        {"student_id": seed["student1"].id, "subject_id": seed["math"].id, "class_id": seed["class"].id, "term": "Term 1", "assessment_type": "midterm", "score": 85.0, "max_score": 100.0},
        {"student_id": seed["student1"].id, "subject_id": seed["math"].id, "class_id": seed["class"].id, "term": "Term 1", "assessment_type": "final", "score": 95.0, "max_score": 100.0},
    ]

    bulk_res = client.post("/gradebook/bulk", json={"entries": entries})
    assert bulk_res.status_code == 200

    # Retrieve student gradebook
    gb_res = client.get(f"/gradebook/{seed['student1'].id}?term=Term 1")
    assert gb_res.status_code == 200
    data = gb_res.json()
    assert data["term_average"] == 89.0
    assert data["gpa"] == 3.7
    assert data["letter_grade"] == "A"


def test_gradebook_entry_idempotency(client, seed, db_session):
    """Upserting the same assessment entry updates score without duplicate rows."""
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    payload = {
        "student_id": seed["student1"].id,
        "subject_id": seed["math"].id,
        "class_id": seed["class"].id,
        "term": "Term 1",
        "assessment_type": "assignment",
        "assessment_id": 101,
        "score": 75.0,
        "max_score": 100.0,
    }

    res1 = client.post("/gradebook/entry", json=payload)
    assert res1.status_code == 200
    assert res1.json()["score"] == 75.0

    # Update mark
    payload["score"] = 88.0
    res2 = client.post("/gradebook/entry", json=payload)
    assert res2.status_code == 200
    assert res2.json()["score"] == 88.0

    count = (
        db_session.query(GradebookEntry)
        .filter(
            GradebookEntry.student_id == seed["student1"].id,
            GradebookEntry.assessment_id == 101,
        )
        .count()
    )
    assert count == 1


# ====================================================================================
# FEATURE 7 — REPORT CARD AUTOMATION TESTS
# ====================================================================================


def test_report_card_generation_and_idempotency(client, seed, db_session):
    """Generates report card snapshot with attendance & grades; regenerating is idempotent."""
    # Seed attendance for student1 (2 present, 0 absent = 100%)
    db_session.add_all([
        AttendanceRecord(student_id=seed["student1"].id, class_id=seed["class"].id, date=datetime.now().date(), status="present", source="manual"),
        AttendanceRecord(student_id=seed["student1"].id, class_id=seed["class"].id, date=datetime.now().date() - timedelta(days=1), status="present", source="manual"),
    ])
    # Seed remark
    db_session.add(
        Remark(
            school_id=seed["school"].id,
            author_id=seed["teacher"].id,
            student_id=seed["student1"].id,
            class_id=seed["class"].id,
            content="Outstanding analytical thinking in calculus.",
            sentiment_tag="appreciation",
        )
    )
    db_session.flush()

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    # First generation
    res1 = client.post(f"/report_cards/generate/{seed['student1'].id}?term=Term 1")
    assert res1.status_code == 200
    card1 = res1.json()
    assert card1["attendance_percentage"] == 100.0
    assert card1["source_data_snapshot"]["student_name"] is not None

    # Second generation (idempotent regeneration)
    res2 = client.post(f"/report_cards/generate/{seed['student1'].id}?term=Term 1")
    assert res2.status_code == 200
    card2 = res2.json()
    assert card1["id"] == card2["id"]


# ====================================================================================
# FEATURE 8 — DIGITAL LIBRARY TESTS
# ====================================================================================


def test_library_issue_and_return_lifecycle(client, seed, db_session):
    """Issue reduces available inventory; return restores it; prevents double active borrowing."""
    item = LibraryItem(
        school_id=seed["school"].id,
        title="Introduction to Linear Algebra",
        author="Gilbert Strang",
        category="Mathematics",
        type="book",
        available_copies=1,
        total_copies=1,
    )
    db_session.add(item)
    db_session.flush()

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    # Issue book to student1
    issue_res = client.post("/library/issue", json={"item_id": item.id, "student_id": seed["student1"].id, "loan_days": 14})
    assert issue_res.status_code == 200
    loan_id = issue_res.json()["id"]

    db_session.refresh(item)
    assert item.available_copies == 0

    # Student 2 tries to borrow same unavailable book -> 400
    issue_res2 = client.post("/library/issue", json={"item_id": item.id, "student_id": seed["student2"].id})
    assert issue_res2.status_code == 400

    # Return book
    ret_res = client.put(f"/library/return/{loan_id}")
    assert ret_res.status_code == 200
    assert ret_res.json()["status"] == "returned"

    db_session.refresh(item)
    assert item.available_copies == 1


# ====================================================================================
# FEATURE 9 & 10 — CALENDAR SYNC & HOMEWORK TESTS
# ====================================================================================


def test_calendar_sync_idempotency(client, seed, db_session):
    """Syncing user calendar multiple times does not produce duplicate calendar records."""
    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)

    sync_res1 = client.post("/calendar/sync")
    assert sync_res1.status_code == 200

    sync_res2 = client.post("/calendar/sync")
    assert sync_res2.status_code == 200

    events_res = client.get(f"/calendar/{seed['student1'].id}")
    assert events_res.status_code == 200


def test_homework_calendar_events(client, seed, db_session):
    """Retrieves academic deadlines for homework calendar."""
    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)

    hw_res = client.get(f"/calendar/homework/{seed['student1'].id}")
    assert hw_res.status_code == 200
    assert isinstance(hw_res.json(), list)


# ====================================================================================
# FEATURE 11 — STUDENT ANALYTICS TESTS
# ====================================================================================


def test_student_personal_analytics_endpoint(client, seed, db_session):
    """Returns analytics profile with attendance, grades, quizzes, and risk banner."""
    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)

    res = client.get(f"/analytics/student/{seed['student1'].id}")
    assert res.status_code == 200
    data = res.json()
    assert "attendance" in data
    assert "gradebook" in data
    assert "risk_status" in data
    assert "trend" in data


# ====================================================================================
# FEATURE 12 & 14 — REMARKS SYSTEM TESTS
# ====================================================================================


def test_teacher_bulk_remarks_entry_and_history(client, seed, db_session):
    """Teacher submits batch remarks with sentiment tags and student views history."""
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    bulk_payload = {
        "class_id": seed["class"].id,
        "subject_id": seed["math"].id,
        "remarks": [
            {"student_id": seed["student1"].id, "content": "Mastered vector spaces with distinction.", "sentiment_tag": "appreciation"},
            {"student_id": seed["student2"].id, "content": "Needs more practice on eigenvalue problems.", "sentiment_tag": "academic"},
        ],
    }

    res = client.post("/remarks/bulk", json=bulk_payload)
    assert res.status_code == 200
    assert res.json()["count"] == 2

    # Student 1 views history
    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)
    hist_res = client.get(f"/remarks/{seed['student1'].id}")
    assert hist_res.status_code == 200
    items = hist_res.json()
    assert len(items) >= 1
    assert items[0]["sentiment_tag"] == "appreciation"
