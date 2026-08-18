import uuid
import pytest
from datetime import datetime, timezone, timedelta
from io import BytesIO

from app.main import app
from app.models.assignment import Assignment, AssignmentSubmission
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.notification import Notification
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.user import User
from app.services.assignment_service import (
    DEADLINE_SCAN_LOOKBACK_DAYS,
    detect_assignment_deadlines_and_missing,
)
from app.services.auth import CurrentUser, get_current_user

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

    school = School(name="Assignment Test School")
    db_session.add(school)
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    teacher = _make_user(db_session, teacher_role, "teacher1", school)
    other_teacher = _make_user(db_session, teacher_role, "teacher2", school)

    student_enrolled = _make_user(db_session, student_role, "student_enrolled", school)
    other_student = _make_user(db_session, student_role, "other_student", school)
    student_not_enrolled = _make_user(db_session, student_role, "student_not_enrolled", school)

    school_class = SchoolClass(
        name="Grade 10 - A",
        academic_year=ACADEMIC_YEAR,
        school_id=school.id,
        class_teacher_id=teacher.id,
        grade_level=10,
    )
    other_class = SchoolClass(
        name="Grade 10 - B",
        academic_year=ACADEMIC_YEAR,
        school_id=school.id,
        class_teacher_id=other_teacher.id,
        grade_level=10,
    )
    db_session.add_all([school_class, other_class])
    db_session.flush()

    math_subj = Subject(name="Calculus", school_id=school.id)
    db_session.add(math_subj)
    db_session.flush()

    # Enroll students
    db_session.add_all([
        Enrollment(student_id=student_enrolled.id, class_id=school_class.id, is_primary=True),
        Enrollment(student_id=other_student.id, class_id=school_class.id, is_primary=True),
        Enrollment(student_id=student_not_enrolled.id, class_id=other_class.id, is_primary=True),
    ])
    db_session.flush()

    return {
        "school": school,
        "admin": admin_user,
        "teacher": teacher,
        "other_teacher": other_teacher,
        "student_enrolled": student_enrolled,
        "other_student": other_student,
        "student_not_enrolled": student_not_enrolled,
        "class": school_class,
        "other_class": other_class,
        "subject": math_subj,
    }


def test_create_assignment(client, seed, db_session):
    """Teacher creates an assignment with deadline and max marks."""
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    future_deadline = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    payload = {
        "title": "Problem Set 4: Differential Equations",
        "description": "Complete all exercises from section 4.2.",
        "deadline": future_deadline,
        "class_id": seed["class"].id,
        "subject_id": seed["subject"].id,
        "max_marks": 50.0,
    }

    res = client.post("/assignments", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Problem Set 4: Differential Equations"
    assert data["max_marks"] == 50.0
    assert data["class_name"] == "Grade 10 - A"
    assert data["subject_name"] == "Calculus"

    # Verify notification dispatched to enrolled students
    notif = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == seed["student_enrolled"].id,
            Notification.source_type == "assignment_created",
        )
        .first()
    )
    assert notif is not None
    assert "Problem Set 4" in notif.title


def test_unauthorized_teacher_cannot_create(client, seed):
    """Teacher not assigned to the class gets 403 Forbidden."""
    _override_user("teacher", user_id=seed["other_teacher"].id, school_id=seed["school"].id)

    payload = {
        "title": "Unauthorized Assignment",
        "deadline": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "class_id": seed["class"].id,
    }

    res = client.post("/assignments", json=payload)
    assert res.status_code == 403


