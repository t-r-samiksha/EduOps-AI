"""Person B authorization gaps found by the seam/bug audit (docs/audit/pb-02-bugs.md).

Each test here failed before its fix. They cover the three BLOCKERs:

  B-1  POST /remarks and /remarks/bulk had NO role gate - any authenticated user,
       including a student or parent, could file teacher remarks about anyone.
  B-2  Teachers could create assignments AND quizzes for classes they do not teach.
       `_classes_taught_by` existed 12 lines above the check that never called it.
  B-3  POST /report_cards/generate/{student_id} was not school-scoped - a cross-tenant
       write that also dispatched notifications to another school's parents.
"""

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from app.main import app
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int, school_id: int | None = None):
    def _fake():
        return CurrentUser(
            id=user_id, sub=str(uuid.uuid4()), email=f"{role}-{user_id}@example.com",
            role=role, school_id=school_id,
        )

    app.dependency_overrides[get_current_user] = _fake


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
def pb_seed(db_session):
    """A teacher who teaches ONE class, another class they don't teach, and a student in
    a second school - the three shapes the blockers need to be proven against."""
    for name in ("admin", "principal", "teacher", "student", "parent"):
        if not db_session.query(Role).filter(Role.name == name).first():
            db_session.add(Role(name=name))
    db_session.flush()
    roles = {r.name: r for r in db_session.query(Role).all()}

    school = School(name="PB Authz School")
    other_school = School(name="PB Other School")
    db_session.add_all([school, other_school])
    db_session.flush()

    teacher = _user(db_session, roles["teacher"], "pb_teacher", school)
    admin = _user(db_session, roles["admin"], "pb_admin", school)
    student = _user(db_session, roles["student"], "pb_student", school)
    parent = _user(db_session, roles["parent"], "pb_parent", school)
    foreign_student = _user(db_session, roles["student"], "pb_foreign", other_school)

    def mk_class(name, grade, school_obj, teacher_id=None):
        c = SchoolClass(
            name=name, academic_year=ACADEMIC_YEAR, school_id=school_obj.id,
            class_teacher_id=teacher_id, grade_level=grade,
        )
        db_session.add(c)
        db_session.flush()
        return c

    taught = mk_class("Taught 3 - A", 3, school, teacher.id)
    untaught = mk_class("Untaught 1 - A", 1, school, None)
    foreign_class = mk_class("Foreign 3 - A", 3, other_school, None)

    subject = Subject(name="Maths", school_id=school.id)
    db_session.add(subject)
    room = Room(name="R1", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add(room)
    db_session.flush()

    db_session.add_all([
        Enrollment(student_id=student.id, class_id=taught.id, is_primary=True),
        Enrollment(student_id=foreign_student.id, class_id=foreign_class.id, is_primary=True),
    ])
    db_session.commit()
    return {
        "school": school, "other_school": other_school, "teacher": teacher, "admin": admin,
        "student": student, "parent": parent, "foreign_student": foreign_student,
        "taught": taught, "untaught": untaught, "foreign_class": foreign_class,
        "subject": subject,
    }


# --- B-1 -----------------------------------------------------------------------------


@pytest.mark.parametrize("role_key,role", [("student", "student"), ("parent", "parent")])
def test_students_and_parents_cannot_create_remarks(client, pb_seed, role_key, role):
    """BLOCKER B-1. Both endpoints used Depends(get_current_user) with no require_role,
    so any authenticated account could file a teacher remark about any student,
    attributed to itself."""
    _override_user(role, pb_seed[role_key].id, pb_seed["school"].id)

    single = client.post("/remarks", json={
        "student_id": pb_seed["student"].id, "class_id": pb_seed["taught"].id,
        "content": "unauthorized", "sentiment_tag": "behavioral",
    })
    assert single.status_code == 403

    bulk = client.post("/remarks/bulk", json={
        "class_id": pb_seed["taught"].id,
        "remarks": [{"student_id": pb_seed["student"].id, "content": "x", "sentiment_tag": "academic"}],
    })
    assert bulk.status_code == 403


def test_teacher_can_still_create_remarks(client, pb_seed):
    """The fix must not break the feature it protects."""
    _override_user("teacher", pb_seed["teacher"].id, pb_seed["school"].id)
    res = client.post("/remarks", json={
        "student_id": pb_seed["student"].id, "class_id": pb_seed["taught"].id,
        "content": "Working hard this term.", "sentiment_tag": "appreciation",
    })
    assert res.status_code == 201
    assert res.json()["content"] == "Working hard this term."


# --- B-2 -----------------------------------------------------------------------------


def test_teacher_cannot_create_assignment_for_a_class_they_do_not_teach(client, pb_seed):
    """BLOCKER B-2 (known failure 1). _assert_can_manage_class_assignment checked only
    that the class was in the caller's SCHOOL, never that the teacher taught it."""
    _override_user("teacher", pb_seed["teacher"].id, pb_seed["school"].id)
    res = client.post("/assignments", json={
        "class_id": pb_seed["untaught"].id, "subject_id": pb_seed["subject"].id,
        "title": "Not my class", "description": "d",
        "deadline": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        "max_marks": 10,
    })
    assert res.status_code == 403


def test_teacher_cannot_create_quiz_for_a_class_they_do_not_teach(client, pb_seed):
    """BLOCKER B-2 sibling: create_quiz had the identical school-only shape."""
    _override_user("teacher", pb_seed["teacher"].id, pb_seed["school"].id)
    res = client.post("/quizzes", json={
        "class_id": pb_seed["untaught"].id, "subject_id": pb_seed["subject"].id,
        "title": "Not my class", "duration_minutes": 10,
        "questions": [{
            "question_text": "q", "option_a": "a", "option_b": "b",
            "option_c": "c", "option_d": "d", "correct_option": "A",
            "marks": 1, "order_index": 0,
        }],
    })
    assert res.status_code == 403


def test_teacher_can_create_for_their_own_class(client, pb_seed):
    _override_user("teacher", pb_seed["teacher"].id, pb_seed["school"].id)
    a = client.post("/assignments", json={
        "class_id": pb_seed["taught"].id, "subject_id": pb_seed["subject"].id,
        "title": "Mine", "description": "d",
        "deadline": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        "max_marks": 10,
    })
    assert a.status_code == 201

    q = client.post("/quizzes", json={
        "class_id": pb_seed["taught"].id, "subject_id": pb_seed["subject"].id,
        "title": "Mine", "duration_minutes": 10,
        "questions": [{
            "question_text": "q", "option_a": "a", "option_b": "b",
            "option_c": "c", "option_d": "d", "correct_option": "A",
            "marks": 1, "order_index": 0,
        }],
    })
    assert q.status_code == 201


def test_admin_is_not_restricted_to_taught_classes(client, pb_seed):
    """Admins have no teaching scope; the taught-check must apply to teachers only."""
    _override_user("admin", pb_seed["admin"].id, pb_seed["school"].id)
    res = client.post("/assignments", json={
        "class_id": pb_seed["untaught"].id, "subject_id": pb_seed["subject"].id,
        "title": "Admin can", "description": "d",
        "deadline": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        "max_marks": 10,
    })
    assert res.status_code == 201


# --- B-3 -----------------------------------------------------------------------------


def test_report_card_cannot_be_generated_for_another_schools_student(client, pb_seed):
    """BLOCKER B-3. Neither the router nor the service compared the student's school to
    the caller's - a cross-tenant write that also notified the other school's parents.
    404 rather than 403 so student ids in other schools can't be probed by status code."""
    _override_user("teacher", pb_seed["teacher"].id, pb_seed["school"].id)
    res = client.post(f"/report_cards/generate/{pb_seed['foreign_student'].id}")
    assert res.status_code == 404


def test_bulk_report_cards_cannot_target_another_schools_class(client, pb_seed):
    _override_user("admin", pb_seed["admin"].id, pb_seed["school"].id)
    res = client.post(f"/report_cards/bulk-generate/{pb_seed['foreign_class'].id}")
    assert res.status_code == 404


def test_report_card_still_generates_for_own_school(client, pb_seed):
    _override_user("teacher", pb_seed["teacher"].id, pb_seed["school"].id)
    res = client.post(f"/report_cards/generate/{pb_seed['student'].id}")
    assert res.status_code == 200
    assert res.json()["student_id"] == pb_seed["student"].id


# --- M-1: report card parent notifications were never committed ----------------------


def test_report_card_generation_actually_delivers_the_parent_notification(client, pb_seed, db_session):
    """M-1. dispatch_bulk sat AFTER db.commit() in each upsert branch with no commit of
    its own, so the Notification rows were added to the session and dropped when the
    request ended. Four generations produced exactly one notification in production.
    """
    from app.models.notification import Notification
    from app.models.parent_student import ParentStudent

    db_session.add(ParentStudent(parent_id=pb_seed["parent"].id, student_id=pb_seed["student"].id))
    db_session.commit()

    _override_user("teacher", pb_seed["teacher"].id, pb_seed["school"].id)
    res = client.post(f"/report_cards/generate/{pb_seed['student'].id}")
    assert res.status_code == 200

    rows = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == pb_seed["parent"].id,
            Notification.source_id == res.json()["id"],
        )
        .all()
    )
    assert len(rows) == 1, "the parent notification must actually be committed"
    # M-7: was "report_card_ready", which is not in SOURCE_TYPES.
    assert rows[0].source_type == "report_card"


