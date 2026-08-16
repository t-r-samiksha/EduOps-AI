import uuid
from datetime import date, timedelta

import pytest

from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.fees import FeeRecord, FeeReminder, FeeSchedule
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from scripts.run_monthly_fee_invoicing import generate_fee_records_for_schedule, run_monthly_invoicing

ACADEMIC_YEAR = "2026-27"


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

    student_role = db_session.query(Role).filter(Role.name == "student").one()
    student1 = _make_user(db_session, student_role, "s1", school)
    student2 = _make_user(db_session, student_role, "s2", school)

    school_class = SchoolClass(name="8A", academic_year=ACADEMIC_YEAR, school_id=school.id)
    db_session.add(school_class)
    db_session.flush()

    db_session.add_all(
        [
            Enrollment(student_id=student1.id, class_id=school_class.id, subject_id=None, is_primary=True),
            Enrollment(student_id=student2.id, class_id=school_class.id, subject_id=None, is_primary=True),
        ]
    )
    db_session.commit()

    return {"school": school, "class": school_class, "student1": student1, "student2": student2}


def test_generates_one_fee_record_per_enrolled_student(db_session, seed):
    schedule = FeeSchedule(
        school_id=seed["school"].id, class_id=seed["class"].id, academic_year=ACADEMIC_YEAR,
        fee_type="tuition", amount=15000.0, due_date=date.today() + timedelta(days=30),
    )
    db_session.add(schedule)
    db_session.commit()

    summary = run_monthly_invoicing(db_session, seed["school"].id, ACADEMIC_YEAR)
    assert summary["records_created"] == 2

    records = db_session.query(FeeRecord).filter(FeeRecord.fee_schedule_id == schedule.id).all()
    assert {r.student_id for r in records} == {seed["student1"].id, seed["student2"].id}
    assert all(r.amount_due == 15000.0 and r.status == "pending" for r in records)


def test_rerunning_does_not_create_duplicate_records(db_session, seed):
    schedule = FeeSchedule(
        school_id=seed["school"].id, class_id=seed["class"].id, academic_year=ACADEMIC_YEAR,
        fee_type="tuition", amount=15000.0, due_date=date.today() + timedelta(days=30),
    )
    db_session.add(schedule)
    db_session.commit()

    run_monthly_invoicing(db_session, seed["school"].id, ACADEMIC_YEAR)
    summary2 = run_monthly_invoicing(db_session, seed["school"].id, ACADEMIC_YEAR)
    assert summary2["records_created"] == 0

    records = db_session.query(FeeRecord).filter(FeeRecord.fee_schedule_id == schedule.id).all()
    assert len(records) == 2


def test_school_wide_schedule_applies_to_every_enrolled_student(db_session, seed):
    schedule = FeeSchedule(
        school_id=seed["school"].id, class_id=None, academic_year=ACADEMIC_YEAR,
        fee_type="transport", amount=2000.0, due_date=date.today() + timedelta(days=30),
    )
    db_session.add(schedule)
    db_session.commit()

    run_monthly_invoicing(db_session, seed["school"].id, ACADEMIC_YEAR)
    records = db_session.query(FeeRecord).filter(FeeRecord.fee_schedule_id == schedule.id).all()
    assert {r.student_id for r in records} == {seed["student1"].id, seed["student2"].id}


def test_past_due_pending_record_is_marked_overdue(db_session, seed):
    schedule = FeeSchedule(
        school_id=seed["school"].id, class_id=seed["class"].id, academic_year=ACADEMIC_YEAR,
        fee_type="tuition", amount=15000.0, due_date=date.today() - timedelta(days=10),
    )
    db_session.add(schedule)
    db_session.commit()

    summary = run_monthly_invoicing(db_session, seed["school"].id, ACADEMIC_YEAR)
    assert summary["overdue_marked"] == 2

    records = db_session.query(FeeRecord).filter(FeeRecord.fee_schedule_id == schedule.id).all()
    assert all(r.status == "overdue" for r in records)


