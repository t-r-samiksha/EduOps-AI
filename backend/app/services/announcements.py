"""Announcement audience resolution and visibility.

THIS MODULE IS THE FEATURE'S CORRECTNESS. Everything else in the announcements stack is
CRUD around it: the router validates and persists, notify.py delivers. What decides
whether a Grade 3 announcement actually reaches both sections' students, their parents
and the teachers who teach them - and nobody else - is `resolve_audience`.

ANNOUNCEMENTS ARE A SOURCE, NOT A DELIVERY SYSTEM. `resolve_audience` returns user ids;
the caller hands them to services/notify.py's `dispatch_bulk` with
source_type="announcement". There is no second inbox. See models/announcement.py.

The two failure modes worth naming, because neither raises:

  1. AN AUDIENCE THAT IS TOO SMALL looks like a successful post that nobody read. A
     class-scoped row with a null class_id, or a grade lookup that missed a section,
     resolves quietly to fewer people and the author never finds out.
  2. DUPLICATES inflate the reach number the author is shown and send the same person
     two bell rows. `parent_student` has no unique constraint, so a parent linked twice
     to the same child - or with two children in one grade - would otherwise be counted
     twice. Every path here goes through a set.

THE FEED AND THE AUDIENCE ARE NOT THE SAME SET, AND THAT IS NOT A BUG. `resolve_audience`
excludes the author - nobody needs a bell row for the thing they just posted. But the
feed is a VIEW, not an inbox, so an author DOES see their own announcement in it: a
teacher who posts to Grade 3 and then cannot find it on the announcements page would
reasonably conclude the post failed. Audience drives delivery; `visible_scope_for`
drives the feed. This is the one place the two legitimately diverge.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.audit_log import write_audit_log
from app.services.notify import dispatch_bulk
from app.models.announcement import Announcement
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.timetable import TimetableSlot
from app.models.user import User

SCHOOL_SCOPE, GRADE_SCOPE, CLASS_SCOPE = "school", "grade", "class"


# --- building blocks ----------------------------------------------------------------


def _class_ids_at_grade(db: Session, school_id: int, grade_level: int) -> list[int]:
    """Every active class at this grade level IN THIS SCHOOL.

    `school_id` is load-bearing, not defensive: grade 3 exists in every school, so
    filtering on grade_level alone would cross tenants. Same reasoning as
    models/resource.py's grade_level docstring.
    """
    return [
        row.id
        for row in db.query(SchoolClass.id).filter(
            SchoolClass.school_id == school_id,
            SchoolClass.grade_level == grade_level,
            SchoolClass.is_active.is_(True),
        )
    ]


def _students_in(db: Session, class_ids: list[int]) -> set[int]:
    if not class_ids:
        return set()
    return {
        row.student_id
        for row in db.query(Enrollment.student_id).filter(Enrollment.class_id.in_(class_ids))
    }


def _parents_of(db: Session, student_ids: set[int]) -> set[int]:
    """Linked guardians. A set, because parent_student has no unique constraint and a
    parent with two children in the same grade must not be notified twice."""
    if not student_ids:
        return set()
    return {
        row.parent_id
        for row in db.query(ParentStudent.parent_id).filter(
            ParentStudent.student_id.in_(student_ids)
        )
    }


def _teachers_of(db: Session, class_ids: list[int]) -> set[int]:
    """Teachers responsible for these classes: homeroom UNION timetable-taught.

    The same union as services/scoping.py's classes_taught_by, from the other
    direction. Homeroom alone is not enough - a teacher who teaches a class without
    being its homeroom teacher still needs its announcements, and on the Riverside data
    one teacher has no homeroom at all.
    """
    if not class_ids:
        return set()
    homeroom = {
        row.class_teacher_id
        for row in db.query(SchoolClass.class_teacher_id).filter(SchoolClass.id.in_(class_ids))
        if row.class_teacher_id is not None
    }
    timetabled = {
        row.teacher_id
        for row in db.query(TimetableSlot.teacher_id)
        .filter(TimetableSlot.class_id.in_(class_ids))
        .distinct()
        if row.teacher_id is not None
    }
    return homeroom | timetabled


def _all_active_users(db: Session, school_id: int) -> set[int]:
    return {
        row.id
        for row in db.query(User.id).filter(
            User.school_id == school_id, User.is_active.is_(True)
        )
    }


# --- the audience -------------------------------------------------------------------


def resolve_audience(db: Session, announcement: Announcement) -> list[int]:
    """Who this announcement is for, excluding its author.

    - class  -> students enrolled in it + their linked parents + its teachers
    - grade  -> the same, unioned across every active class at that grade in the school
    - school -> every active user in the school

    Returns a sorted list so callers, tests and the reach number the author is shown are
    all deterministic. The author is excluded: dispatching to yourself puts a bell row
    on the person who just clicked Post.
    """
    school_id = announcement.school_id

    if announcement.scope_type == SCHOOL_SCOPE:
        audience = _all_active_users(db, school_id)

    elif announcement.scope_type == GRADE_SCOPE:
        class_ids = _class_ids_at_grade(db, school_id, announcement.scope_grade_level)
        students = _students_in(db, class_ids)
        audience = students | _parents_of(db, students) | _teachers_of(db, class_ids)

    elif announcement.scope_type == CLASS_SCOPE:
        class_ids = [announcement.scope_class_id]
        students = _students_in(db, class_ids)
        audience = students | _parents_of(db, students) | _teachers_of(db, class_ids)

    else:  # pragma: no cover - the CHECK constraint makes this unreachable
        raise ValueError(f"unknown scope_type {announcement.scope_type!r}")

    audience.discard(announcement.author_id)
    return sorted(audience)


# --- visibility (the read side) -----------------------------------------------------


def visible_scope_for(db: Session, user) -> dict:
    """The scopes this caller can SEE, used to filter their feed.

    Deliberately derived from the caller's own identity - there is no user_id parameter
    anywhere on the feed, so no client can widen what it asks for.

    Returns {"all": bool, "grades": set[int], "class_ids": set[int], "child_ids": set[int]}.
    `all` short-circuits for admin and principal, who see everything in their school.
    """
    if user.role in ("admin", "principal"):
        return {"all": True, "grades": set(), "class_ids": set(), "child_ids": set()}

    class_ids: set[int] = set()
    child_ids: set[int] = set()

    if user.role == "student":
        class_ids = {
            row.class_id
            for row in db.query(Enrollment.class_id).filter(Enrollment.student_id == user.id)
        }

    elif user.role == "parent":
        child_ids = {
            row.student_id
            for row in db.query(ParentStudent.student_id).filter(
                ParentStudent.parent_id == user.id
            )
        }
        if child_ids:
            class_ids = {
                row.class_id
                for row in db.query(Enrollment.class_id).filter(
                    Enrollment.student_id.in_(child_ids)
                )
            }

    elif user.role == "teacher":
        homeroom = {
            row.id
            for row in db.query(SchoolClass.id).filter(SchoolClass.class_teacher_id == user.id)
        }
        timetabled = {
            row.class_id
            for row in db.query(TimetableSlot.class_id)
            .filter(TimetableSlot.teacher_id == user.id)
            .distinct()
        }
        class_ids = homeroom | timetabled

    grades = {
        row.grade_level
        for row in db.query(SchoolClass.grade_level).filter(SchoolClass.id.in_(class_ids or [-1]))
        if row.grade_level is not None
    }
    return {"all": False, "grades": grades, "class_ids": class_ids, "child_ids": child_ids}


def can_see(announcement: Announcement, scope: dict) -> bool:
    """Whether one announcement falls inside a caller's visible scope.

    Everyone in a school sees its school-wide announcements - that is what school-wide
    means, and it is why students and parents need no special case here.
    """
    if scope["all"]:
        return True
    if announcement.scope_type == SCHOOL_SCOPE:
        return True
    if announcement.scope_type == GRADE_SCOPE:
        return announcement.scope_grade_level in scope["grades"]
    return announcement.scope_class_id in scope["class_ids"]


def related_children(db: Session, announcement: Announcement, scope: dict) -> list[dict]:
    """For a PARENT only: which of their own children this item relates to.

    A parent with two children in Grade 3 gets ONE item naming both, not two copies -
    the deduplication happens here rather than by emitting duplicate rows. Empty for a
    school-wide item (it relates to everyone, so naming a child would be noise) and
    empty for every non-parent role.
    """
    if not scope["child_ids"] or announcement.scope_type == SCHOOL_SCOPE:
        return []

    if announcement.scope_type == CLASS_SCOPE:
        target_class_ids = [announcement.scope_class_id]
    else:
        target_class_ids = _class_ids_at_grade(
            db, announcement.school_id, announcement.scope_grade_level
        )
    if not target_class_ids:
        return []

    matched = {
        row.student_id
        for row in db.query(Enrollment.student_id).filter(
            Enrollment.student_id.in_(scope["child_ids"]),
            Enrollment.class_id.in_(target_class_ids),
        )
    }
    if not matched:
        return []
    return [
        {"id": u.id, "name": u.full_name}
        for u in db.query(User).filter(User.id.in_(matched)).order_by(User.id)
    ]


def scope_label(db: Session, announcement: Announcement) -> str:
    """`School` / `Grade 3` / `Grade 3 - A`, resolved server-side so the UI badge needs
    no second lookup and cannot render a different label from the one enforced."""
    if announcement.scope_type == SCHOOL_SCOPE:
        return "School"
    if announcement.scope_type == GRADE_SCOPE:
        cls = (
            db.query(SchoolClass)
            .filter(
                SchoolClass.school_id == announcement.school_id,
                SchoolClass.grade_level == announcement.scope_grade_level,
                SchoolClass.grade_label.isnot(None),
            )
            .first()
        )
        if cls is not None and cls.grade_label:
            return cls.grade_label  # "LKG"/"UKG"/"Nursery" - see SchoolClass.grade_label
        return f"Grade {announcement.scope_grade_level}"
    cls = db.query(SchoolClass).filter(SchoolClass.id == announcement.scope_class_id).one_or_none()
    return cls.name if cls is not None else f"Class {announcement.scope_class_id}"


def publish_announcement(
    db: Session,
    *,
    author_id: int,
    school_id: int,
    scope_type: str,
    title: str,
    body: str,
    scope_grade_level: int | None = None,
    scope_class_id: int | None = None,
    category: str = "general",
    priority: str = "normal",
    audit_action: str = "create_announcement",
    audience_override: list[int] | None = None,
) -> tuple[Announcement, list[int]]:
    """Creates an Announcement row, resolves its audience, and dispatches it.

    THE ONLY WAY AN ANNOUNCEMENT SHOULD COME INTO EXISTENCE. Extracted so the classroom
    stream can reuse it: a stream post of type "announcement" previously dispatched
    notifications directly with source_type="announcement" and source_id=<StreamPost.id>,
    which put stream-post ids and announcement ids in ONE id namespace. A notification's
    (source_type, source_id) is how the client resolves what to open, so post 41 and
    announcement 41 were indistinguishable - one of them would deep-link to the other's
    content. Routing through here means source_id is always an Announcement.id, and the
    post also becomes visible in the announcement feed instead of only in the stream.

    Does NOT commit - dispatch runs inside the caller's transaction, per notify.py's
    convention, so the announcement, its notifications and its audit row commit together
    or not at all. The caller commits.
    """
    ann = Announcement(
        school_id=school_id,
        author_id=author_id,
        scope_type=scope_type,
        scope_grade_level=scope_grade_level,
        scope_class_id=scope_class_id,
        title=title.strip(),
        body=body.strip(),
        category=category,
        priority=priority,
    )
    db.add(ann)
    db.flush()  # need ann.id for source_id and for the audit row

    # audience_override exists for ONE case: an elective classroom. resolve_audience
    # expands a class scope to every student enrolled in the class, but an elective
    # classroom's announcement must reach only the students taking that subject - the N-2
    # fix in classroom.py::_get_enrolled_student_ids. Passing the narrowed list keeps
    # delivery correct; scope_class_id still records which class it belongs to.
    audience = resolve_audience(db, ann) if audience_override is None else sorted(
        set(audience_override) - {author_id}
    )
    dispatch_bulk(
        db,
        user_ids=audience,
        source_type="announcement",
        title=ann.title,
        body=ann.body[:280],
        priority=ann.priority,  # urgent arrives urgent
        source_id=ann.id,
    )
    write_audit_log(
        db,
        actor_id=author_id,
        action=audit_action,
        entity_type="announcements",
        entity_id=ann.id,
        detail={
            "scope_type": ann.scope_type,
            "recipients": len(audience),
            "priority": ann.priority,
            "narrowed_audience": audience_override is not None,
        },
    )
    return ann, audience
