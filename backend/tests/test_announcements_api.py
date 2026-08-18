"""Announcements: the permission matrix, audience resolution, and feed scoping.

The matrix is enforced server-side and every cell has a test. The UI hides options a
caller may not use, but that is a courtesy - these are the checks that count.

Audience resolution is the feature's correctness (see services/announcements.py), so it
is tested directly as well as through the endpoints: an audience that is too small looks
exactly like a successful post nobody read, and nothing raises.
"""

import uuid
from datetime import time

import pytest

from app.main import app
from app.models.announcement import Announcement
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.notification import Notification
from app.models.parent_student import ParentStudent
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from app.services.announcements import resolve_audience
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int, school_id: int | None = None):
    def _fake_user():
        return CurrentUser(
            id=user_id, sub=str(uuid.uuid4()), email=f"{role}-{user_id}@example.com",
            role=role, school_id=school_id,
        )

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _user(db, role_row, prefix, school):
    u = User(
        supabase_id=uuid.uuid4(), email=f"{prefix}-{uuid.uuid4()}@example.com",
        full_name=prefix.replace("_", " ").title(), role_id=role_row.id, school_id=school.id,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture()
def ann_seed(db_session):
    """Two grades, two sections in grade 3, one parent with BOTH grade-3 children.

    The two-children-one-grade case is deliberate: parent_student has no unique
    constraint, so this is the shape that produces duplicate recipients if the audience
    is not de-duplicated.
    """
    for name in ("admin", "principal", "teacher", "student", "parent"):
        if not db_session.query(Role).filter(Role.name == name).first():
            db_session.add(Role(name=name))
    db_session.flush()
    roles = {r.name: r for r in db_session.query(Role).all()}

    school = School(name="Announce School")
    other_school = School(name="Other School")
    db_session.add_all([school, other_school])
    db_session.flush()

    admin = _user(db_session, roles["admin"], "ann_admin", school)
    teacher = _user(db_session, roles["teacher"], "ann_teacher", school)
    outsider_teacher = _user(db_session, roles["teacher"], "ann_outsider", school)
    g3a_student = _user(db_session, roles["student"], "ann_g3a", school)
    g3b_student = _user(db_session, roles["student"], "ann_g3b", school)
    g1_student = _user(db_session, roles["student"], "ann_g1", school)
    parent = _user(db_session, roles["parent"], "ann_parent", school)
    lone_parent = _user(db_session, roles["parent"], "ann_lone_parent", school)

    def mk_class(name, grade, teacher_id):
        c = SchoolClass(
            name=name, academic_year=ACADEMIC_YEAR, school_id=school.id,
            class_teacher_id=teacher_id, grade_level=grade,
        )
        db_session.add(c)
        db_session.flush()
        return c

    g3a = mk_class("Grade 3 - A", 3, teacher.id)
    g3b = mk_class("Grade 3 - B", 3, None)
    g1a = mk_class("Grade 1 - A", 1, outsider_teacher.id)

    subject = Subject(name="Maths", school_id=school.id)
    db_session.add(subject)
    room = Room(name="A-1", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add(room)
    db_session.flush()

    # `teacher` teaches 3-B on the timetable without being its homeroom teacher - the
    # case that homeroom-only scoping would miss.
    db_session.add(TimetableSlot(
        class_id=g3b.id, subject_id=subject.id, teacher_id=teacher.id, room_id=room.id,
        academic_year=ACADEMIC_YEAR, day_of_week=0, period_number=1,
        start_time=time(9, 0), end_time=time(9, 45),
    ))

    db_session.add_all([
        Enrollment(student_id=g3a_student.id, class_id=g3a.id, is_primary=True),
        Enrollment(student_id=g3b_student.id, class_id=g3b.id, is_primary=True),
        Enrollment(student_id=g1_student.id, class_id=g1a.id, is_primary=True),
        # ONE parent, BOTH grade-3 children - must still be a single recipient.
        ParentStudent(parent_id=parent.id, student_id=g3a_student.id),
        ParentStudent(parent_id=parent.id, student_id=g3b_student.id),
        ParentStudent(parent_id=lone_parent.id, student_id=g1_student.id),
    ])
    db_session.commit()

    return {
        "school": school, "other_school": other_school, "admin": admin,
        "teacher": teacher, "outsider_teacher": outsider_teacher,
        "g3a": g3a, "g3b": g3b, "g1a": g1a,
        "g3a_student": g3a_student, "g3b_student": g3b_student, "g1_student": g1_student,
        "parent": parent, "lone_parent": lone_parent,
    }


def _post(client, **kw):
    payload = {"title": "T", "body": "B", "category": "general", "priority": "normal"}
    payload.update(kw)
    return client.post("/announcements", json=payload)


# --- audience resolution ------------------------------------------------------------


def test_grade_audience_reaches_both_sections_parents_and_teachers(db_session, ann_seed):
    """A Grade 3 announcement must reach BOTH sections' students, their linked parents,
    and the teachers of those classes - and nobody from Grade 1."""
    ann = Announcement(
        school_id=ann_seed["school"].id, author_id=ann_seed["admin"].id,
        scope_type="grade", scope_grade_level=3,
        title="T", body="B", category="general", priority="normal",
    )
    db_session.add(ann)
    db_session.flush()

    audience = resolve_audience(db_session, ann)

    assert ann_seed["g3a_student"].id in audience
    assert ann_seed["g3b_student"].id in audience, "the other section must be included"
    assert ann_seed["parent"].id in audience
    assert ann_seed["teacher"].id in audience, "homeroom of 3-A and timetabled on 3-B"

    assert ann_seed["g1_student"].id not in audience, "Grade 1 must not be reached"
    assert ann_seed["lone_parent"].id not in audience
    assert ann_seed["outsider_teacher"].id not in audience


def test_audience_deduplicates_a_parent_of_two_children_in_the_grade(db_session, ann_seed):
    """parent_student has no unique constraint and this parent has two grade-3 children.
    Without de-duplication they would be counted twice and get two bell rows."""
    ann = Announcement(
        school_id=ann_seed["school"].id, author_id=ann_seed["admin"].id,
        scope_type="grade", scope_grade_level=3,
        title="T", body="B", category="general", priority="normal",
    )
    db_session.add(ann)
    db_session.flush()

    audience = resolve_audience(db_session, ann)
    assert len(audience) == len(set(audience)), "audience must contain no duplicates"
    assert audience.count(ann_seed["parent"].id) == 1


def test_audience_excludes_the_author(db_session, ann_seed):
    """Dispatching to yourself puts a bell row on the person who just clicked Post."""
    ann = Announcement(
        school_id=ann_seed["school"].id, author_id=ann_seed["teacher"].id,
        scope_type="class", scope_class_id=ann_seed["g3a"].id,
        title="T", body="B", category="general", priority="normal",
    )
    db_session.add(ann)
    db_session.flush()
    assert ann_seed["teacher"].id not in resolve_audience(db_session, ann)


# --- the permission matrix ----------------------------------------------------------


def test_teacher_cannot_post_school_wide(client, ann_seed):
    _override_user("teacher", ann_seed["teacher"].id, ann_seed["school"].id)
    res = _post(client, scope_type="school")
    assert res.status_code == 403


def test_teacher_cannot_post_to_a_class_they_do_not_teach(client, ann_seed):
    _override_user("teacher", ann_seed["teacher"].id, ann_seed["school"].id)
    res = _post(client, scope_type="class", scope_class_id=ann_seed["g1a"].id)
    assert res.status_code == 403


def test_teacher_cannot_post_to_a_grade_they_do_not_teach(client, ann_seed):
    _override_user("teacher", ann_seed["teacher"].id, ann_seed["school"].id)
    res = _post(client, scope_type="grade", scope_grade_level=1)
    assert res.status_code == 403


def test_teacher_can_post_to_their_own_grade_and_class(client, ann_seed):
    _override_user("teacher", ann_seed["teacher"].id, ann_seed["school"].id)
    assert _post(client, scope_type="grade", scope_grade_level=3).status_code == 201
    assert _post(client, scope_type="class", scope_class_id=ann_seed["g3a"].id).status_code == 201


@pytest.mark.parametrize("role_key,role", [("g3a_student", "student"), ("parent", "parent")])
def test_students_and_parents_cannot_post(client, ann_seed, role_key, role):
    _override_user(role, ann_seed[role_key].id, ann_seed["school"].id)
    assert _post(client, scope_type="school").status_code == 403


@pytest.mark.parametrize("scope", ["school", "grade", "class"])
def test_admin_can_post_every_scope(client, ann_seed, scope):
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    kw = {"scope_type": scope}
    if scope == "grade":
        kw["scope_grade_level"] = 3
    if scope == "class":
        kw["scope_class_id"] = ann_seed["g3a"].id
    assert _post(client, **kw).status_code == 201


def test_admin_cannot_target_another_school(client, ann_seed, db_session):
    """A class outside the caller's school is a 404, not a 403 - otherwise an admin
    could probe another school's class ids by status code."""
    foreign = SchoolClass(
        name="Foreign 3 - A", academic_year=ACADEMIC_YEAR,
        school_id=ann_seed["other_school"].id, grade_level=3,
    )
    db_session.add(foreign)
    db_session.commit()

    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    res = _post(client, scope_type="class", scope_class_id=foreign.id)
    assert res.status_code == 404


def test_school_id_comes_from_the_token_not_the_body(client, ann_seed):
    """Passing school_id in the body must not move the announcement to another school."""
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    res = client.post("/announcements", json={
        "scope_type": "school", "title": "T", "body": "B",
        "category": "general", "priority": "normal",
        "school_id": ann_seed["other_school"].id,   # ignored - not a field on the schema
    })
    assert res.status_code == 201
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    assert any(i["title"] == "T" for i in client.get("/announcements/feed").json()["items"])


# --- scope column validation --------------------------------------------------------


@pytest.mark.parametrize("kw", [
    {"scope_type": "grade"},                                   # missing grade level
    {"scope_type": "class"},                                   # missing class id
    {"scope_type": "school", "scope_grade_level": 3},          # school takes neither
    {"scope_type": "grade", "scope_grade_level": 3, "scope_class_id": 1},
])
def test_scope_columns_must_agree_with_scope_type(client, ann_seed, kw):
    """A half-populated scope resolves to the wrong audience, or none, with no error."""
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    assert _post(client, **kw).status_code in (400, 404)


@pytest.mark.parametrize("kw", [{"category": "nonsense"}, {"priority": "screaming"}])
def test_unknown_category_or_priority_is_rejected(client, ann_seed, kw):
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    assert _post(client, scope_type="school", **kw).status_code == 400


# --- the feed -----------------------------------------------------------------------


def test_grade_1_student_does_not_see_a_grade_3_announcement(client, ann_seed):
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    _post(client, scope_type="grade", scope_grade_level=3, title="Grade 3 only")
    _post(client, scope_type="school", title="Everyone")

    _override_user("student", ann_seed["g1_student"].id, ann_seed["school"].id)
    titles = [i["title"] for i in client.get("/announcements/feed").json()["items"]]
    assert "Everyone" in titles, "school-wide reaches every student"
    assert "Grade 3 only" not in titles


def test_student_sees_school_grade_and_own_class(client, ann_seed):
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    _post(client, scope_type="school", title="S")
    _post(client, scope_type="grade", scope_grade_level=3, title="G")
    _post(client, scope_type="class", scope_class_id=ann_seed["g3a"].id, title="C")
    _post(client, scope_type="class", scope_class_id=ann_seed["g3b"].id, title="OtherSection")

    _override_user("student", ann_seed["g3a_student"].id, ann_seed["school"].id)
    titles = [i["title"] for i in client.get("/announcements/feed").json()["items"]]
    assert {"S", "G", "C"} <= set(titles)
    assert "OtherSection" not in titles, "another section's class post is not theirs"


def test_parent_feed_is_deduplicated_and_tags_the_related_children(client, ann_seed):
    """One item naming both children, not two copies - and school-wide items carry no
    child tag, because they relate to everyone."""
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    _post(client, scope_type="grade", scope_grade_level=3, title="G3")
    _post(client, scope_type="school", title="All")

    _override_user("parent", ann_seed["parent"].id, ann_seed["school"].id)
    items = client.get("/announcements/feed").json()["items"]

    g3 = [i for i in items if i["title"] == "G3"]
    assert len(g3) == 1, "a parent of two grade-3 children gets ONE item"
    assert len(g3[0]["related_children"]) == 2, "tagged with both children"

    all_item = next(i for i in items if i["title"] == "All")
    assert all_item["related_children"] == [], "school-wide relates to everyone"


def test_parent_does_not_see_an_unlinked_childs_class_announcement(client, ann_seed):
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    _post(client, scope_type="class", scope_class_id=ann_seed["g1a"].id, title="G1 class")

    _override_user("parent", ann_seed["parent"].id, ann_seed["school"].id)
    titles = [i["title"] for i in client.get("/announcements/feed").json()["items"]]
    assert "G1 class" not in titles


def test_feed_pins_urgent_then_important_then_newest(client, ann_seed):
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    _post(client, scope_type="school", title="normal one", priority="normal")
    _post(client, scope_type="school", title="urgent one", priority="urgent")
    _post(client, scope_type="school", title="important one", priority="important")

    _override_user("student", ann_seed["g3a_student"].id, ann_seed["school"].id)
    titles = [i["title"] for i in client.get("/announcements/feed").json()["items"]]
    assert titles[:3] == ["urgent one", "important one", "normal one"]


def test_feed_has_no_user_id_parameter(client, ann_seed):
    """The audience a caller belongs to comes from their token. A user_id parameter
    would be a way for a client to widen it, so it must not exist - passing one is
    ignored rather than honoured."""
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    _post(client, scope_type="class", scope_class_id=ann_seed["g3a"].id, title="C")

    _override_user("student", ann_seed["g1_student"].id, ann_seed["school"].id)
    res = client.get("/announcements/feed", params={"user_id": ann_seed["g3a_student"].id})
    assert res.status_code == 200
    assert "C" not in [i["title"] for i in res.json()["items"]]


# --- delivery routes through the existing notification path -------------------------


def test_posting_dispatches_notifications_with_source_type_announcement(client, ann_seed, db_session):
    """The architectural rule, asserted: announcements are a SOURCE, not a second
    delivery system. Recipients get a row in the bell they already have."""
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    res = _post(client, scope_type="grade", scope_grade_level=3, title="Dispatch me", priority="urgent")
    assert res.status_code == 201
    ann_id = res.json()["announcement"]["id"]
    recipients = res.json()["recipients"]
    assert recipients > 0

    rows = (
        db_session.query(Notification)
        .filter(Notification.source_type == "announcement", Notification.source_id == ann_id)
        .all()
    )
    assert len(rows) == recipients, "one bell row per resolved recipient"
    assert {r.priority for r in rows} == {"urgent"}, "urgent must arrive urgent"
    assert ann_seed["admin"].id not in {r.user_id for r in rows}, "not to the author"


# --- acknowledgment -----------------------------------------------------------------


def test_acknowledge_requires_being_in_the_audience(client, ann_seed):
    """Acknowledging something you were never sent would inflate the numerator of a
    ratio whose denominator is the audience."""
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    ann_id = _post(client, scope_type="class", scope_class_id=ann_seed["g3a"].id).json()["announcement"]["id"]

    _override_user("student", ann_seed["g1_student"].id, ann_seed["school"].id)
    assert client.put(f"/announcements/{ann_id}/acknowledge").status_code == 403

    _override_user("student", ann_seed["g3a_student"].id, ann_seed["school"].id)
    assert client.put(f"/announcements/{ann_id}/acknowledge").status_code == 200


def test_acknowledge_is_idempotent(client, ann_seed):
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    ann_id = _post(client, scope_type="school").json()["announcement"]["id"]

    _override_user("student", ann_seed["g3a_student"].id, ann_seed["school"].id)
    first = client.put(f"/announcements/{ann_id}/acknowledge").json()
    second = client.put(f"/announcements/{ann_id}/acknowledge").json()
    assert second["acknowledged"] is True
    assert first["acknowledged_at"] == second["acknowledged_at"], "keeps the first timestamp"


def test_ack_status_is_author_admin_or_principal_only(client, ann_seed):
    _override_user("teacher", ann_seed["teacher"].id, ann_seed["school"].id)
    ann_id = _post(client, scope_type="class", scope_class_id=ann_seed["g3a"].id).json()["announcement"]["id"]

    _override_user("teacher", ann_seed["teacher"].id, ann_seed["school"].id)
    assert client.get(f"/announcements/{ann_id}/ack-status").status_code == 200  # author
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    assert client.get(f"/announcements/{ann_id}/ack-status").status_code == 200
    _override_user("student", ann_seed["g3a_student"].id, ann_seed["school"].id)
    assert client.get(f"/announcements/{ann_id}/ack-status").status_code == 403


def test_ack_status_counts_add_up(client, ann_seed):
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    ann_id = _post(client, scope_type="grade", scope_grade_level=3).json()["announcement"]["id"]

    _override_user("student", ann_seed["g3a_student"].id, ann_seed["school"].id)
    client.put(f"/announcements/{ann_id}/acknowledge")

    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    st = client.get(f"/announcements/{ann_id}/ack-status").json()
    assert st["acknowledged_count"] == 1
    assert st["audience_size"] == len(st["acknowledged"]) + len(st["outstanding"])
    assert st["acknowledged"][0]["user_id"] == ann_seed["g3a_student"].id


def test_single_announcement_respects_visibility(client, ann_seed):
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    ann_id = _post(client, scope_type="grade", scope_grade_level=3).json()["announcement"]["id"]

    _override_user("student", ann_seed["g3a_student"].id, ann_seed["school"].id)
    assert client.get(f"/announcements/{ann_id}").status_code == 200
    _override_user("student", ann_seed["g1_student"].id, ann_seed["school"].id)
    assert client.get(f"/announcements/{ann_id}").status_code == 403


def test_announcement_from_another_school_is_404(client, ann_seed, db_session):
    foreign = Announcement(
        school_id=ann_seed["other_school"].id, author_id=ann_seed["admin"].id,
        scope_type="school", title="Foreign", body="B", category="general", priority="normal",
    )
    db_session.add(foreign)
    db_session.commit()

    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    assert client.get(f"/announcements/{foreign.id}").status_code == 404


# --- postable scopes (what the composer may OFFER) ----------------------------------


def test_postable_scopes_never_offers_school_to_a_teacher(client, ann_seed):
    """The composer renders from this. A teacher must get can_post_school=False so the
    option is ABSENT rather than present-and-rejected - an option you can see but not
    use reads as a broken UI, not a permission."""
    _override_user("teacher", ann_seed["teacher"].id, ann_seed["school"].id)
    body = client.get("/announcements/postable-scopes").json()
    assert body["can_post"] is True
    assert body["can_post_school"] is False

    names = {c["name"] for c in body["classes"]}
    assert {"Grade 3 - A", "Grade 3 - B"} <= names, "homeroom AND timetable-taught"
    assert "Grade 1 - A" not in names, "a class they do not teach must not be offered"
    assert 1 not in body["grades"]


def test_postable_scopes_offers_everything_to_an_admin(client, ann_seed):
    _override_user("admin", ann_seed["admin"].id, ann_seed["school"].id)
    body = client.get("/announcements/postable-scopes").json()
    assert body["can_post"] is True and body["can_post_school"] is True
    assert {1, 3} <= set(body["grades"])


@pytest.mark.parametrize("role_key,role", [("g3a_student", "student"), ("parent", "parent")])
def test_postable_scopes_is_empty_for_students_and_parents(client, ann_seed, role_key, role):
    """can_post=False hides the composer entirely for roles that may never post."""
    _override_user(role, ann_seed[role_key].id, ann_seed["school"].id)
    body = client.get("/announcements/postable-scopes").json()
    assert body["can_post"] is False
    assert body["classes"] == [] and body["grades"] == []


def test_postable_scopes_offering_is_not_the_boundary(client, ann_seed):
    """Even if a client ignores postable-scopes entirely and posts school-wide as a
    teacher, the server still refuses. The offering is a convenience, not the gate."""
    _override_user("teacher", ann_seed["teacher"].id, ann_seed["school"].id)
    assert _post(client, scope_type="school").status_code == 403
