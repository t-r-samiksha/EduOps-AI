import uuid

import pytest
from fastapi import HTTPException

from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.scoping import assert_parent_linked, students_in_classes, teacher_class_ids

ACADEMIC_YEAR = "2026-27"


def _make_user(db_session, role_row, prefix, school):
    email = f"{prefix}-{uuid.uuid4()}@example.com"
    user = User(supabase_id=uuid.uuid4(), email=email, full_name=prefix, role_id=role_row.id, school_id=school.id)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def seed(db_session):
    school = School(name="Scoping Test School")
    db_session.add(school)
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    parent_role = db_session.query(Role).filter(Role.name == "parent").one()

    teacher = _make_user(db_session, teacher_role, "teacher", school)
    other_teacher = _make_user(db_session, teacher_role, "other-teacher", school)
    teacherless = _make_user(db_session, teacher_role, "no-class-teacher", school)

    class_a = SchoolClass(name="Grade 8 - A", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=teacher.id)
    class_b = SchoolClass(name="Grade 9 - B", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=teacher.id)
    other_class = SchoolClass(
        name="Grade 10 - C", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=other_teacher.id
    )
    db_session.add_all([class_a, class_b, other_class])
    db_session.flush()

    student_a = _make_user(db_session, student_role, "student-a", school)
    student_b = _make_user(db_session, student_role, "student-b", school)
    student_other = _make_user(db_session, student_role, "student-other", school)
    secondary = _make_user(db_session, student_role, "student-secondary", school)

    db_session.add_all(
        [
            Enrollment(student_id=student_a.id, class_id=class_a.id, subject_id=None, is_primary=True),
            Enrollment(student_id=student_b.id, class_id=class_b.id, subject_id=None, is_primary=True),
            Enrollment(student_id=student_other.id, class_id=other_class.id, subject_id=None, is_primary=True),
            # Non-primary enrollment: must NOT count as "in" class_a
            Enrollment(student_id=secondary.id, class_id=class_a.id, subject_id=None, is_primary=False),
        ]
    )

    linked_parent = _make_user(db_session, parent_role, "linked-parent", school)
    unlinked_parent = _make_user(db_session, parent_role, "unlinked-parent", school)
    db_session.add(ParentStudent(parent_id=linked_parent.id, student_id=student_a.id))

    db_session.commit()

    return {
        "teacher": teacher,
        "other_teacher": other_teacher,
        "teacherless": teacherless,
        "class_a": class_a,
        "class_b": class_b,
        "other_class": other_class,
        "student_a": student_a,
        "student_b": student_b,
        "student_other": student_other,
        "secondary": secondary,
        "linked_parent": linked_parent,
        "unlinked_parent": unlinked_parent,
    }


# --- assert_parent_linked ---


def test_assert_parent_linked_returns_student_id_when_linked(db_session, seed):
    result = assert_parent_linked(db_session, seed["linked_parent"].id, seed["student_a"].id)
    assert result == seed["student_a"].id


def test_assert_parent_linked_400_when_student_id_missing(db_session, seed):
    with pytest.raises(HTTPException) as exc:
        assert_parent_linked(db_session, seed["linked_parent"].id, None)
    assert exc.value.status_code == 400
    assert exc.value.detail == "student_id is required for parent role"


def test_assert_parent_linked_403_when_not_linked(db_session, seed):
    with pytest.raises(HTTPException) as exc:
        assert_parent_linked(db_session, seed["unlinked_parent"].id, seed["student_a"].id)
    assert exc.value.status_code == 403
    assert exc.value.detail == "Not linked to this student"


def test_assert_parent_linked_403_for_other_parents_child(db_session, seed):
    """A parent with links, naming a real student who just isn't theirs."""
    with pytest.raises(HTTPException) as exc:
        assert_parent_linked(db_session, seed["linked_parent"].id, seed["student_other"].id)
    assert exc.value.status_code == 403


def test_assert_parent_linked_400_takes_precedence_over_403(db_session, seed):
    """An unlinked parent passing None still gets 400, not 403 - the missing-arg
    check runs first, exactly as in risk.py."""
    with pytest.raises(HTTPException) as exc:
        assert_parent_linked(db_session, seed["unlinked_parent"].id, None)
    assert exc.value.status_code == 400


# --- teacher_class_ids ---


def test_teacher_class_ids_returns_owned_classes(db_session, seed):
    result = teacher_class_ids(db_session, seed["teacher"].id)
    assert sorted(result) == sorted([seed["class_a"].id, seed["class_b"].id])


def test_teacher_class_ids_excludes_other_teachers_class(db_session, seed):
    assert seed["other_class"].id not in teacher_class_ids(db_session, seed["teacher"].id)


def test_teacher_class_ids_empty_for_teacher_without_classes(db_session, seed):
    assert teacher_class_ids(db_session, seed["teacherless"].id) == []


def test_teacher_class_ids_empty_for_unknown_teacher(db_session, seed):
    assert teacher_class_ids(db_session, -1) == []


# --- students_in_classes ---


def test_students_in_classes_single_class(db_session, seed):
    assert students_in_classes(db_session, [seed["class_a"].id]) == {seed["student_a"].id}


def test_students_in_classes_multiple_classes_unions(db_session, seed):
    result = students_in_classes(db_session, [seed["class_a"].id, seed["class_b"].id])
    assert result == {seed["student_a"].id, seed["student_b"].id}


def test_students_in_classes_excludes_non_primary_enrollment(db_session, seed):
    """secondary is enrolled in class_a with is_primary=False and must not appear."""
    assert seed["secondary"].id not in students_in_classes(db_session, [seed["class_a"].id])


def test_students_in_classes_empty_input_returns_empty_set(db_session, seed):
    assert students_in_classes(db_session, []) == set()


def test_students_in_classes_unknown_class_returns_empty_set(db_session, seed):
    assert students_in_classes(db_session, [-1]) == set()
