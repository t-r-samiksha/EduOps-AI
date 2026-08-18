import uuid
import pytest
from io import BytesIO

from app.main import app
from app.models.class_ import SchoolClass
from app.models.classroom import Classroom, PostAttachment, StreamPost
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

    school = School(name="Classroom Test School")
    other_school = School(name="Other School")
    db_session.add_all([school, other_school])
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    teacher = _make_user(db_session, teacher_role, "teacher1", school)
    other_teacher = _make_user(db_session, teacher_role, "teacher2", school)

    student_enrolled = _make_user(db_session, student_role, "student_enrolled", school)
    student_not_enrolled = _make_user(db_session, student_role, "student_not_enrolled", school)

    school_class = SchoolClass(
        name="Grade 8 - A",
        academic_year=ACADEMIC_YEAR,
        school_id=school.id,
        class_teacher_id=teacher.id,
        grade_level=8,
    )
    other_class = SchoolClass(
        name="Grade 9 - B",
        academic_year=ACADEMIC_YEAR,
        school_id=school.id,
        grade_level=9,
    )
    db_session.add_all([school_class, other_class])
    db_session.flush()

    math_subj = Subject(name="Mathematics", school_id=school.id)
    science_subj = Subject(name="Science", school_id=school.id)
    db_session.add_all([math_subj, science_subj])
    db_session.flush()

    # Enroll student in school_class
    enrollment = Enrollment(
        student_id=student_enrolled.id,
        class_id=school_class.id,
        is_primary=True,
    )
    # Enroll other student in other_class only
    other_enrollment = Enrollment(
        student_id=student_not_enrolled.id,
        class_id=other_class.id,
        is_primary=True,
    )
    db_session.add_all([enrollment, other_enrollment])
    db_session.flush()

    # Create classroom
    classroom = Classroom(
        school_id=school.id,
        class_id=school_class.id,
        class_name=school_class.name,
        subject_id=math_subj.id,
        teacher_id=teacher.id,
    )
    db_session.add(classroom)
    db_session.flush()

    return {
        "school": school,
        "other_school": other_school,
        "admin": admin_user,
        "teacher": teacher,
        "other_teacher": other_teacher,
        "student_enrolled": student_enrolled,
        "student_not_enrolled": student_not_enrolled,
        "class": school_class,
        "subject": math_subj,
        "classroom": classroom,
    }


