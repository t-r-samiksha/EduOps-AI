"""Regressions found by the post-merge route-health sweep (docs/audit/route-health-sweep.md).

All three endpoints below returned 5xx against real Riverside data while the existing
suite passed, because the existing tests only exercised the paths that happen not to
touch the broken code. Each test here is written to hit the branch that actually failed.

Kept in its own module rather than added to Person B's test files so the two sides'
tests stay separately mergeable (see CLAUDE.md's one-module-per-domain convention).
"""

import uuid
from datetime import date, time, timedelta

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.exams import Exam
from app.models.risk import RiskFlag
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int, school_id: int | None = None):
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


def _user(db_session, role_row, prefix, school):
    u = User(
        supabase_id=uuid.uuid4(),
        email=f"{prefix}-{uuid.uuid4()}@example.com",
        full_name=prefix.capitalize(),
        role_id=role_row.id,
        school_id=school.id,
    )
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture()
def rh_seed(db_session):
    """One class with two students: `flagged` carries an OPEN RiskFlag, `healthy` does
    not. The distinction is the point - see test_analytics_for_a_flagged_student."""
    for name in ("admin", "teacher", "student", "parent"):
        if not db_session.query(Role).filter(Role.name == name).first():
            db_session.add(Role(name=name))
    db_session.flush()

    school = School(name="Route Health School")
    db_session.add(school)
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()

    teacher = _user(db_session, teacher_role, "rh_teacher", school)
    flagged = _user(db_session, student_role, "rh_flagged", school)
    healthy = _user(db_session, student_role, "rh_healthy", school)

    school_class = SchoolClass(
        name="Grade 3 - RH",
        academic_year=ACADEMIC_YEAR,
        school_id=school.id,
        class_teacher_id=teacher.id,
        grade_level=3,
    )
    db_session.add(school_class)
    db_session.flush()

    subject = Subject(name="Mathematics", school_id=school.id)
    db_session.add(subject)
    db_session.flush()

    db_session.add_all([
        Enrollment(student_id=flagged.id, class_id=school_class.id, is_primary=True),
        Enrollment(student_id=healthy.id, class_id=school_class.id, is_primary=True),
    ])

    # An OPEN flag carrying TWO reasons - `reasons` is a JSONB list, not a scalar.
    db_session.add(RiskFlag(
        student_id=flagged.id,
        risk_level="medium",
        score=0.366,
        reasons=[
            "attendance rate 59% is below the 90% threshold",
            "recent teacher remarks skew negative (avg sentiment -0.44)",
        ],
        status="open",
    ))

    # A scheduled exam, so the calendar sync actually has a row to convert.
    db_session.add(Exam(
        school_id=school.id,
        subject_id=subject.id,
        class_id=school_class.id,
        academic_year=ACADEMIC_YEAR,
        exam_type="unit_test",
        exam_date=date.today() + timedelta(days=3),
        start_time=time(9, 0),
        end_time=time(11, 0),
        total_marks=50,
    ))
    db_session.commit()

    return {
        "school": school, "class": school_class, "subject": subject,
        "teacher": teacher, "flagged": flagged, "healthy": healthy,
    }


# --- E1 -----------------------------------------------------------------------------


def test_analytics_for_a_flagged_student_returns_its_reasons(client, rh_seed):
    """REGRESSION. `analytics_service` built its payload with `f.reason`, but RiskFlag
    exposes `reasons` (a JSONB list). The comprehension sat behind `if is_at_risk`, so
    it was only ever evaluated for a student who HAS an open flag - which no existing
    test covered. Result: the screen worked for every healthy student and 500'd for
    exactly the at-risk ones it exists to surface.
    """
    flagged = rh_seed["flagged"]
    # Read as staff: this test is about the payload shape, not the parent-link gate
    # (a parent reading a child who is not theirs is covered separately below).
    _override_user("admin", user_id=rh_seed["teacher"].id, school_id=rh_seed["school"].id)

    res = client.get(f"/analytics/student/{flagged.id}")
    assert res.status_code == 200

    risk = res.json()["risk_status"]
    assert risk["is_at_risk"] is True
    assert risk["flags_count"] == 1
    # Flattened to list[str] - NOT a list of lists, and not a list of ORM objects.
    assert risk["reasons"] == [
        "attendance rate 59% is below the 90% threshold",
        "recent teacher remarks skew negative (avg sentiment -0.44)",
    ]
    assert all(isinstance(r, str) for r in risk["reasons"])


