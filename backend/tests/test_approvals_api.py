import uuid
from datetime import date, time

import pytest

from app.main import app
from app.models.audit import AuditLogEntry
from app.models.class_ import SchoolClass
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest, Substitution
from app.models.subject import Subject
from app.models.timetable import Room, TeacherSubject, TimetableSlot
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
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()

    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    teacher = _make_user(db_session, teacher_role, "teacher", school)
    sub_teacher = _make_user(db_session, teacher_role, "sub-teacher", school)

    subject = Subject(name="Math", school_id=school.id)
    db_session.add(subject)
    db_session.flush()
    room = Room(name="R1", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add(room)
    db_session.flush()
    school_class = SchoolClass(
        name="8A", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=teacher.id,
        grade_level=8, section="A", is_active=True,
    )
    db_session.add(school_class)
    db_session.flush()

    db_session.add(TeacherSubject(teacher_id=sub_teacher.id, subject_id=subject.id))
    # day_of_week must match today's weekday, since pending_leave below uses
    # date.today() for a single-day leave - _distinct_slots_for_leave only touches
    # the weekday(s) actually spanned by the leave's date range.
    db_session.add(
        TimetableSlot(
            day_of_week=date.today().weekday(), period_number=0, start_time=time(8, 0), end_time=time(8, 45),
            subject_id=subject.id, teacher_id=teacher.id, class_id=school_class.id, room_id=room.id,
            academic_year=ACADEMIC_YEAR, is_active=True,
        )
    )
    db_session.commit()

    return {"school": school, "class": school_class, "admin_user": admin_user, "teacher": teacher, "sub_teacher": sub_teacher}


@pytest.fixture()
def pending_leave(db_session, seed):
    lr = LeaveRequest(teacher_id=seed["teacher"].id, start_date=date.today(), end_date=date.today(), reason="sick", status="pending")
    db_session.add(lr)
    db_session.commit()
    db_session.refresh(lr)
    return lr


# --- RBAC ---


def test_list_approvals_401_without_token(client):
    resp = client.get("/admin/approvals")
    assert resp.status_code == 401


def test_list_approvals_403_for_teacher_role(client):
    # Deliberate: teacher is NOT authorized for the unified inbox - see
    # routers/approvals.py's own comment for why.
    _override_user("teacher")
    resp = client.get("/admin/approvals")
    assert resp.status_code == 403


def test_decision_401_without_token(client):
    resp = client.post("/admin/approvals/leave_request:1/decision", json={"decision": "approve"})
    assert resp.status_code == 401


def test_decision_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/approvals/leave_request:1/decision", json={"decision": "approve"})
    assert resp.status_code == 403


# --- GET /admin/approvals ---


def test_list_approvals_returns_pending_leave_request(client, seed, pending_leave):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/approvals")
    assert resp.status_code == 200
    items = resp.json()["items"]
    match = next(i for i in items if i["id"] == f"leave_request:{pending_leave.id}")
    assert match["type"] == "leave_request"
    assert match["requested_by"] == seed["teacher"].id
    assert match["entity_type"] == "leave_requests"
    assert match["payload"]["reason"] == "sick"


# --- POST /admin/approvals/{id}/decision ---


def test_approve_decision_applies_and_creates_substitutions(client, db_session, seed, pending_leave):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        f"/admin/approvals/leave_request:{pending_leave.id}/decision",
        json={"decision": "approve", "academic_year": ACADEMIC_YEAR},
    )
    assert resp.status_code == 200
    assert resp.json() == {"id": f"leave_request:{pending_leave.id}", "status": "approved"}

    db_session.refresh(pending_leave)
    assert pending_leave.status == "approved"
    assert pending_leave.decided_by == seed["admin_user"].id
    assert pending_leave.decided_at is not None

    subs = db_session.query(Substitution).filter(Substitution.leave_request_id == pending_leave.id).all()
    assert len(subs) == 1
    assert subs[0].substitute_teacher_id == seed["sub_teacher"].id