def test_student_submission_on_time(client, seed, db_session):
    """Student submits before deadline -> status is 'submitted'."""
    future_deadline = datetime.now(timezone.utc) + timedelta(days=2)
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        subject_id=seed["subject"].id,
        teacher_id=seed["teacher"].id,
        title="Physics Lab Report",
        deadline=future_deadline,
        max_marks=100.0,
    )
    db_session.add(assignment)
    db_session.flush()

    _override_user("student", user_id=seed["student_enrolled"].id, school_id=seed["school"].id)

    payload = {
        "file_url": "https://storage.example.com/lab_report.pdf",
        "file_name": "lab_report.pdf",
        "file_size": 102400,
    }

    res = client.post(f"/assignments/{assignment.id}/submit", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "submitted"
    assert data["file_name"] == "lab_report.pdf"


def test_student_submission_late(client, seed, db_session):
    """Student submits after deadline -> status is 'late'."""
    past_deadline = datetime.now(timezone.utc) - timedelta(hours=3)
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        subject_id=seed["subject"].id,
        teacher_id=seed["teacher"].id,
        title="Late Essay",
        deadline=past_deadline,
        max_marks=100.0,
    )
    db_session.add(assignment)
    db_session.flush()

    _override_user("student", user_id=seed["student_enrolled"].id, school_id=seed["school"].id)

    payload = {
        "file_url": "https://storage.example.com/late_essay.docx",
        "file_name": "late_essay.docx",
        "file_size": 20480,
    }

    res = client.post(f"/assignments/{assignment.id}/submit", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "late"


def test_missing_submission_detection(client, seed, db_session):
    """Scheduled task detects past deadlines and marks missing submissions."""
    past_deadline = datetime.now(timezone.utc) - timedelta(days=1)
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        subject_id=seed["subject"].id,
        teacher_id=seed["teacher"].id,
        title="Past Project",
        deadline=past_deadline,
        max_marks=100.0,
    )
    db_session.add(assignment)
    db_session.flush()

    # Run detection service
    result = detect_assignment_deadlines_and_missing(db_session)
    assert result["missing_marked"] >= 2  # student_enrolled and other_student

    # Verify missing submission record in DB
    missing_sub = (
        db_session.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.assignment_id == assignment.id,
            AssignmentSubmission.student_id == seed["student_enrolled"].id,
        )
        .first()
    )
    assert missing_sub is not None
    assert missing_sub.status == "missing"


def test_deadline_job_is_idempotent(client, seed, db_session):
    """A second run the same night must not re-nudge anyone.

    Guards the scheduled job (scheduler.py JOB_ID_ASSIGNMENT_DEADLINES). The missing path
    is self-limiting via its status="missing" row; the reminder path needed an explicit
    guard, since it dispatched to every unsubmitted student on every invocation.
    """
    now = datetime.now(timezone.utc)
    past = Assignment(
        school_id=seed["school"].id, class_id=seed["class"].id,
        subject_id=seed["subject"].id, teacher_id=seed["teacher"].id,
        title="Overdue", deadline=now - timedelta(days=1), max_marks=100.0,
    )
    soon = Assignment(
        school_id=seed["school"].id, class_id=seed["class"].id,
        subject_id=seed["subject"].id, teacher_id=seed["teacher"].id,
        title="Due tomorrow", deadline=now + timedelta(hours=6), max_marks=100.0,
    )
    db_session.add_all([past, soon])
    db_session.flush()

    first = detect_assignment_deadlines_and_missing(db_session)
    assert first["missing_marked"] >= 2
    assert first["reminders_sent"] >= 2, "the 24h window should have fired once"

    def _counts():
        return (
            db_session.query(Notification)
            .filter(Notification.source_type == "assignment_missing").count(),
            db_session.query(Notification)
            .filter(Notification.source_type == "assignment_reminder").count(),
        )

    after_first = _counts()
    second = detect_assignment_deadlines_and_missing(db_session)
    assert second == {"missing_marked": 0, "reminders_sent": 0}
    assert _counts() == after_first, "second run created notifications"

    third = detect_assignment_deadlines_and_missing(db_session)
    assert third == {"missing_marked": 0, "reminders_sent": 0}
    assert _counts() == after_first


def test_deadline_scan_ignores_assignments_older_than_lookback(client, seed, db_session):
    """An assignment past the lookback window is not resurrected.

    Without the bound, a student enrolling mid-year was marked missing - and notified -
    for every assignment ever set in the class.
    """
    ancient = Assignment(
        school_id=seed["school"].id, class_id=seed["class"].id,
        subject_id=seed["subject"].id, teacher_id=seed["teacher"].id,
        title="Last term's essay",
        deadline=datetime.now(timezone.utc)
        - timedelta(days=DEADLINE_SCAN_LOOKBACK_DAYS + 5),
        max_marks=100.0,
    )
    db_session.add(ancient)
    db_session.flush()

    result = detect_assignment_deadlines_and_missing(db_session)
    assert result["missing_marked"] == 0
    assert (
        db_session.query(AssignmentSubmission)
        .filter(AssignmentSubmission.assignment_id == ancient.id).count() == 0
    )


