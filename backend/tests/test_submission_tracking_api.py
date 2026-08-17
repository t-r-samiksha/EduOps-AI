import uuid
import pytest
from datetime import datetime, timezone, timedelta

from app.main import app
from app.models.assignment import Assignment, AssignmentSubmission
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.notification import Notification
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.user import User
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

    school = School(name="Tracker Test School")
    db_session.add(school)
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()

    teacher = _make_user(db_session, teacher_role, "tracker_teacher", school)
    other_teacher = _make_user(db_session, teacher_role, "tracker_other_teacher", school)

    student1 = _make_user(db_session, student_role, "student_ontime", school)
    student2 = _make_user(db_session, student_role, "student_late", school)
    student3 = _make_user(db_session, student_role, "student_missing", school)
    student_other = _make_user(db_session, student_role, "student_other_class", school)

    school_class = SchoolClass(
        name="Grade 11 - A",
        academic_year=ACADEMIC_YEAR,
        school_id=school.id,
        class_teacher_id=teacher.id,
        grade_level=11,
    )
    other_class = SchoolClass(
        name="Grade 11 - B",
        academic_year=ACADEMIC_YEAR,
        school_id=school.id,
        class_teacher_id=other_teacher.id,
        grade_level=11,
    )
    db_session.add_all([school_class, other_class])
    db_session.flush()

    subj = Subject(name="Chemistry", school_id=school.id)
    db_session.add(subj)
    db_session.flush()

    # Enrollments
    db_session.add_all([
        Enrollment(student_id=student1.id, class_id=school_class.id, is_primary=True),
        Enrollment(student_id=student2.id, class_id=school_class.id, is_primary=True),
        Enrollment(student_id=student3.id, class_id=school_class.id, is_primary=True),
        Enrollment(student_id=student_other.id, class_id=other_class.id, is_primary=True),
    ])
    db_session.flush()

    return {
        "school": school,
        "teacher": teacher,
        "other_teacher": other_teacher,
        "student1": student1,
        "student2": student2,
        "student3": student3,
        "student_other": student_other,
        "class": school_class,
        "other_class": other_class,
        "subject": subj,
    }


def test_get_submissions_authorized_teacher(client, seed, db_session):
    """Authorized teacher views all enrolled students with accurate submission details."""
    past_deadline = datetime.now(timezone.utc) - timedelta(hours=2)
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        subject_id=seed["subject"].id,
        teacher_id=seed["teacher"].id,
        title="Organic Chemistry Lab",
        deadline=past_deadline,
        max_marks=50.0,
    )
    db_session.add(assignment)
    db_session.flush()

    # student1 submitted on time
    db_session.add(
        AssignmentSubmission(
            assignment_id=assignment.id,
            student_id=seed["student1"].id,
            file_url="https://example.com/chem1.pdf",
            file_name="chem1.pdf",
            status="submitted",
            submitted_at=past_deadline - timedelta(hours=1),
        )
    )
    # student2 submitted late
    db_session.add(
        AssignmentSubmission(
            assignment_id=assignment.id,
            student_id=seed["student2"].id,
            file_url="https://example.com/chem2.pdf",
            file_name="chem2.pdf",
            status="late",
            submitted_at=past_deadline + timedelta(hours=1),
        )
    )
    # student3 has not submitted (deadline passed -> missing)
    db_session.flush()

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    res = client.get(f"/assignments/{assignment.id}/submissions")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 3

    s1 = next(i for i in items if i["student_id"] == seed["student1"].id)
    assert s1["status"] == "submitted"
    assert s1["submission_id"] is not None
    assert s1["file_name"] == "chem1.pdf"

    s2 = next(i for i in items if i["student_id"] == seed["student2"].id)
    assert s2["status"] == "late"

    s3 = next(i for i in items if i["student_id"] == seed["student3"].id)
    assert s3["status"] == "missing"
    assert s3["file_url"] is None


def test_get_submissions_unauthorized_teacher(client, seed, db_session):
    """Teacher not assigned to the class gets 403 Forbidden."""
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        teacher_id=seed["teacher"].id,
        title="Restricted Assignment",
        deadline=datetime.now(timezone.utc) + timedelta(days=2),
    )
    db_session.add(assignment)
    db_session.flush()

    _override_user("teacher", user_id=seed["other_teacher"].id, school_id=seed["school"].id)

    res = client.get(f"/assignments/{assignment.id}/submissions")
    assert res.status_code == 403


def test_get_submissions_student_forbidden(client, seed, db_session):
    """Student caller cannot access submissions tracker endpoint."""
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        teacher_id=seed["teacher"].id,
        title="Student Forbidden Test",
        deadline=datetime.now(timezone.utc) + timedelta(days=2),
    )
    db_session.add(assignment)
    db_session.flush()

    _override_user("student", user_id=seed["student1"].id, school_id=seed["school"].id)

    res = client.get(f"/assignments/{assignment.id}/submissions")
    assert res.status_code == 403


def test_teacher_nudges_missing_student(client, seed, db_session):
    """Teacher nudges a missing student and verifies Person C notification dispatch."""
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        teacher_id=seed["teacher"].id,
        title="Electromagnetism Problem Set",
        deadline=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add(assignment)
    db_session.flush()

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    res = client.post(f"/assignments/{assignment.id}/nudge/{seed['student3'].id}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "nudged"

    # Verify notification in DB for student3
    notif = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == seed["student3"].id,
            Notification.source_type == "assignment_nudge",
        )
        .first()
    )
    assert notif is not None
    assert "Electromagnetism" in notif.title


def test_teacher_bulk_nudge_all_missing(client, seed, db_session):
    """Teacher sends bulk nudge to all missing/unsubmitted students."""
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        teacher_id=seed["teacher"].id,
        title="Genetics Homework",
        deadline=datetime.now(timezone.utc) + timedelta(days=2),
    )
    db_session.add(assignment)
    db_session.flush()

    # student1 already submitted
    db_session.add(
        AssignmentSubmission(
            assignment_id=assignment.id,
            student_id=seed["student1"].id,
            file_url="https://example.com/gen.pdf",
            status="submitted",
        )
    )
    db_session.flush()

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    res = client.post(f"/assignments/{assignment.id}/nudge-missing")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "bulk_nudged"
    assert data["nudged_count"] == 2  # student2 and student3

    # Check notification sent to student2
    notif = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == seed["student2"].id,
            Notification.source_type == "assignment_nudge",
        )
        .first()
    )
    assert notif is not None


def test_unauthorized_teacher_cannot_nudge(client, seed, db_session):
    """Teacher from another class cannot nudge students in this class."""
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        teacher_id=seed["teacher"].id,
        title="Unauthorized Nudge Test",
        deadline=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add(assignment)
    db_session.flush()

    _override_user("teacher", user_id=seed["other_teacher"].id, school_id=seed["school"].id)

    res = client.post(f"/assignments/{assignment.id}/nudge/{seed['student3'].id}")
    assert res.status_code == 403


def test_nudge_non_enrolled_student_fails(client, seed, db_session):
    """Nudging a student not enrolled in the assignment's class returns 404."""
    assignment = Assignment(
        school_id=seed["school"].id,
        class_id=seed["class"].id,
        teacher_id=seed["teacher"].id,
        title="Class Specific Task",
        deadline=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add(assignment)
    db_session.flush()

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    res = client.post(f"/assignments/{assignment.id}/nudge/{seed['student_other'].id}")
    assert res.status_code == 404