def test_analytics_for_a_healthy_student_still_returns_no_reasons(client, rh_seed):
    """The path the old tests did cover - kept so the fix can't regress it."""
    _override_user("admin", user_id=rh_seed["teacher"].id, school_id=rh_seed["school"].id)

    res = client.get(f"/analytics/student/{rh_seed['healthy'].id}")
    assert res.status_code == 200
    risk = res.json()["risk_status"]
    assert risk["is_at_risk"] is False
    assert risk["reasons"] == []


# --- E2 -----------------------------------------------------------------------------


def test_homework_calendar_does_not_raise(client, rh_seed):
    """REGRESSION. `calendar_sync_service` imported SchoolClass from app.models.school,
    where it does not live (app.models.class_), so this 500'd on every call for every
    role. An empty list is a perfectly good result here - raising is not.
    """
    student = rh_seed["flagged"]
    _override_user("student", user_id=student.id, school_id=rh_seed["school"].id)

    res = client.get(f"/calendar/homework/{student.id}")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


# --- E3 -----------------------------------------------------------------------------


def test_user_calendar_syncs_an_exam_without_raising(client, rh_seed):
    """REGRESSION, two bugs deep. The visible failure was `ex.name` (Exam has no such
    column). Fixing that exposed a second one the AttributeError had been masking:
    Exam.start_time/end_time are TIME columns while calendar_events.start_time is
    timestamptz, so the INSERT died with a DatatypeMismatch. Both are only reachable
    when the school actually has an exam row - hence the Exam in this fixture.
    """
    student = rh_seed["flagged"]
    _override_user("student", user_id=student.id, school_id=rh_seed["school"].id)

    res = client.get(f"/calendar/{student.id}")
    assert res.status_code == 200
    events = res.json()
    assert isinstance(events, list)

    exam_events = [e for e in events if e.get("event_type") == "exam"]
    assert len(exam_events) == 1, "the seeded exam should sync into the calendar"
    # Title built from subject + exam_type, since Exam has no name column.
    assert "Mathematics" in exam_events[0]["title"]
    assert "unit test" in exam_events[0]["title"]


# --- Parent record scoping ----------------------------------------------------------


@pytest.fixture()
def rh_parent(db_session, rh_seed):
    """A parent linked to `flagged` only - NOT to `healthy`."""
    from app.models.parent_student import ParentStudent

    parent_role = db_session.query(Role).filter(Role.name == "parent").one()
    parent = _user(db_session, parent_role, "rh_parent", rh_seed["school"])
    db_session.add(ParentStudent(parent_id=parent.id, student_id=rh_seed["flagged"].id))
    db_session.commit()
    return parent


@pytest.mark.parametrize(
    "path_for",
    [
        lambda sid: f"/gradebook/{sid}",
        lambda sid: f"/report_cards/{sid}",
        lambda sid: f"/analytics/student/{sid}",
        lambda sid: f"/remarks/{sid}",
        lambda sid: f"/calendar/homework/{sid}",
        lambda sid: f"/library/my-loans/{sid}",
    ],
)
def test_parent_cannot_read_a_child_who_is_not_theirs(client, rh_seed, rh_parent, path_for):
    """REGRESSION, security. These endpoints guarded with

        if user.role == "student" and user.id != student_id: 403

    which constrains STUDENTS only - a parent could read ANY student's grades, report
    cards, analytics, remarks, loans and calendar by changing the id in the URL. There
    was no parent-link check anywhere in this code.

    Verified against live data before the fix: a real parent of two children got 200 on
    a third child's gradebook.
    """
    _override_user("parent", user_id=rh_parent.id, school_id=rh_seed["school"].id)

    own = client.get(path_for(rh_seed["flagged"].id))
    assert own.status_code == 200, "a parent must still see their OWN child"

    other = client.get(path_for(rh_seed["healthy"].id))
    assert other.status_code == 403, "a parent must NOT see a child who isn't theirs"


def test_student_still_cannot_read_another_student(client, rh_seed):
    """The constraint that DID exist must survive the refactor to the shared helper."""
    _override_user("student", user_id=rh_seed["flagged"].id, school_id=rh_seed["school"].id)

    assert client.get(f"/gradebook/{rh_seed['flagged'].id}").status_code == 200
    assert client.get(f"/gradebook/{rh_seed['healthy'].id}").status_code == 403


