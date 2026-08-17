import uuid

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.risk import RemarkStub
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


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
    school = School(name="Remarks Test School")
    other_school = School(name="Remarks Other School")
    db_session.add_all([school, other_school])
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    parent_role = db_session.query(Role).filter(Role.name == "parent").one()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    principal_role = db_session.query(Role).filter(Role.name == "principal").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    principal_user = _make_user(db_session, principal_role, "principal", school)
    teacher = _make_user(db_session, teacher_role, "teacher", school)
    teacher.full_name = "Asha Rao"
    other_teacher = _make_user(db_session, teacher_role, "other-teacher", school)

    school_class = SchoolClass(
        name="Grade 8 - A", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=teacher.id
    )
    other_class = SchoolClass(
        name="Grade 9 - B", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=other_teacher.id
    )
    db_session.add_all([school_class, other_class])
    db_session.flush()

    student = _make_user(db_session, student_role, "student", school)
    other_student = _make_user(db_session, student_role, "other-student", school)
    foreign_student = _make_user(db_session, student_role, "foreign-student", other_school)
    db_session.add_all(
        [
            Enrollment(student_id=student.id, class_id=school_class.id, subject_id=None, is_primary=True),
            Enrollment(student_id=other_student.id, class_id=other_class.id, subject_id=None, is_primary=True),
        ]
    )

    linked_parent = _make_user(db_session, parent_role, "linked-parent", school)
    unlinked_parent = _make_user(db_session, parent_role, "unlinked-parent", school)
    db_session.add(ParentStudent(parent_id=linked_parent.id, student_id=student.id))

    db_session.add_all(
        [
            RemarkStub(student_id=student.id, teacher_id=teacher.id, remark_text="Excellent work and a great attitude!"),
            RemarkStub(student_id=student.id, teacher_id=teacher.id, remark_text="Missed three consecutive homework submissions."),
            RemarkStub(student_id=other_student.id, teacher_id=other_teacher.id, remark_text="Steady progress this term."),
        ]
    )

    db_session.commit()

    return {
        "school": school,
        "other_school": other_school,
        "admin_user": admin_user,
        "principal_user": principal_user,
        "teacher": teacher,
        "other_teacher": other_teacher,
        "student": student,
        "other_student": other_student,
        "foreign_student": foreign_student,
        "linked_parent": linked_parent,
        "unlinked_parent": unlinked_parent,
    }


# --- RBAC basics ---


def test_401_without_token(client, seed):
    resp = client.get(f"/remarks/student/{seed['student'].id}")
    assert resp.status_code == 401


def test_403_for_unrecognised_role(client, seed):
    """The final else - a role outside the five known ones is refused rather than
    falling through to an unscoped query."""
    _override_user("counselor", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['student'].id}")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not authorized to view remarks"


def test_404_for_unknown_student(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/remarks/student/-1")
    assert resp.status_code == 404


# --- admin / principal ---


def test_admin_sees_remarks_for_own_school_student(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['student'].id}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert {i["remark_text"] for i in items} == {
        "Excellent work and a great attitude!",
        "Missed three consecutive homework submissions.",
    }


def test_principal_sees_remarks_for_own_school_student(client, seed):
    _override_user("principal", user_id=seed["principal_user"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['student'].id}")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


def test_admin_404_for_other_school_student(client, seed):
    """Cross-tenant: 404 not 403, so ids from another school aren't probeable."""
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['foreign_student'].id}")
    assert resp.status_code == 404


# --- teacher ---


def test_teacher_sees_remarks_for_own_class_student(client, seed):
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['student'].id}")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


def test_teacher_403_for_student_outside_own_class(client, seed):
    _override_user("teacher", user_id=seed["teacher"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['other_student'].id}")
    assert resp.status_code == 403


# --- parent ---


def test_linked_parent_sees_remarks(client, seed):
    _override_user("parent", user_id=seed["linked_parent"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['student'].id}")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


def test_unlinked_parent_403(client, seed):
    _override_user("parent", user_id=seed["unlinked_parent"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['student'].id}")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not linked to this student"


# --- student ---


def test_student_sees_own_remarks(client, seed):
    _override_user("student", user_id=seed["student"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['student'].id}")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


def test_student_403_for_another_students_remarks(client, seed):
    _override_user("student", user_id=seed["student"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['other_student'].id}")
    assert resp.status_code == 403


# --- payload shape ---


def test_item_shape_includes_teacher_name_and_sentiment(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['student'].id}")
    item = next(i for i in resp.json()["items"] if i["remark_text"].startswith("Excellent"))
    assert item["student_id"] == seed["student"].id
    assert item["teacher_id"] == seed["teacher"].id
    assert item["teacher_name"] == "Asha Rao"
    assert item["sentiment"]["label"] == "positive"
    assert item["sentiment"]["compound"] > 0
    assert item["created_at"] is not None


def test_negative_remark_scores_negative(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get(f"/remarks/student/{seed['student'].id}")
    item = next(i for i in resp.json()["items"] if i["remark_text"].startswith("Missed"))
    assert item["sentiment"]["label"] == "negative"
    assert item["sentiment"]["compound"] < 0


def test_student_with_no_remarks_returns_empty_items(client, seed):
    _override_user("student", user_id=seed["foreign_student"].id, school_id=seed["other_school"].id)
    resp = client.get(f"/remarks/student/{seed['foreign_student'].id}")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
