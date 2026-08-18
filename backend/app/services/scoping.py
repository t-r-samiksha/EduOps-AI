"""Shared role-scoping helpers for new routers.

WHY THIS EXISTS ALONGSIDE THE PER-ROUTER COPIES - read before "cleaning up"
----------------------------------------------------------------------------
Four existing routers (attendance.py, fees.py, risk.py, timetable.py) each carry
their own private `_teacher_class_ids` / `_students_in_classes` / inline
parent-link check. That duplication is DELIBERATE, not an accident: see the
comment at routers/fees.py:22-24, which records it as following this codebase's
"keep Person A/B/C's code in separate files so merges stay clean" convention.

This module is for NEW code only. It was added because the notification/remarks
work needed the same three checks and copying them a fifth time is worse than
sharing them. It intentionally does NOT refactor the four existing routers to
call it - reversing a documented convention across four of Person A's tested
routers is a separate, reviewable change, not a drive-by edit inside a feature
branch. So both forms exist on purpose, and the older routers keeping their own
copies is not a bug to fix here.

The semantics below are copied to match routers/risk.py:173-183 and
routers/fees.py:274-294 exactly - same status codes, same message strings - so a
caller migrated to these helpers later behaves identically to what it replaced.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent


def assert_parent_linked(db: Session, parent_id: int, student_id: int | None) -> int:
    """Verify a parent caller named one of their own linked children.

    Returns the validated `student_id` so call sites can use it directly as the
    filter value. Raises `400` when a parent didn't name a child at all (the
    endpoint can't guess which one), `403` when the named child isn't theirs.
    """
    if student_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "student_id is required for parent role")
    link = (
        db.query(ParentStudent)
        .filter(ParentStudent.parent_id == parent_id, ParentStudent.student_id == student_id)
        .one_or_none()
    )
    if link is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not linked to this student")
    return student_id


def assert_can_view_student_record(
    db: Session, user, student_id: int, *, what: str = "record"
) -> None:
    """Ownership gate for any per-student record - gradebook, report card, analytics,
    remarks, library loans, homework calendar.

    - student: may only read their own.
    - parent: must be LINKED to that child (assert_parent_linked).
    - teacher: scoped to the students they teach (see below).
    - admin / principal: allowed through.

    WHY THIS EXISTS. Every one of those endpoints originally guarded with:

        if user.role == "student" and user.id != student_id: 403

    which constrains STUDENTS ONLY. Nothing constrained parents, and no parent-link
    check existed anywhere in that code - so any authenticated parent could read any
    student's grades, report cards, analytics and remarks by changing the id in the
    URL. Verified against live data before this was written: `guardian.kumar`, a
    parent of two children, got 200 on a third child's gradebook.

    - teacher: may only read a student enrolled in a class they are responsible for
      (homeroom UNION timetable-taught - see classes_taught_by).
    - admin / principal: unrestricted within their school.
    """
    if user.role == "student":
        if user.id != student_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Cannot view another student's {what}"
            )
        return
    if user.role == "parent":
        assert_parent_linked(db, user.id, student_id)
        return
    if user.role == "teacher":
        if student_id not in students_taught_by(db, user.id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Not authorized to view this student's {what}"
            )



def classes_taught_by(db: Session, teacher_id: int) -> list[int]:
    """Classes a teacher is responsible for: homeroom UNION anything they teach on the
    timetable.

    teacher_class_ids() alone is HOMEROOM ONLY and is not a substitute here - on the
    Riverside data, scoping Meera Iyer by homeroom would have cut her from 12 students
    to 2 and removed Grade 3 - B entirely, taking the cross-section Top Doubts cluster
    with it. Kavya Reddy has no homeroom at all and would have gone to zero.
    """
    from app.models.timetable import TimetableSlot

    homeroom = set(teacher_class_ids(db, teacher_id))
    taught = {
        row.class_id
        for row in db.query(TimetableSlot.class_id)
        .filter(TimetableSlot.teacher_id == teacher_id)
        .distinct()
    }
    return sorted(homeroom | taught)


def students_taught_by(db: Session, teacher_id: int) -> set[int]:
    """Students enrolled in any class this teacher is responsible for."""
    return students_in_classes(db, classes_taught_by(db, teacher_id))


def deny_parent(user, *, feature: str) -> None:
    """403 for the parent role.

    The RBAC matrix gives parents NO ACCESS to the classroom stream and the digital
    library: those are a class-wide teaching surface and a school-wide catalogue, not
    per-child information. Both were reachable by any authenticated parent because the
    handlers only ever gated `require_role` on their WRITE paths.

    Amendment on record: Resources is deliberately NOT covered here. The matrix
    originally listed it as parent-No-Access, but a parent seeing their child's course
    material is reasonable and it was already built, so the matrix was amended to allow
    it rather than the code restricted. See docs/audit/route-health-sweep.md.
    """
    if user.role == "parent":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Parents do not have access to {feature}"
        )


def teacher_class_ids(db: Session, teacher_id: int) -> list[int]:
    """Classes where this teacher is the homeroom/class teacher.

    Homeroom ownership only (`SchoolClass.class_teacher_id`) - a teacher who
    merely teaches a subject to a class is not covered, matching the existing
    routers' definition of "your class".
    """
    return [c.id for c in db.query(SchoolClass).filter(SchoolClass.class_teacher_id == teacher_id).all()]


def students_in_classes(db: Session, class_ids: list[int]) -> set[int]:
    """Students primarily enrolled in any of `class_ids`.

    Empty input returns an empty set without querying. Callers filtering with
    `.in_()` should guard the empty case (`... .in_(result or [-1])`) the way the
    existing routers do, since `IN ()` matches nothing but is invalid SQL in
    some dialects.
    """
    if not class_ids:
        return set()
    return {
        row.student_id
        for row in db.query(Enrollment.student_id).filter(
            Enrollment.class_id.in_(class_ids), Enrollment.is_primary.is_(True)
        )
    }