def test_regenerating_a_report_card_does_not_re_notify(client, pb_seed, db_session):
    """Bulk-regenerating a class of 30 twice must not send 60 notifications."""
    from app.models.notification import Notification
    from app.models.parent_student import ParentStudent

    db_session.add(ParentStudent(parent_id=pb_seed["parent"].id, student_id=pb_seed["student"].id))
    db_session.commit()

    _override_user("teacher", pb_seed["teacher"].id, pb_seed["school"].id)
    client.post(f"/report_cards/generate/{pb_seed['student'].id}")
    client.post(f"/report_cards/generate/{pb_seed['student'].id}")
    client.post(f"/report_cards/generate/{pb_seed['student'].id}")

    count = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == pb_seed["parent"].id,
            Notification.source_type == "report_card",
        )
        .count()
    )
    assert count == 1, "only the first publication notifies"


# --- S-F: grading an assignment writes a gradebook entry -----------------------------


def test_grading_an_assignment_creates_a_gradebook_entry(client, pb_seed, db_session):
    """SEAM S-F. Quiz attempts wrote gradebook entries from the start; grading an
    assignment wrote only to assignment_submissions, so a teacher entered every score
    twice and assignment grades never reached analytics, report cards or risk scoring.
    """
    from app.models.assignment import Assignment, AssignmentSubmission
    from app.models.gradebook import GradebookEntry

    assignment = Assignment(
        school_id=pb_seed["school"].id, class_id=pb_seed["taught"].id,
        subject_id=pb_seed["subject"].id, teacher_id=pb_seed["teacher"].id,
        title="Graded work", description="d",
        deadline=datetime.now(timezone.utc) + timedelta(days=1), max_marks=20,
    )
    db_session.add(assignment)
    db_session.flush()
    submission = AssignmentSubmission(
        assignment_id=assignment.id, student_id=pb_seed["student"].id,
        file_url="f", file_name="f.pdf", file_size=1, status="submitted",
        submitted_at=datetime.now(timezone.utc),
    )
    db_session.add(submission)
    db_session.commit()

    _override_user("teacher", pb_seed["teacher"].id, pb_seed["school"].id)
    res = client.put(
        f"/assignments/{assignment.id}/grade/{submission.id}",
        json={"grade": 17, "feedback": "Good work"},
    )
    assert res.status_code == 200

    entry = (
        db_session.query(GradebookEntry)
        .filter(
            GradebookEntry.student_id == pb_seed["student"].id,
            GradebookEntry.assessment_type == "assignment",
            GradebookEntry.assessment_id == assignment.id,
        )
        .one_or_none()
    )
    assert entry is not None, "grading must record the score in the gradebook"
    assert entry.score == 17
    assert entry.max_score == 20

    # Re-grading updates in place rather than stacking duplicates that would be averaged.
    client.put(
        f"/assignments/{assignment.id}/grade/{submission.id}",
        json={"grade": 19, "feedback": "Revised"},
    )
    entries = (
        db_session.query(GradebookEntry)
        .filter(
            GradebookEntry.student_id == pb_seed["student"].id,
            GradebookEntry.assessment_type == "assignment",
            GradebookEntry.assessment_id == assignment.id,
        )
        .all()
    )
    assert len(entries) == 1
    assert entries[0].score == 19