def test_teacher_and_admin_are_not_blocked_by_the_parent_gate(client, rh_seed):
    """The helper must not over-reach: staff roles still read any student in scope."""
    for role in ("teacher", "admin", "principal"):
        _override_user(role, user_id=rh_seed["teacher"].id, school_id=rh_seed["school"].id)
        res = client.get(f"/gradebook/{rh_seed['healthy'].id}")
        assert res.status_code == 200, f"{role} should not be blocked"


# --- RBAC matrix enforcement --------------------------------------------------------


def test_teacher_bot_is_teacher_only(client, rh_seed):
    """The Teacher Assistant is a lesson-planning tool scoped to the grades the caller
    teaches. It was gated require_role("teacher","admin","principal") and routed onto
    the admin and principal dashboards, where there is no teaching scope to resolve.
    """
    _override_user("teacher", user_id=rh_seed["teacher"].id, school_id=rh_seed["school"].id)
    assert client.post("/bots/teacher/ask", json={"query": "ping"}).status_code != 403

    for role in ("admin", "principal", "parent", "student"):
        _override_user(role, user_id=rh_seed["teacher"].id, school_id=rh_seed["school"].id)
        res = client.post("/bots/teacher/ask", json={"query": "ping"})
        assert res.status_code == 403, f"{role} must not reach the teacher bot"


@pytest.mark.parametrize(
    "path,feature",
    [
        ("/classroom/my-classrooms", "classroom stream"),
        ("/library/catalog", "digital library"),
    ],
)
def test_parent_is_denied_classroom_and_library(client, rh_seed, rh_parent, path, feature):
    """RBAC matrix: parents have NO ACCESS to the classroom stream or the digital
    library - a class-wide teaching surface and a school-wide catalogue, neither of
    which is per-child information. Both were reachable because the handlers only gated
    their WRITE paths.

    Resources is deliberately NOT in this list: the matrix was amended to allow parents
    their child's course material. See docs/audit/route-health-sweep.md.
    """
    _override_user("parent", user_id=rh_parent.id, school_id=rh_seed["school"].id)
    assert client.get(path).status_code == 403

    # ...and the roles that SHOULD have it still do.
    _override_user("teacher", user_id=rh_seed["teacher"].id, school_id=rh_seed["school"].id)
    assert client.get(path).status_code == 200


def test_parent_keeps_access_to_resources(client, rh_seed, rh_parent):
    """The amendment, asserted - so nobody "restores the matrix" and breaks it."""
    _override_user("parent", user_id=rh_parent.id, school_id=rh_seed["school"].id)
    assert client.get("/resources").status_code == 200


# --- teacher scope ------------------------------------------------------------------


@pytest.fixture()
def rh_outsider(db_session, rh_seed):
    """A teacher of a DIFFERENT class, plus a student only in that class.

    Riverside cannot demonstrate this: all three of its teachers appear on the
    timetable for all four classes, so every teacher legitimately sees every student.
    The control is real, but only a synthetic fixture can prove it.
    """
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    other_teacher = _user(db_session, teacher_role, "rh_other_teacher", rh_seed["school"])
    other_student = _user(db_session, student_role, "rh_other_student", rh_seed["school"])

    other_class = SchoolClass(
        name="Grade 5 - Z",
        academic_year=ACADEMIC_YEAR,
        school_id=rh_seed["school"].id,
        class_teacher_id=other_teacher.id,
        grade_level=5,
    )
    db_session.add(other_class)
    db_session.flush()
    db_session.add(Enrollment(student_id=other_student.id, class_id=other_class.id, is_primary=True))
    db_session.commit()
    return {"teacher": other_teacher, "student": other_student, "class": other_class}


@pytest.mark.parametrize(
    "path_for",
    [
        lambda sid: f"/gradebook/{sid}",
        lambda sid: f"/report_cards/{sid}",
        lambda sid: f"/analytics/student/{sid}",
        lambda sid: f"/remarks/{sid}",
    ],
)
def test_teacher_cannot_read_a_student_they_do_not_teach(client, rh_seed, rh_outsider, path_for):
    """RBAC matrix: teachers see their TAUGHT students only. Previously unenforced on
    gradebook, report cards, analytics and remarks - any teacher could read any student
    in the school.
    """
    outsider = rh_outsider["teacher"]
    _override_user("teacher", user_id=outsider.id, school_id=rh_seed["school"].id)

    own = client.get(path_for(rh_outsider["student"].id))
    assert own.status_code == 200, "a teacher must still read their OWN student"

    other = client.get(path_for(rh_seed["flagged"].id))
    assert other.status_code == 403, "a teacher must NOT read a student they don't teach"