def test_teacher_grades_submission(client, seed, db_session):
    """Teacher grades student submission with marks & feedback."""
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        subject_id=seed["subject"].id,
        teacher_id=seed["teacher"].id,
        title="Math Homework",
        deadline=datetime.now(timezone.utc) + timedelta(days=2),
        max_marks=20.0,
    )
    db_session.add(assignment)
    db_session.flush()

    submission = AssignmentSubmission(
        assignment_id=assignment.id,
        student_id=seed["student_enrolled"].id,
        file_url="https://example.com/math.pdf",
        status="submitted",
        submitted_at=datetime.now(timezone.utc),
    )
    db_session.add(submission)
    db_session.flush()

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    grade_payload = {
        "grade": 18.5,
        "feedback": "Excellent step-by-step working. Minor arithmetic slip on problem 3.",
    }

    res = client.put(f"/assignments/{assignment.id}/grade/{submission.id}", json=grade_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["grade"] == 18.5
    assert data["status"] == "graded"
    assert "arithmetic slip" in data["feedback"]

    # Verify notification dispatched to student
    notif = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == seed["student_enrolled"].id,
            Notification.source_type == "assignment_graded",
        )
        .first()
    )
    assert notif is not None
    assert "18.5/20.0" in notif.body


def test_invalid_grade_validation(client, seed, db_session):
    """Grading higher than max_marks or below 0 returns 422 error."""
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        teacher_id=seed["teacher"].id,
        title="Quiz Sheet",
        deadline=datetime.now(timezone.utc) + timedelta(days=1),
        max_marks=25.0,
    )
    db_session.add(assignment)
    db_session.flush()

    submission = AssignmentSubmission(
        assignment_id=assignment.id,
        student_id=seed["student_enrolled"].id,
        file_url="https://example.com/quiz.pdf",
        status="submitted",
    )
    db_session.add(submission)
    db_session.flush()

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    # Exceeds max marks
    res = client.put(f"/assignments/{assignment.id}/grade/{submission.id}", json={"grade": 30.0})
    assert res.status_code == 422


def test_unauthorized_student_submission(client, seed, db_session):
    """Student from a different class section cannot submit (403 Forbidden)."""
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        teacher_id=seed["teacher"].id,
        title="Grade 10-A Exclusive",
        deadline=datetime.now(timezone.utc) + timedelta(days=2),
    )
    db_session.add(assignment)
    db_session.flush()

    _override_user("student", user_id=seed["student_not_enrolled"].id, school_id=seed["school"].id)

    payload = {"file_url": "https://example.com/intruder.pdf"}
    res = client.post(f"/assignments/{assignment.id}/submit", json=payload)
    assert res.status_code == 403


def test_duplicate_submission_handling(client, seed, db_session):
    """Resubmission updates file when un-graded; fails when already graded."""
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        teacher_id=seed["teacher"].id,
        title="Biology Paper",
        deadline=datetime.now(timezone.utc) + timedelta(days=2),
        max_marks=100.0,
    )
    db_session.add(assignment)
    db_session.flush()

    _override_user("student", user_id=seed["student_enrolled"].id, school_id=seed["school"].id)

    # First submission
    res1 = client.post(
        f"/assignments/{assignment.id}/submit",
        json={"file_url": "https://example.com/v1.pdf", "file_name": "v1.pdf"},
    )
    assert res1.status_code == 200

    # Resubmission (updated file before grading)
    res2 = client.post(
        f"/assignments/{assignment.id}/submit",
        json={"file_url": "https://example.com/v2.pdf", "file_name": "v2.pdf"},
    )
    assert res2.status_code == 200
    assert res2.json()["file_name"] == "v2.pdf"

    # Teacher grades it
    sub_id = res2.json()["id"]
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)
    client.put(f"/assignments/{assignment.id}/grade/{sub_id}", json={"grade": 95.0})

    # Student attempts resubmission after grading -> 400
    _override_user("student", user_id=seed["student_enrolled"].id, school_id=seed["school"].id)
    res3 = client.post(
        f"/assignments/{assignment.id}/submit",
        json={"file_url": "https://example.com/v3.pdf"},
    )
    assert res3.status_code == 400


def test_teacher_views_submissions_queue(client, seed, db_session):
    """Teacher views submission queue containing enrolled students."""
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        teacher_id=seed["teacher"].id,
        title="History Review",
        deadline=datetime.now(timezone.utc) + timedelta(days=3),
    )
    db_session.add(assignment)
    db_session.flush()

    # One student submitted
    db_session.add(
        AssignmentSubmission(
            assignment_id=assignment.id,
            student_id=seed["student_enrolled"].id,
            file_url="https://example.com/history.pdf",
            status="submitted",
        )
    )
    db_session.flush()

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    res = client.get(f"/assignments/{assignment.id}/submissions")
    assert res.status_code == 200
    items = res.json()
    assert len(items) >= 2
    submitted_item = next(i for i in items if i["student_id"] == seed["student_enrolled"].id)
    assert submitted_item["status"] == "submitted"
