import uuid
from datetime import date, timedelta

import pytest

from app.models.attendance import AttendanceRecord
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.risk import RemarkStub, RiskFlag
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from scripts.run_nightly_risk_scoring import run_nightly_scoring

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

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()

    teacher = _make_user(db_session, teacher_role, "teacher", school)
    at_risk_student = _make_user(db_session, student_role, "at-risk", school)
    healthy_student = _make_user(db_session, student_role, "healthy", school)

    school_class = SchoolClass(name="Grade 8 - A", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=teacher.id)
    db_session.add(school_class)
    db_session.flush()

    db_session.add_all(
        [
            Enrollment(student_id=at_risk_student.id, class_id=school_class.id, subject_id=None, is_primary=True),
            Enrollment(student_id=healthy_student.id, class_id=school_class.id, subject_id=None, is_primary=True),
        ]
    )

    today = date.today()
    for i in range(20):
        record_date = today - timedelta(days=i + 1)
        # at_risk: mostly absent. healthy: mostly present.
        db_session.add(
            AttendanceRecord(
                student_id=at_risk_student.id,
                class_id=school_class.id,
                date=record_date,
                status="absent" if i % 5 != 4 else "present",
                source="manual",
            )
        )
        db_session.add(
            AttendanceRecord(
                student_id=healthy_student.id,
                class_id=school_class.id,
                date=record_date,
                status="present" if i % 10 != 0 else "absent",
                source="manual",
            )
        )

    db_session.add(
        RemarkStub(
            student_id=at_risk_student.id,
            teacher_id=teacher.id,
            remark_text="Struggling badly, failing to keep up, seems miserable and hopeless.",
        )
    )

    db_session.commit()

    return {"school": school, "class": school_class, "teacher": teacher, "at_risk": at_risk_student, "healthy": healthy_student}


def test_nightly_scoring_flags_at_risk_student_not_healthy_one(db_session, seed):
    summary = run_nightly_scoring(db_session, seed["school"].id, ACADEMIC_YEAR)

    assert summary["students_scored"] == 2
    assert summary["flags_created"] == 1
    assert summary["low_risk_skipped"] == 1

    flags = db_session.query(RiskFlag).filter(RiskFlag.student_id == seed["at_risk"].id).all()
    assert len(flags) == 1
    assert flags[0].risk_level in ("medium", "high")
    assert flags[0].status == "open"

    healthy_flags = db_session.query(RiskFlag).filter(RiskFlag.student_id == seed["healthy"].id).all()
    assert healthy_flags == []


def test_rerunning_updates_existing_open_flag_not_duplicates(db_session, seed):
    run_nightly_scoring(db_session, seed["school"].id, ACADEMIC_YEAR)
    first_flags = db_session.query(RiskFlag).filter(RiskFlag.student_id == seed["at_risk"].id).all()
    assert len(first_flags) == 1
    first_id = first_flags[0].id

    summary2 = run_nightly_scoring(db_session, seed["school"].id, ACADEMIC_YEAR)
    assert summary2["flags_created"] == 0
    assert summary2["flags_updated"] == 1

    flags = db_session.query(RiskFlag).filter(RiskFlag.student_id == seed["at_risk"].id).all()
    assert len(flags) == 1
    assert flags[0].id == first_id


def test_resolved_flag_does_not_block_a_fresh_flag_on_recurrence(db_session, seed):
    run_nightly_scoring(db_session, seed["school"].id, ACADEMIC_YEAR)
    flag = db_session.query(RiskFlag).filter(RiskFlag.student_id == seed["at_risk"].id).one()
    flag.status = "resolved"
    flag.resolved_by = seed["teacher"].id
    db_session.commit()

    summary = run_nightly_scoring(db_session, seed["school"].id, ACADEMIC_YEAR)
    assert summary["flags_created"] == 1  # a new flag, the resolved one is left alone

    flags = db_session.query(RiskFlag).filter(RiskFlag.student_id == seed["at_risk"].id).all()
    assert len(flags) == 2
    statuses = {f.status for f in flags}
    assert statuses == {"resolved", "open"}


def test_student_with_no_attendance_records_is_not_flagged(db_session, seed):
    # A third student with an enrollment but zero AttendanceRecord rows at all.
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    no_data_student = _make_user(db_session, student_role, "no-data", seed["school"])
    db_session.add(Enrollment(student_id=no_data_student.id, class_id=seed["class"].id, subject_id=None, is_primary=True))
    db_session.commit()

    summary = run_nightly_scoring(db_session, seed["school"].id, ACADEMIC_YEAR)
    assert summary["students_scored"] == 3

    flags = db_session.query(RiskFlag).filter(RiskFlag.student_id == no_data_student.id).all()
    assert flags == []