def test_overdue_record_gets_a_reminder_logged(db_session, seed):
    schedule = FeeSchedule(
        school_id=seed["school"].id, class_id=seed["class"].id, academic_year=ACADEMIC_YEAR,
        fee_type="tuition", amount=15000.0, due_date=date.today() - timedelta(days=8),
    )
    db_session.add(schedule)
    db_session.commit()

    summary = run_monthly_invoicing(db_session, seed["school"].id, ACADEMIC_YEAR)
    assert summary["reminders_sent"] == 2

    reminders = (
        db_session.query(FeeReminder)
        .join(FeeRecord, FeeReminder.fee_record_id == FeeRecord.id)
        .filter(FeeRecord.fee_schedule_id == schedule.id)
        .all()
    )
    assert len(reminders) == 2
    assert all(r.sent_at is None for r in reminders)  # stub - no email infra exists
    assert all("7 days overdue" in r.cadence_reason for r in reminders)


def test_rerunning_does_not_duplicate_the_same_reminder_tier(db_session, seed):
    schedule = FeeSchedule(
        school_id=seed["school"].id, class_id=seed["class"].id, academic_year=ACADEMIC_YEAR,
        fee_type="tuition", amount=15000.0, due_date=date.today() - timedelta(days=8),
    )
    db_session.add(schedule)
    db_session.commit()

    run_monthly_invoicing(db_session, seed["school"].id, ACADEMIC_YEAR)
    summary2 = run_monthly_invoicing(db_session, seed["school"].id, ACADEMIC_YEAR)
    assert summary2["reminders_sent"] == 0  # same tier, already sent

    reminders = (
        db_session.query(FeeReminder)
        .join(FeeRecord, FeeReminder.fee_record_id == FeeRecord.id)
        .filter(FeeRecord.fee_schedule_id == schedule.id)
        .all()
    )
    assert len(reminders) == 2  # still just one per student, not four


# --- generate_only_due_within_days (auto-generate window) --------------------


def test_due_within_days_skips_a_schedule_due_far_in_the_future(db_session, seed):
    schedule = FeeSchedule(
        school_id=seed["school"].id, class_id=seed["class"].id, academic_year=ACADEMIC_YEAR,
        fee_type="tuition", amount=15000.0, due_date=date.today() + timedelta(days=60),
    )
    db_session.add(schedule)
    db_session.commit()

    summary = run_monthly_invoicing(db_session, seed["school"].id, ACADEMIC_YEAR, generate_only_due_within_days=7)
    assert summary["records_created"] == 0
    assert db_session.query(FeeRecord).filter(FeeRecord.fee_schedule_id == schedule.id).count() == 0


def test_due_within_days_still_generates_a_schedule_due_soon(db_session, seed):
    schedule = FeeSchedule(
        school_id=seed["school"].id, class_id=seed["class"].id, academic_year=ACADEMIC_YEAR,
        fee_type="tuition", amount=15000.0, due_date=date.today() + timedelta(days=3),
    )
    db_session.add(schedule)
    db_session.commit()

    summary = run_monthly_invoicing(db_session, seed["school"].id, ACADEMIC_YEAR, generate_only_due_within_days=7)
    assert summary["records_created"] == 2


def test_due_within_days_still_generates_an_already_overdue_schedule(db_session, seed):
    """A schedule already past due is obviously "within" any forward-looking
    window - must not be skipped just because it's negative days away."""
    schedule = FeeSchedule(
        school_id=seed["school"].id, class_id=seed["class"].id, academic_year=ACADEMIC_YEAR,
        fee_type="tuition", amount=15000.0, due_date=date.today() - timedelta(days=5),
    )
    db_session.add(schedule)
    db_session.commit()

    summary = run_monthly_invoicing(db_session, seed["school"].id, ACADEMIC_YEAR, generate_only_due_within_days=7)
    assert summary["records_created"] == 2


def test_generate_fee_records_for_schedule_ignores_the_window_entirely(db_session, seed):
    """The per-schedule manual override always generates, regardless of how
    far out due_date is - there's no gating parameter to even pass."""
    schedule = FeeSchedule(
        school_id=seed["school"].id, class_id=seed["class"].id, academic_year=ACADEMIC_YEAR,
        fee_type="tuition", amount=15000.0, due_date=date.today() + timedelta(days=90),
    )
    db_session.add(schedule)
    db_session.commit()

    created = generate_fee_records_for_schedule(db_session, schedule)
    assert created == 2
    assert db_session.query(FeeRecord).filter(FeeRecord.fee_schedule_id == schedule.id).count() == 2
