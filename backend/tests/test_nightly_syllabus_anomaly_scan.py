import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.models.attendance import AttendanceRecord
from app.models.class_ import SchoolClass
from app.models.document import Document
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.syllabus import AnomalyFlag, SyllabusCheckpoint, SyllabusPlan
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from scripts.run_nightly_syllabus_anomaly_scan import run_scan

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

    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    overloaded_teacher = _make_user(db_session, teacher_role, "overloaded", school)
    teacher2 = _make_user(db_session, teacher_role, "t2", school)
    teacher3 = _make_user(db_session, teacher_role, "t3", school)

    subject = Subject(name="Math", school_id=school.id)
    other_subject = Subject(name="Science", school_id=school.id)
    db_session.add_all([subject, other_subject])
    db_session.flush()

    room = Room(name="R1", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add(room)
    db_session.flush()

    school_class = SchoolClass(name="8A", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=overloaded_teacher.id)
    db_session.add(school_class)
    db_session.flush()

    # overloaded_teacher: 8 active slots. teacher2/teacher3: 1 each. Fallback-rule
    # path (few teachers) is what this test exercises - the model path itself is
    # covered by test_anomaly_detector.py's own unit tests.
    slots = []
    for i in range(8):
        slots.append(
            TimetableSlot(
                day_of_week=i % 5, period_number=i // 5, start_time=time(8, 0), end_time=time(8, 45),
                subject_id=subject.id, teacher_id=overloaded_teacher.id, class_id=school_class.id, room_id=room.id,
                academic_year=ACADEMIC_YEAR, is_active=True,
            )
        )
    slots.append(
        TimetableSlot(
            day_of_week=0, period_number=5, start_time=time(13, 0), end_time=time(13, 45),
            subject_id=other_subject.id, teacher_id=teacher2.id, class_id=school_class.id, room_id=room.id,
            academic_year=ACADEMIC_YEAR, is_active=True,
        )
    )
    slots.append(
        TimetableSlot(
            day_of_week=1, period_number=5, start_time=time(13, 0), end_time=time(13, 45),
            subject_id=other_subject.id, teacher_id=teacher3.id, class_id=school_class.id, room_id=room.id,
            academic_year=ACADEMIC_YEAR, is_active=True,
        )
    )
    db_session.add_all(slots)
    db_session.commit()

    return {
        "school": school, "class": school_class, "subject": subject, "other_subject": other_subject,
        "admin_user": admin_user, "overloaded_teacher": overloaded_teacher, "teacher2": teacher2, "teacher3": teacher3,
    }


def test_scan_flags_syllabus_drift(db_session, seed):
    today = date.today()
    term_start = today - timedelta(days=35)
    term_end = today + timedelta(days=35)  # 70-day term, 35 elapsed -> expected=0.5
    plan = SyllabusPlan(
        class_id=seed["class"].id, subject_id=seed["subject"].id, academic_year=ACADEMIC_YEAR,
        total_units=10, term_start_date=term_start, term_end_date=term_end, created_by=seed["admin_user"].id,
    )
    db_session.add(plan)
    db_session.flush()
    db_session.add(SyllabusCheckpoint(plan_id=plan.id, topic_label="Topic 1", sequence_number=1, logged_by=seed["admin_user"].id))
    db_session.commit()
    db_session.refresh(plan)

    summary = run_scan(db_session, seed["school"].id, ACADEMIC_YEAR)
    assert summary["flags_created"] >= 1

    flag = (
        db_session.query(AnomalyFlag)
        .filter(AnomalyFlag.type == "syllabus_drift", AnomalyFlag.entity_type == "syllabus_plans", AnomalyFlag.entity_id == plan.id)
        .one()
    )
    assert flag.status == "open"
    assert flag.detail["actual_fraction"] == 0.1
    assert "message" in flag.detail


def test_scan_flags_teacher_overload(db_session, seed):
    run_scan(db_session, seed["school"].id, ACADEMIC_YEAR)

    flag = (
        db_session.query(AnomalyFlag)
        .filter(AnomalyFlag.type == "teacher_overload", AnomalyFlag.entity_id == seed["overloaded_teacher"].id)
        .one()
    )
    assert flag.status == "open"
    assert flag.detail["periods_per_week"] == 8

    # teacher2/teacher3 (1 period each) must NOT be flagged.
    assert (
        db_session.query(AnomalyFlag)
        .filter(AnomalyFlag.type == "teacher_overload", AnomalyFlag.entity_id.in_([seed["teacher2"].id, seed["teacher3"].id]))
        .count()
        == 0
    )


def test_scan_flags_document_backlog(db_session, seed):
    stuck_doc = Document(uploaded_by=seed["admin_user"].id, document_type="admission_form", file_url="x", status="queued")
    db_session.add(stuck_doc)
    db_session.flush()
    stuck_doc.uploaded_at = datetime.now(timezone.utc) - timedelta(hours=48)
    db_session.commit()
    db_session.refresh(stuck_doc)

    run_scan(db_session, seed["school"].id, ACADEMIC_YEAR)

    flag = (
        db_session.query(AnomalyFlag)
        .filter(AnomalyFlag.type == "document_backlog", AnomalyFlag.entity_id == stuck_doc.id)
        .one()
    )
    assert flag.status == "open"


def test_scan_flags_attendance_drop(db_session, seed):
    today = date.today()
    baseline_start = today - timedelta(days=30)
    recent_start = today - timedelta(days=7)

    # Baseline window: high attendance.
    for i in range(20):
        db_session.add(
            AttendanceRecord(
                student_id=seed["admin_user"].id, class_id=seed["class"].id,
                date=baseline_start + timedelta(days=i), status="present", source="manual",
            )
        )
    # Recent window: attendance has dropped sharply.
    for i in range(7):
        db_session.add(
            AttendanceRecord(
                student_id=seed["admin_user"].id, class_id=seed["class"].id,
                date=recent_start + timedelta(days=i), status="absent" if i % 2 == 0 else "present", source="manual",
            )
        )
    db_session.commit()

    run_scan(db_session, seed["school"].id, ACADEMIC_YEAR)

    flag = (
        db_session.query(AnomalyFlag)
        .filter(AnomalyFlag.type == "attendance_drop", AnomalyFlag.entity_id == seed["class"].id)
        .one()
    )
    assert flag.status == "open"


def test_rerunning_scan_updates_existing_open_flag_not_duplicates(db_session, seed):
    run_scan(db_session, seed["school"].id, ACADEMIC_YEAR)
    first_count = (
        db_session.query(AnomalyFlag)
        .filter(AnomalyFlag.type == "teacher_overload", AnomalyFlag.entity_id == seed["overloaded_teacher"].id)
        .count()
    )
    assert first_count == 1

    summary2 = run_scan(db_session, seed["school"].id, ACADEMIC_YEAR)
    assert summary2["flags_updated"] >= 1

    second_count = (
        db_session.query(AnomalyFlag)
        .filter(AnomalyFlag.type == "teacher_overload", AnomalyFlag.entity_id == seed["overloaded_teacher"].id)
        .count()
    )
    assert second_count == 1  # still just one open flag, not two


def test_scan_never_produces_submission_rate_flags(db_session, seed):
    # No Person B submissions table exists (see anomaly_detector.py's module
    # docstring) - run_scan() never imports detect_low_submission_rates at all, so no
    # submission_rate AnomalyFlag can ever be created by this script today. A
    # structural check (not a DB count, per this session's test-isolation rule) - the
    # function genuinely isn't in this module's namespace to be called.
    import scripts.run_nightly_syllabus_anomaly_scan as scan_module

    assert not hasattr(scan_module, "detect_low_submission_rates")
    run_scan(db_session, seed["school"].id, ACADEMIC_YEAR)  # completes cleanly regardless