def test_teacher_creates_post(client, seed):
    """Authorized teacher creates note, material, and announcement."""
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    payload = {
        "post_type": "note",
        "title": "Welcome to Math Class",
        "content": "Please review chapter 1 before Friday.",
        "attachments": [
            {
                "file_name": "chapter1.pdf",
                "file_url": "https://example.com/chapter1.pdf",
                "file_type": "application/pdf",
                "file_size": 1048576,
            }
        ],
    }

    res = client.post(f"/classroom/{seed['classroom'].id}/post", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Welcome to Math Class"
    assert data["post_type"] == "note"
    assert len(data["attachments"]) == 1
    assert data["attachments"][0]["file_name"] == "chapter1.pdf"
    assert data["author"]["id"] == seed["teacher"].id


def test_unauthorized_user_cannot_create_post(client, seed):
    """Students and unassigned teachers cannot create posts in the classroom."""
    # Student attempt
    _override_user("student", user_id=seed["student_enrolled"].id, school_id=seed["school"].id)
    payload = {
        "post_type": "note",
        "title": "Unauthorized Post",
        "content": "This should fail.",
    }
    res = client.post(f"/classroom/{seed['classroom'].id}/post", json=payload)
    assert res.status_code == 403

    # Other teacher attempt
    _override_user("teacher", user_id=seed["other_teacher"].id, school_id=seed["school"].id)
    res = client.post(f"/classroom/{seed['classroom'].id}/post", json=payload)
    assert res.status_code == 403


def test_enrolled_student_can_view_stream(client, seed, db_session):
    """Enrolled student can view chronological stream posts."""
    # Create two posts
    post1 = StreamPost(
        classroom_id=seed["classroom"].id,
        author_id=seed["teacher"].id,
        post_type="material",
        title="Post 1",
        content="First post content",
    )
    post2 = StreamPost(
        classroom_id=seed["classroom"].id,
        author_id=seed["teacher"].id,
        post_type="announcement",
        title="Post 2 (Newer)",
        content="Second post content",
    )
    db_session.add_all([post1, post2])
    db_session.flush()

    _override_user("student", user_id=seed["student_enrolled"].id, school_id=seed["school"].id)

    res = client.get(f"/classroom/{seed['classroom'].id}/stream")
    assert res.status_code == 200
    data = res.json()
    assert "classroom" in data
    assert data["classroom"]["id"] == seed["classroom"].id
    assert len(data["items"]) >= 2
    # Check newest first order
    assert data["items"][0]["title"] == "Post 2 (Newer)"
    assert data["items"][1]["title"] == "Post 1"


def test_non_enrolled_student_cannot_view_stream(client, seed):
    """Non-enrolled student receives 403 Forbidden."""
    _override_user("student", user_id=seed["student_not_enrolled"].id, school_id=seed["school"].id)

    res = client.get(f"/classroom/{seed['classroom'].id}/stream")
    assert res.status_code == 403


def test_teacher_deletes_post(client, seed, db_session):
    """Author teacher can delete their post, which cascades to attachments."""
    post = StreamPost(
        classroom_id=seed["classroom"].id,
        author_id=seed["teacher"].id,
        post_type="note",
        title="To Delete",
        content="Will be deleted.",
    )
    db_session.add(post)
    db_session.flush()

    attachment = PostAttachment(
        post_id=post.id,
        file_name="temp.txt",
        file_url="https://example.com/temp.txt",
        file_type="text/plain",
        file_size=120,
    )
    db_session.add(attachment)
    db_session.flush()

    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    res = client.delete(f"/classroom/{seed['classroom'].id}/post/{post.id}")
    assert res.status_code == 204

    # Verify deleted
    deleted_post = db_session.query(StreamPost).filter(StreamPost.id == post.id).first()
    assert deleted_post is None
    deleted_att = db_session.query(PostAttachment).filter(PostAttachment.post_id == post.id).first()
    assert deleted_att is None


def test_student_cannot_delete_post(client, seed, db_session):
    """Student cannot delete posts."""
    post = StreamPost(
        classroom_id=seed["classroom"].id,
        author_id=seed["teacher"].id,
        post_type="note",
        title="Teacher Note",
        content="Content",
    )
    db_session.add(post)
    db_session.flush()

    _override_user("student", user_id=seed["student_enrolled"].id, school_id=seed["school"].id)

    res = client.delete(f"/classroom/{seed['classroom'].id}/post/{post.id}")
    assert res.status_code == 403


def test_attachment_handling(client, seed):
    """File upload returns attachment details."""
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    file_content = b"Sample syllabus and study guide content"
    files = {"file": ("syllabus.pdf", BytesIO(file_content), "application/pdf")}

    res = client.post(f"/classroom/{seed['classroom'].id}/upload", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["file_name"] == "syllabus.pdf"
    assert data["file_type"] == "application/pdf"
    assert data["file_size"] == len(file_content)
    assert "file_url" in data


def test_announcement_triggers_notification(client, seed, db_session):
    """Announcement post automatically triggers in-app notification for enrolled students."""
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)

    payload = {
        "post_type": "announcement",
        "title": "Important Exam Announcement",
        "content": "Midterm test scheduled for next Monday.",
    }

    res = client.post(f"/classroom/{seed['classroom'].id}/post", json=payload)
    assert res.status_code == 201

    # Check notification table
    notif = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == seed["student_enrolled"].id,
            Notification.source_type == "announcement",
        )
        .first()
    )
    assert notif is not None
    assert "Important Exam Announcement" in notif.title