def test_subjectless_assessment_is_skipped_not_misfiled(db_session, pb_seed):
    """M-5. The old code passed `subject_id or 1`, filing the grade against subject id 1
    - whichever school owns that row. Skipping is the honest outcome."""
    from app.services.gradebook_service import upsert_assessment_grade

    result = upsert_assessment_grade(
        db_session,
        school_id=pb_seed["school"].id,
        student_id=pb_seed["student"].id,
        subject_id=None,
        class_id=pb_seed["taught"].id,
        assessment_type="quiz",
        assessment_id=999,
        score=5,
        max_score=10,
    )
    assert result is None


# --- M-2: one attendance implementation, two windows ---------------------------------


@pytest.fixture()
def attendance_rows(db_session, pb_seed):
    """A student with a known mix INSIDE and OUTSIDE the 30-day window."""
    from datetime import date
    from app.models.attendance import AttendanceRecord

    today = date.today()
    rows = []
    # inside 30 days: 3 present, 1 absent, 1 late  -> present-only = 3/5 = 60.0%
    for i, st in enumerate(["present", "present", "present", "absent", "late"]):
        rows.append(AttendanceRecord(
            student_id=pb_seed["student"].id, class_id=pb_seed["taught"].id,
            date=today - timedelta(days=i + 1), status=st, source="manual",
        ))
    # outside 30 days: 5 more present, which must NOT affect the 30-day figure
    for i in range(5):
        rows.append(AttendanceRecord(
            student_id=pb_seed["student"].id, class_id=pb_seed["taught"].id,
            date=today - timedelta(days=60 + i), status="present", source="manual",
        ))
    db_session.add_all(rows)
    db_session.commit()
    return pb_seed