def test_reject_decision_does_not_require_academic_year(client, db_session, seed, pending_leave):
    _override_user("principal", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/approvals/leave_request:{pending_leave.id}/decision", json={"decision": "reject"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    db_session.refresh(pending_leave)
    assert pending_leave.status == "rejected"


def test_approve_decision_without_academic_year_returns_400(client, seed, pending_leave):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/approvals/leave_request:{pending_leave.id}/decision", json={"decision": "approve"})
    assert resp.status_code == 400


def test_decision_rejects_invalid_decision_value(client, seed, pending_leave):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/approvals/leave_request:{pending_leave.id}/decision", json={"decision": "maybe"})
    assert resp.status_code == 400


def test_decision_malformed_id_returns_400(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/admin/approvals/not-a-valid-id/decision", json={"decision": "approve"})
    assert resp.status_code == 400


def test_decision_unknown_type_returns_404(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/admin/approvals/fees:1/decision", json={"decision": "approve"})
    assert resp.status_code == 404


def test_decision_unknown_entity_id_returns_404(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/admin/approvals/leave_request:999999/decision", json={"decision": "approve"})
    assert resp.status_code == 404


def test_decision_on_already_decided_leave_returns_400(client, seed, pending_leave):
    _override_user("admin", user_id=seed["admin_user"].id)
    assert client.post(f"/admin/approvals/leave_request:{pending_leave.id}/decision", json={"decision": "reject"}).status_code == 200
    resp = client.post(f"/admin/approvals/leave_request:{pending_leave.id}/decision", json={"decision": "reject"})
    assert resp.status_code == 400


def test_decision_writes_audit_log_entry(client, db_session, seed, pending_leave):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/approvals/leave_request:{pending_leave.id}/decision", json={"decision": "reject", "comment": "not enough notice"})
    assert resp.status_code == 200

    entry = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == "leave_requests", AuditLogEntry.entity_id == pending_leave.id, AuditLogEntry.action == "reject")
        .one()
    )
    assert entry.actor_id == seed["admin_user"].id
    assert entry.detail["comment"] == "not enough notice"


def test_decision_comment_is_persisted_on_the_leave_request(client, db_session, seed, pending_leave):
    """The comment used to be written ONLY into the audit log detail (asserted by the
    test above) - a table teachers can't read, since GET /audit/* is admin/principal
    only. It now also lands on the record the teacher can actually see."""
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        f"/admin/approvals/leave_request:{pending_leave.id}/decision",
        json={"decision": "reject", "comment": "not enough notice"},
    )
    assert resp.status_code == 200

    db_session.refresh(pending_leave)
    assert pending_leave.decision_comment == "not enough notice"


def test_decision_comment_reaches_the_teacher_via_leave_requests_endpoint(client, db_session, seed, pending_leave):
    """End-to-end visibility: the teacher who filed the request reads their own
    decision note back off GET /staff/leave_requests."""
    _override_user("admin", user_id=seed["admin_user"].id)
    assert client.post(
        f"/admin/approvals/leave_request:{pending_leave.id}/decision",
        json={"decision": "reject", "comment": "short-staffed that week"},
    ).status_code == 200

    _override_user("teacher", user_id=pending_leave.teacher_id)
    resp = client.get("/staff/leave_requests")
    assert resp.status_code == 200
    mine = next(r for r in resp.json() if r["id"] == pending_leave.id)
    assert mine["decision_comment"] == "short-staffed that week"


def test_blank_decision_comment_does_not_clobber_an_existing_note(db_session, seed, pending_leave):
    """decide_leave_request() is shared by two endpoints, only one of which sends a
    comment - the quick-approve path must not blank out a note already recorded."""
    from app.routers.staffing import decide_leave_request

    decide_leave_request(db_session, pending_leave, "rejected", seed["admin_user"].id, None, "first note")
    assert pending_leave.decision_comment == "first note"

    decide_leave_request(db_session, pending_leave, "rejected", seed["admin_user"].id, None, "   ")
    assert pending_leave.decision_comment == "first note"

    decide_leave_request(db_session, pending_leave, "rejected", seed["admin_user"].id, None, None)
    assert pending_leave.decision_comment == "first note"


# --- admission_application as 2nd real source: real HTTP-level integration ---


def test_get_admin_approvals_shows_both_leave_request_and_admission_together(client, db_session, seed, pending_leave):
    from datetime import date

    from app.models.admissions import AdmissionApplication

    application = AdmissionApplication(
        school_id=seed["school"].id, academic_year=ACADEMIC_YEAR, applicant_name="Jane Doe", dob=date(2015, 4, 1),
        guardian_email="g@example.com", grade_applied="8", status="under_review", submitted_by=seed["admin_user"].id,
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/approvals")
    assert resp.status_code == 200
    ids = {i["id"] for i in resp.json()["items"]}
    assert f"leave_request:{pending_leave.id}" in ids
    assert f"admission_application:{application.id}" in ids


def test_approve_admission_via_unified_endpoint_creates_enrollment(client, db_session, seed):
    """Same real, automatic accept pipeline (section auto-assignment + real
    student account + real guardian resolution) via the shared Approvals inbox
    entry point, not just the dedicated PATCH endpoint - decide_admission_application
    is shared, so behavior must be identical regardless of entry point."""
    import uuid as uuid_module
    from datetime import date
    from unittest.mock import patch

    from app.models.admissions import AdmissionApplication
    from app.models.document import Document
    from app.models.enrollment import Enrollment
    from app.models.parent_student import ParentStudent
    from app.models.role import Role
    from app.models.user import User

    # Accepting now hard-requires a marksheet + id_proof already linked
    # (REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE) - constructed directly here rather
    # than via the real upload/attach endpoints, matching this test's own existing
    # direct-construction style.
    marksheet = Document(uploaded_by=seed["admin_user"].id, school_id=seed["school"].id, document_type="marksheet", file_url="x", status="done")
    id_proof = Document(uploaded_by=seed["admin_user"].id, school_id=seed["school"].id, document_type="id_proof", file_url="x", status="done")
    db_session.add_all([marksheet, id_proof])
    db_session.flush()

    application = AdmissionApplication(
        school_id=seed["school"].id, academic_year=ACADEMIC_YEAR, applicant_name="Jane Doe", dob=date(2015, 4, 1),
        guardian_email="g@example.com", grade_applied="8", status="under_review", submitted_by=seed["admin_user"].id,
        ocr_document_ids=[marksheet.id, id_proof.id],
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    with patch("app.routers.admissions.create_auth_account", side_effect=lambda **kwargs: uuid_module.uuid4()):
        resp = client.post(f"/admin/approvals/admission_application:{application.id}/decision", json={"decision": "approve"})
    assert resp.status_code == 200
    assert resp.json() == {"id": f"admission_application:{application.id}", "status": "accepted"}

    db_session.refresh(application)
    assert application.status == "accepted"
    assert application.enrolled_student_id is not None

    student_role = db_session.query(Role).filter(Role.name == "student").one()
    student = db_session.query(User).filter(User.id == application.enrolled_student_id).one()
    assert student.role_id == student_role.id
    assert student.full_name == "Jane Doe"

    enrollment = (
        db_session.query(Enrollment)
        .filter(Enrollment.student_id == student.id, Enrollment.class_id == seed["class"].id)
        .one()
    )
    assert enrollment.is_primary is True

    parent_role = db_session.query(Role).filter(Role.name == "parent").one()
    parent = db_session.query(User).filter(User.email == "g@example.com", User.role_id == parent_role.id).one()
    link = db_session.query(ParentStudent).filter(ParentStudent.parent_id == parent.id, ParentStudent.student_id == student.id).one_or_none()
    assert link is not None


def test_decide_admission_via_unified_endpoint_404s_for_another_schools_application(client, db_session, seed):
    """Same cross-school scoping fix as the dedicated PATCH endpoint in
    admissions.py - this is the SECOND entry point to the same decide function,
    found live to have the identical gap during this session's manual testing."""
    from datetime import date

    from app.models.admissions import AdmissionApplication

    other_school = School(name="Another School")
    db_session.add(other_school)
    db_session.commit()
    db_session.refresh(other_school)

    application = AdmissionApplication(
        school_id=seed["school"].id, academic_year=ACADEMIC_YEAR, applicant_name="Jane Doe", dob=date(2015, 4, 1),
        guardian_email="g2@example.com", grade_applied="8", status="under_review", submitted_by=seed["admin_user"].id,
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    _override_user("admin", user_id=999999, school_id=other_school.id)
    resp = client.post(f"/admin/approvals/admission_application:{application.id}/decision", json={"decision": "approve"})
    assert resp.status_code == 404