def test_teacher_scope_is_homeroom_union_timetable_not_homeroom_alone(db_session, rh_seed):
    """Scoping on homeroom alone would have cut Meera Iyer from 12 students to 2 on the
    real Riverside data, removing Grade 3 - B and the cross-section Top Doubts cluster.
    A teacher with NO homeroom would have gone to zero. The union is load-bearing.
    """
    from app.models.timetable import Room, TimetableSlot
    from app.services.scoping import classes_taught_by, teacher_class_ids

    # A teacher with no homeroom who only appears on the timetable.
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    visiting = _user(db_session, teacher_role, "rh_visiting", rh_seed["school"])
    room = Room(name="RH-101", capacity=30, room_type="classroom", school_id=rh_seed["school"].id)
    db_session.add(room)
    db_session.flush()
    db_session.add(TimetableSlot(
        class_id=rh_seed["class"].id,
        subject_id=rh_seed["subject"].id,
        teacher_id=visiting.id,
        room_id=room.id,
        academic_year=ACADEMIC_YEAR,
        day_of_week=0,
        period_number=1,
        start_time=time(9, 0),
        end_time=time(9, 45),
    ))
    # flush, not commit - conftest wraps each test in an outer transaction and a nested
    # commit here trips SQLAlchemy's IllegalStateChangeError.
    db_session.flush()

    assert teacher_class_ids(db_session, visiting.id) == [], "no homeroom, by construction"
    assert rh_seed["class"].id in classes_taught_by(db_session, visiting.id)


def test_parent_sees_own_childs_loans_but_not_the_catalog(client, rh_seed, rh_parent):
    """The Digital Library amendment, asserted at the boundary.

    `/library/catalog` is a school-wide staff-and-student surface and stays parent-
    denied. `/library/my-loans/{child_id}` is per-child - a parent seeing their own
    child's borrowed and overdue books is parent-portal territory - so it is gated by
    the parent LINK rather than blocked outright. Matrix amended 2026-08-18.
    """
    _override_user("parent", user_id=rh_parent.id, school_id=rh_seed["school"].id)

    assert client.get("/library/catalog").status_code == 403
    assert client.get(f"/library/my-loans/{rh_seed['flagged'].id}").status_code == 200
    assert client.get(f"/library/my-loans/{rh_seed['healthy'].id}").status_code == 403


def test_teacher_can_read_their_own_homework_calendar(client, rh_seed):
    """REGRESSION. A teacher asking for their OWN deadlines was refused with 403.

    GET /calendar/homework/{id} guarded with assert_can_view_student_record, whose teacher
    branch tests `id in students_taught_by(...)`. A teacher's own user id is not one of their
    students, so the check rejected them - and the page rendered "Could not load the academic
    calendar" for every teacher in the app. Admins slipped through only because that branch
    returns early.

    The service itself always handled staff: it branches on role and returns a teacher's
    taught-class deadlines. Only the gate was wrong.
    """
    teacher = rh_seed["teacher"]
    _override_user("teacher", user_id=teacher.id, school_id=rh_seed["school"].id)

    res = client.get(f"/calendar/homework/{teacher.id}")
    assert res.status_code == 200, res.text
    assert isinstance(res.json(), list)


def test_teacher_still_cannot_read_a_calendar_for_a_student_they_do_not_teach(
    client, rh_seed, db_session
):
    """The self-read exemption must not become "any id"."""
    from app.models.school import School as _School

    other_school = _School(name="Calendar Outsider School")
    db_session.add(other_school)
    db_session.flush()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    outsider_student = _user(db_session, student_role, "rh_outsider", other_school)
    db_session.commit()

    _override_user("teacher", user_id=rh_seed["teacher"].id, school_id=rh_seed["school"].id)
    res = client.get(f"/calendar/homework/{outsider_student.id}")
    assert res.status_code == 403


def test_student_can_read_their_own_synced_calendar(client, rh_seed):
    """GET /calendar/{user_id} carried the same self-read gap."""
    student = rh_seed["flagged"]
    _override_user("student", user_id=student.id, school_id=rh_seed["school"].id)

    res = client.get(f"/calendar/{student.id}")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