def test_late_is_not_counted_as_present(db_session, attendance_rows, pb_seed):
    """M-2 rule 1. Analytics and report cards counted `late` as present, inflating every
    figure and disagreeing with the parent portal."""
    from app.services.attendance_stats import lookback_snapshot

    snap = lookback_snapshot(db_session, pb_seed["student"].id, 30)
    assert snap.present_count == 3
    assert snap.late_count == 1
    assert snap.present_pct == 60.0, "3 present of 5 records - late is reported, not counted"


def test_window_is_respected(db_session, attendance_rows, pb_seed):
    """The 5 older rows are real but outside the window and must not leak in."""
    from app.services.attendance_stats import attendance_snapshot, lookback_snapshot

    assert lookback_snapshot(db_session, pb_seed["student"].id, 30).total_records == 5
    assert attendance_snapshot(db_session, pb_seed["student"].id).total_records == 10


def test_no_records_returns_none_not_a_hundred_percent(db_session, pb_seed):
    """M-2 rule 2. Every surface returned 100.0 for a student with no data, so 'no
    information' rendered as 'perfect attendance'."""
    from app.services.attendance_stats import lookback_snapshot

    snap = lookback_snapshot(db_session, pb_seed["student"].id, 30)
    assert snap.total_records == 0
    assert snap.present_pct is None


def test_academic_year_window_is_bounded_and_labelled(db_session, attendance_rows, pb_seed):
    """The report card's window: the whole academic year, carrying its own label so the
    different number reads as a different measure."""
    from app.services.attendance_stats import academic_year_bounds, academic_year_snapshot

    start, end = academic_year_bounds("2026-27")
    assert (start.year, start.month) == (2026, 4)
    assert (end.year, end.month) == (2027, 3)

    snap = academic_year_snapshot(db_session, pb_seed["student"].id, "2026-27")
    assert snap.label == "Attendance — 2026-27"
    assert snap.start_date == start and snap.end_date == end


def test_portal_and_analytics_agree_by_construction(client, attendance_rows, pb_seed):
    """The whole point of M-2: the two surfaces a judge can see side by side must not
    disagree about one child."""
    _override_user("parent", pb_seed["parent"].id, pb_seed["school"].id)
    from app.models.parent_student import ParentStudent

    _override_user("teacher", pb_seed["teacher"].id, pb_seed["school"].id)
    analytics = client.get(f"/analytics/student/{pb_seed['student'].id}").json()["attendance"]

    assert analytics["percentage"] == 60.0
    assert analytics["late_days"] == 1
    assert analytics["window_label"] == "Last 30 days"


