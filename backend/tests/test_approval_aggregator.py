import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.admissions import AdmissionApplication
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest
from app.models.user import User
from app.services.approval_aggregator import (
    APPROVAL_SOURCES,
    PendingApproval,
    admission_application_approvals,
    aggregate_approvals,
    leave_request_approvals,
)

ACADEMIC_YEAR = "2026-27"


def _make_user(db_session, role_row, prefix, school):
    email = f"{prefix}-{uuid.uuid4()}@example.com"
    user = User(supabase_id=uuid.uuid4(), email=email, full_name=prefix, role_id=role_row.id, school_id=school.id)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def teacher(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    t = _make_user(db_session, teacher_role, "teacher", school)
    db_session.commit()
    return t


@pytest.fixture()
def admin(db_session):
    school = School(name="Test School 2")
    db_session.add(school)
    db_session.flush()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    a = _make_user(db_session, admin_role, "admin", school)
    db_session.commit()
    return {"school": school, "admin": a}


def _find(approvals, approval_id):
    return next(a for a in approvals if a.id == approval_id)


def test_pending_leave_request_is_a_pending_approval(db_session, teacher):
    lr = LeaveRequest(teacher_id=teacher.id, start_date=date.today(), end_date=date.today(), reason="sick", status="pending")
    db_session.add(lr)
    db_session.commit()

    approval = _find(leave_request_approvals(db_session), f"leave_request:{lr.id}")
    assert approval.type == "leave_request"
    assert approval.requested_by == teacher.id
    assert approval.entity_type == "leave_requests"
    assert approval.entity_id == lr.id
    assert approval.payload["reason"] == "sick"


def test_approved_leave_request_is_not_pending(db_session, teacher):
    lr = LeaveRequest(teacher_id=teacher.id, start_date=date.today(), end_date=date.today(), reason="sick", status="approved")
    db_session.add(lr)
    db_session.commit()

    assert f"leave_request:{lr.id}" not in {a.id for a in leave_request_approvals(db_session)}


def test_rejected_leave_request_is_not_pending(db_session, teacher):
    lr = LeaveRequest(teacher_id=teacher.id, start_date=date.today(), end_date=date.today(), reason="sick", status="rejected")
    db_session.add(lr)
    db_session.commit()

    assert f"leave_request:{lr.id}" not in {a.id for a in leave_request_approvals(db_session)}


def test_default_registry_has_leave_request_and_admission_application():
    # 2/8 sources are real, up from 1/7 last session - see approval_aggregator.py's
    # module docstring for what else was checked and ruled out.
    assert set(APPROVAL_SOURCES.keys()) == {"leave_request", "admission_application"}


# --- admission_application_approvals ---


def test_under_review_admission_is_a_pending_approval(db_session, admin):
    application = AdmissionApplication(
        school_id=admin["school"].id, academic_year=ACADEMIC_YEAR, applicant_name="Jane Doe", dob=date(2015, 4, 1),
        guardian_email="g@example.com", grade_applied="Grade 8", status="under_review", submitted_by=admin["admin"].id,
    )
    db_session.add(application)
    db_session.commit()

    approval = _find(admission_application_approvals(db_session), f"admission_application:{application.id}")
    assert approval.type == "admission_application"
    assert approval.requested_by == admin["admin"].id
    assert approval.entity_type == "admission_applications"
    assert approval.payload["applicant_name"] == "Jane Doe"


def test_submitted_admission_is_not_yet_a_pending_approval(db_session, admin):
    # "submitted" is pending TRIAGE, not pending a binary decision - see
    # approval_aggregator.py's module docstring.
    application = AdmissionApplication(
        school_id=admin["school"].id, academic_year=ACADEMIC_YEAR, applicant_name="Jane Doe", dob=date(2015, 4, 1),
        guardian_email="g@example.com", grade_applied="Grade 8", status="submitted", submitted_by=admin["admin"].id,
    )
    db_session.add(application)
    db_session.commit()

    assert f"admission_application:{application.id}" not in {a.id for a in admission_application_approvals(db_session)}


def test_accepted_admission_is_not_pending(db_session, admin):
    application = AdmissionApplication(
        school_id=admin["school"].id, academic_year=ACADEMIC_YEAR, applicant_name="Jane Doe", dob=date(2015, 4, 1),
        guardian_email="g@example.com", grade_applied="Grade 8", status="accepted", submitted_by=admin["admin"].id,
    )
    db_session.add(application)
    db_session.commit()

    assert f"admission_application:{application.id}" not in {a.id for a in admission_application_approvals(db_session)}


def test_real_registry_surfaces_both_leave_request_and_admission_together(db_session, teacher, admin):
    lr = LeaveRequest(teacher_id=teacher.id, start_date=date.today(), end_date=date.today(), reason="sick", status="pending")
    application = AdmissionApplication(
        school_id=admin["school"].id, academic_year=ACADEMIC_YEAR, applicant_name="Jane Doe", dob=date(2015, 4, 1),
        guardian_email="g@example.com", grade_applied="Grade 8", status="under_review", submitted_by=admin["admin"].id,
    )
    db_session.add_all([lr, application])
    db_session.commit()

    approvals = aggregate_approvals(db_session)  # real APPROVAL_SOURCES, not fakes
    ids = {a.id for a in approvals}
    assert f"leave_request:{lr.id}" in ids
    assert f"admission_application:{application.id}" in ids


def _fake_approval(type_: str, entity_id: int, requested_at: datetime) -> PendingApproval:
    return PendingApproval(
        id=f"{type_}:{entity_id}", type=type_, requested_by=1, requested_at=requested_at,
        payload={}, entity_type="fake", entity_id=entity_id,
    )


def test_aggregate_merges_sources_and_sorts_newest_first(db_session):
    now = datetime.now(timezone.utc)
    fake_sources = {
        "a": lambda db: [_fake_approval("a", 1, now - timedelta(days=1))],
        "b": lambda db: [_fake_approval("b", 2, now)],
    }
    approvals = aggregate_approvals(db_session, sources=fake_sources)
    assert [a.id for a in approvals] == ["b:2", "a:1"]


def test_aggregate_mechanism_works_with_injected_source(db_session):
    # Proves the pluggability claim: registering a fake "fees"-shaped source works
    # without touching aggregate_approvals itself - the same mechanism a real future
    # source (Fees, Admissions, Exam Management) would use.
    fake_sources = {"fees": lambda db: [_fake_approval("fees", 99, datetime.now(timezone.utc))]}
    approvals = aggregate_approvals(db_session, sources=fake_sources)
    assert approvals[0].type == "fees"
    assert approvals[0].id == "fees:99"