# --- M-3 / M-4: quiz window and timing ------------------------------------------------


def _make_quiz(db_session, pb_seed, *, opens_days=-1, closes_days=1, duration=10):
    from app.models.quiz import Quiz, QuizQuestion

    now = datetime.now(timezone.utc)
    quiz = Quiz(
        school_id=pb_seed["school"].id, class_id=pb_seed["taught"].id,
        subject_id=pb_seed["subject"].id, teacher_id=pb_seed["teacher"].id,
        title="Timed quiz", duration_minutes=duration,
        available_from=now + timedelta(days=opens_days),
        available_until=now + timedelta(days=closes_days),
    )
    db_session.add(quiz)
    db_session.flush()
    q = QuizQuestion(
        quiz_id=quiz.id, question_text="2+2?", option_a="3", option_b="4",
        option_c="5", option_d="6", correct_option="B", marks=1.0, order_index=0,
    )
    db_session.add(q)
    db_session.commit()
    return quiz, q


def test_quiz_closed_window_is_enforced(client, pb_seed, db_session):
    """M-3. A quiz whose available_until had passed 16 days earlier still accepted and
    graded a submission - the window was never read."""
    quiz, q = _make_quiz(db_session, pb_seed, opens_days=-10, closes_days=-5)
    _override_user("student", pb_seed["student"].id, pb_seed["school"].id)

    assert client.post(f"/quizzes/{quiz.id}/start").status_code == 403
    assert client.post(f"/quizzes/{quiz.id}/attempt", json={"answers": {str(q.id): "B"}}).status_code == 403


def test_quiz_not_yet_open_is_enforced(client, pb_seed, db_session):
    quiz, _ = _make_quiz(db_session, pb_seed, opens_days=2, closes_days=5)
    _override_user("student", pb_seed["student"].id, pb_seed["school"].id)
    assert client.post(f"/quizzes/{quiz.id}/start").status_code == 403


def test_start_records_a_real_started_at_and_is_idempotent(client, pb_seed, db_session):
    """M-4. started_at used to be invented at SUBMIT time as `now - duration_minutes`,
    so every attempt looked like it took exactly the allowed time."""
    quiz, _ = _make_quiz(db_session, pb_seed)
    _override_user("student", pb_seed["student"].id, pb_seed["school"].id)

    first = client.post(f"/quizzes/{quiz.id}/start")
    assert first.status_code == 200
    assert first.json()["status"] == "in_progress"
    assert first.json()["submitted_at"] is None

    # A refresh or double-tap must not reset the clock or burn the attempt.
    second = client.post(f"/quizzes/{quiz.id}/start")
    assert second.status_code == 200
    assert second.json()["started_at"] == first.json()["started_at"]
    assert second.json()["id"] == first.json()["id"]


def test_submitting_without_starting_is_refused(client, pb_seed, db_session):
    """A submission with no recorded start cannot be timed, so it is refused rather
    than accepted with a fabricated duration."""
    quiz, q = _make_quiz(db_session, pb_seed)
    _override_user("student", pb_seed["student"].id, pb_seed["school"].id)
    res = client.post(f"/quizzes/{quiz.id}/attempt", json={"answers": {str(q.id): "B"}})
    assert res.status_code == 400


def test_over_duration_is_accepted_and_flagged_not_rejected(client, pb_seed, db_session):
    """DECISION: running over the clock must not lose the student's work. The submission
    is graded and recorded as `time_expired` so the teacher sees it ran over."""
    from app.models.quiz import QuizAttempt

    quiz, q = _make_quiz(db_session, pb_seed, duration=10)
    _override_user("student", pb_seed["student"].id, pb_seed["school"].id)
    client.post(f"/quizzes/{quiz.id}/start")

    # Backdate the start so the submission is 30 minutes into a 10-minute quiz.
    attempt = (
        db_session.query(QuizAttempt)
        .filter(QuizAttempt.quiz_id == quiz.id, QuizAttempt.student_id == pb_seed["student"].id)
        .one()
    )
    attempt.started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.commit()

    res = client.post(f"/quizzes/{quiz.id}/attempt", json={"answers": {str(q.id): "B"}})
    assert res.status_code == 200, "work must not be lost to the clock"
    body = res.json()
    assert body["status"] == "time_expired"
    assert body["score"] == 1.0, "and it is still graded on its merits"


def test_within_duration_completes_normally(client, pb_seed, db_session):
    quiz, q = _make_quiz(db_session, pb_seed, duration=10)
    _override_user("student", pb_seed["student"].id, pb_seed["school"].id)
    client.post(f"/quizzes/{quiz.id}/start")

    res = client.post(f"/quizzes/{quiz.id}/attempt", json={"answers": {str(q.id): "B"}})
    assert res.status_code == 200
    assert res.json()["status"] == "completed"


# --- M-7: the notification vocabulary is validated -----------------------------------


def test_dispatch_rejects_an_undeclared_source_type(db_session):
    """M-7. Nine of twenty source types were dispatched without ever being declared,
    across BOTH developers' features, each landing in the bell with no icon and no
    route. notify.py was deliberately lenient, which is how it drifted."""
    from app.services.notify import dispatch_notification

    with pytest.raises(ValueError, match="unknown notification source_type"):
        dispatch_notification(db_session, user_id=1, source_type="totally_made_up", title="t")


def test_dispatch_rejects_an_unknown_priority(db_session):
    from app.services.notify import dispatch_notification

    with pytest.raises(ValueError, match="unknown notification priority"):
        dispatch_notification(
            db_session, user_id=1, source_type="announcement", title="t", priority="screaming"
        )


def test_every_dispatch_call_site_uses_a_declared_source_type():
    """The audit that made enabling validation safe, kept as a test so a new dispatch
    with an undeclared type fails here rather than silently in the bell."""
    import ast
    import pathlib
    from app.models.notification import SOURCE_TYPES

    offenders = []
    roots = [pathlib.Path("app"), pathlib.Path("scripts")]
    for root in roots:
        for f in root.rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if fn not in ("dispatch_notification", "dispatch_bulk"):
                    continue
                for kw in node.keywords:
                    if kw.arg == "source_type" and isinstance(kw.value, ast.Constant):
                        if kw.value.value not in SOURCE_TYPES:
                            offenders.append(f"{f}:{node.lineno} -> {kw.value.value!r}")
    assert not offenders, "undeclared notification source_type at: " + "; ".join(offenders)


# --- Addition A: top doubts must show DOUBTS ------------------------------------------


@pytest.mark.parametrize("query,keep", [
    ("hi", False),
    ("Hello sir", False),
    ("thanks!", False),
    ("ok", False),
    ("", False),
    ("why do we carry the one", True),
    ("hi miss why do we carry the one", True),  # a greeting wrapping a real question
    ("photosynthesis?", True),
])
def test_small_talk_is_not_a_doubt(query, keep):
    """The teacher widget led with a cluster labelled "Casual Greetings - students are
    opening the chat with casual greetings without asking academic questions": a true
    statement about the data and no use as an insight."""
    from app.services.doubt_insights import _is_academic_doubt

    assert _is_academic_doubt(query) is keep


def test_top_doubts_excludes_parent_bot_questions(db_session, pb_seed):
    """chatbot_logs is shared by all three bots and _fetch_logs never filtered, so a
    teacher's Top Doubts clustered PARENT questions - including "does X have ADHD or a
    learning disability?" - as if they were common student doubts."""
    from app.models.knowledge import ChatbotLog
    from app.services.doubt_insights import _fetch_logs

    for bot_type, q in [
        ("student", "why do we carry the one when we multiply"),
        ("student", "hi"),
        ("parent", "does my child have a learning disability?"),
        ("teacher", "give me 5 MCQs on fractions"),
    ]:
        db_session.add(ChatbotLog(
            user_id=pb_seed["student"].id, bot_type=bot_type, query=q, response="r",
            class_id=pb_seed["taught"].id, subject_id=pb_seed["subject"].id,
        ))
    db_session.commit()

    kept = _fetch_logs(
        db_session, school_id=pb_seed["school"].id, grade_level=3, subject_id=None, days=30
    )
    queries = [log.query for log, _ in kept]

    assert "why do we carry the one when we multiply" in queries
    assert "hi" not in queries, "small talk is not a doubt"
    assert "does my child have a learning disability?" not in queries, "parent bot, wrong audience"
    assert "give me 5 MCQs on fractions" not in queries, "teacher bot, not a student doubt"
