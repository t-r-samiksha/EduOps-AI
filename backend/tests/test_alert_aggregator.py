import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.models.attendance import AttendanceReconciliation
from app.models.class_ import SchoolClass
from app.models.document import Document, ExtractedEntity
from app.models.fees import FeeRecord, FeeSchedule
from app.models.risk import RiskFlag
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest, Substitution
from app.models.subject import Subject
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from app.services.alert_aggregator import (
    ALERT_SOURCES,
    FEE_OVERDUE_URGENT_DAYS,
    Alert,
    aggregate_alerts,
    attendance_reconciliation_alerts,
    document_failed_alerts,
    document_low_confidence_alerts,
    fee_overdue_alerts,
    leave_request_alerts,
    risk_flag_alerts,
    substitution_alerts,
    summarize_alerts,
)

ACADEMIC_YEAR = "2026-27"


def _make_user(db_session, role_row, prefix, school):
    email = f"{prefix}-{uuid.uuid4()}@example.com"
    user = User(supabase_id=uuid.uuid4(), email=email, full_name=prefix, role_id=role_row.id, school_id=school.id)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def base(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()

    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    teacher = _make_user(db_session, teacher_role, "teacher", school)
    student = _make_user(db_session, student_role, "student", school)
    db_session.commit()

    return {"school": school, "admin_user": admin_user, "teacher": teacher, "student": student}


# --- risk_flag_alerts ---


# These source functions correctly aggregate globally with no school-scoping (same
# documented simplification as routers/risk.py and staffing.py), so a live DB with
# real leftover rows from earlier sessions means these tests must find their own
# alert by composite id rather than assume the table is empty or has exactly N rows.


def _find(alerts, alert_id):
    return next(a for a in alerts if a.id == alert_id)


def test_risk_flag_high_open_is_urgent(db_session, base):
    flag = RiskFlag(student_id=base["student"].id, risk_level="high", score=0.8, reasons=["bad attendance"], status="open")
    db_session.add(flag)
    db_session.commit()

    alert = _find(risk_flag_alerts(db_session), f"risk_flag:{flag.id}")
    assert alert.severity == "urgent"
    assert alert.entity_type == "risk_flags"
    assert alert.entity_id == flag.id


def test_risk_flag_medium_open_is_normal(db_session, base):
    flag = RiskFlag(student_id=base["student"].id, risk_level="medium", score=0.5, reasons=["x"], status="open")
    db_session.add(flag)
    db_session.commit()

    assert _find(risk_flag_alerts(db_session), f"risk_flag:{flag.id}").severity == "normal"


def test_risk_flag_high_acknowledged_is_downgraded_to_normal(db_session, base):
    flag = RiskFlag(student_id=base["student"].id, risk_level="high", score=0.8, reasons=["x"], status="acknowledged")
    db_session.add(flag)
    db_session.commit()

    assert _find(risk_flag_alerts(db_session), f"risk_flag:{flag.id}").severity == "normal"


def test_risk_flag_resolved_is_excluded(db_session, base):
    flag = RiskFlag(student_id=base["student"].id, risk_level="high", score=0.8, reasons=["x"], status="resolved")
    db_session.add(flag)
    db_session.commit()

    assert f"risk_flag:{flag.id}" not in {a.id for a in risk_flag_alerts(db_session)}


# --- leave_request_alerts ---


def test_pending_leave_request_is_normal(db_session, base):
    lr = LeaveRequest(teacher_id=base["teacher"].id, start_date=date.today(), end_date=date.today(), reason="sick", status="pending")
    db_session.add(lr)
    db_session.commit()

    assert _find(leave_request_alerts(db_session), f"leave_request:{lr.id}").severity == "normal"


def test_approved_leave_request_is_excluded(db_session, base):
    lr = LeaveRequest(teacher_id=base["teacher"].id, start_date=date.today(), end_date=date.today(), reason="sick", status="approved")
    db_session.add(lr)
    db_session.commit()

    assert f"leave_request:{lr.id}" not in {a.id for a in leave_request_alerts(db_session)}


# --- substitution_alerts ---


@pytest.fixture()
def slot(db_session, base):
    subject = Subject(name="Math", school_id=base["school"].id)
    room = Room(name="R1", capacity=30, room_type="classroom", school_id=base["school"].id)
    db_session.add_all([subject, room])
    db_session.flush()

    school_class = SchoolClass(name="8A", academic_year=ACADEMIC_YEAR, school_id=base["school"].id, class_teacher_id=base["teacher"].id)
    db_session.add(school_class)
    db_session.flush()

    ts = TimetableSlot(
        day_of_week=0, period_number=0, start_time=time(8, 0), end_time=time(8, 45),
        subject_id=subject.id, teacher_id=base["teacher"].id, class_id=school_class.id, room_id=room.id,
        academic_year=ACADEMIC_YEAR, is_active=True,
    )
    db_session.add(ts)
    db_session.commit()
    db_session.refresh(ts)
    return ts


def test_substitution_far_from_leave_start_is_normal(db_session, base, slot):
    lr = LeaveRequest(teacher_id=base["teacher"].id, start_date=date.today() + timedelta(days=30), end_date=date.today() + timedelta(days=31), reason="x", status="approved")
    db_session.add(lr)
    db_session.flush()
    sub = Substitution(leave_request_id=lr.id, timetable_slot_id=slot.id, original_teacher_id=base["teacher"].id, status="suggested")
    db_session.add(sub)
    db_session.commit()

    assert _find(substitution_alerts(db_session), f"substitution:{sub.id}").severity == "normal"


def test_substitution_close_to_leave_start_is_urgent(db_session, base, slot):
    lr = LeaveRequest(teacher_id=base["teacher"].id, start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2), reason="x", status="approved")
    db_session.add(lr)
    db_session.flush()
    sub = Substitution(leave_request_id=lr.id, timetable_slot_id=slot.id, original_teacher_id=base["teacher"].id, status="suggested")
    db_session.add(sub)
    db_session.commit()

    assert _find(substitution_alerts(db_session), f"substitution:{sub.id}").severity == "urgent"


def test_confirmed_substitution_is_excluded(db_session, base, slot):
    lr = LeaveRequest(teacher_id=base["teacher"].id, start_date=date.today(), end_date=date.today(), reason="x", status="approved")
    db_session.add(lr)
    db_session.flush()
    sub = Substitution(leave_request_id=lr.id, timetable_slot_id=slot.id, original_teacher_id=base["teacher"].id, substitute_teacher_id=base["teacher"].id, status="confirmed")
    db_session.add(sub)
    db_session.commit()

    assert f"substitution:{sub.id}" not in {a.id for a in substitution_alerts(db_session)}


# --- document alerts ---


def test_failed_document_is_urgent(db_session, base):
    doc = Document(uploaded_by=base["admin_user"].id, document_type="admission_form", file_url="x", status="failed", processed_at=datetime.now(timezone.utc))
    db_session.add(doc)
    db_session.commit()

    alert = _find(document_failed_alerts(db_session), f"document_failed:{doc.id}")
    assert alert.severity == "urgent"
    assert alert.entity_type == "documents"


def test_done_document_is_excluded_from_failed_alerts(db_session, base):
    doc = Document(uploaded_by=base["admin_user"].id, document_type="admission_form", file_url="x", status="done")
    db_session.add(doc)
    db_session.commit()

    assert f"document_failed:{doc.id}" not in {a.id for a in document_failed_alerts(db_session)}


def test_document_with_uncorrected_low_confidence_field_alerts_once_per_document(db_session, base):
    doc = Document(uploaded_by=base["admin_user"].id, document_type="admission_form", file_url="x", status="done")
    db_session.add(doc)
    db_session.flush()
    db_session.add_all(
        [
            ExtractedEntity(document_id=doc.id, field_name="dob", field_value="2016-04-01", confidence_score=0.4, is_low_confidence=True),
            ExtractedEntity(document_id=doc.id, field_name="name", field_value="X", confidence_score=0.3, is_low_confidence=True),
        ]
    )
    db_session.commit()

    alerts = document_low_confidence_alerts(db_session)
    matches = [a for a in alerts if a.id == f"document_low_confidence:{doc.id}"]
    assert len(matches) == 1  # one per document, not per field (two low-confidence fields above)
    assert matches[0].severity == "normal"


def test_corrected_low_confidence_field_does_not_alert(db_session, base):
    doc = Document(uploaded_by=base["admin_user"].id, document_type="admission_form", file_url="x", status="done")
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        ExtractedEntity(document_id=doc.id, field_name="dob", field_value="2016-04-01", confidence_score=0.4, is_low_confidence=True, corrected_value="2015-04-01")
    )
    db_session.commit()

    assert f"document_low_confidence:{doc.id}" not in {a.id for a in document_low_confidence_alerts(db_session)}


def test_high_confidence_field_does_not_alert(db_session, base):
    doc = Document(uploaded_by=base["admin_user"].id, document_type="admission_form", file_url="x", status="done")
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        ExtractedEntity(document_id=doc.id, field_name="dob", field_value="2015-04-01", confidence_score=0.95, is_low_confidence=False)
    )
    db_session.commit()

    assert f"document_low_confidence:{doc.id}" not in {a.id for a in document_low_confidence_alerts(db_session)}


# --- attendance_reconciliation_alerts ---


def test_pending_reconciliation_is_normal(db_session, base, slot):
    row = AttendanceReconciliation(student_id=base["student"].id, timetable_slot_id=slot.id, date=date.today(), reason="cv_only", status="pending")
    db_session.add(row)
    db_session.commit()

    assert _find(attendance_reconciliation_alerts(db_session), f"attendance_reconciliation:{row.id}").severity == "normal"


def test_no_reconciliation_rows_is_empty_by_default(db_session, base):
    # Documents the honest expectation from alert_aggregator.py's docstring: nothing
    # populates this table yet (no RFID ingestion/reconciliation job exists), so this
    # source is expected to return [] in production today.
    assert attendance_reconciliation_alerts(db_session) == []


# --- aggregate_alerts / summarize_alerts (the mechanism, via fake sources) ---


def _fake_alert(source: str, entity_id: int, severity: str, created_at: datetime) -> Alert:
    return Alert(
        id=f"{source}:{entity_id}", source=source, severity=severity, title="t", message="m",
        entity_type="fake", entity_id=entity_id, created_at=created_at, resolved=False,
    )


def test_aggregate_merges_all_sources_and_sorts_newest_first(db_session):
    now = datetime.now(timezone.utc)
    fake_sources = {
        "a": lambda db: [_fake_alert("a", 1, "normal", now - timedelta(days=1))],
        "b": lambda db: [_fake_alert("b", 2, "urgent", now)],
    }
    alerts = aggregate_alerts(db_session, sources=fake_sources)
    assert [a.id for a in alerts] == ["b:2", "a:1"]


def test_aggregate_filters_dismissed_ids(db_session):
    now = datetime.now(timezone.utc)
    fake_sources = {"a": lambda db: [_fake_alert("a", 1, "normal", now), _fake_alert("a", 2, "normal", now)]}
    alerts = aggregate_alerts(db_session, sources=fake_sources, dismissed_ids={"a:1"})
    assert [a.id for a in alerts] == ["a:2"]


def test_aggregate_filters_by_since(db_session):
    now = datetime.now(timezone.utc)
    fake_sources = {"a": lambda db: [_fake_alert("a", 1, "normal", now - timedelta(days=10)), _fake_alert("a", 2, "normal", now)]}
    alerts = aggregate_alerts(db_session, sources=fake_sources, since=now - timedelta(days=1))
    assert [a.id for a in alerts] == ["a:2"]


def test_aggregate_filters_by_severity(db_session):
    now = datetime.now(timezone.utc)
    fake_sources = {"a": lambda db: [_fake_alert("a", 1, "normal", now), _fake_alert("a", 2, "urgent", now)]}
    alerts = aggregate_alerts(db_session, sources=fake_sources, severity="urgent")
    assert [a.id for a in alerts] == ["a:2"]


def test_summarize_counts_by_severity_and_source():
    now = datetime.now(timezone.utc)
    alerts = [
        _fake_alert("risk_flag", 1, "urgent", now),
        _fake_alert("risk_flag", 2, "normal", now),
        _fake_alert("leave_request", 3, "normal", now),
    ]
    summary = summarize_alerts(alerts)
    assert summary["total"] == 3
    assert summary["by_severity"] == {"normal": 2, "urgent": 1}
    assert summary["by_source"] == {"risk_flag": 2, "leave_request": 1}


def test_summarize_empty_list():
    summary = summarize_alerts([])
    assert summary["total"] == 0
    assert summary["by_severity"] == {"normal": 0, "urgent": 0}
    assert summary["by_source"] == {}


def test_registry_has_eight_sources_including_fee_overdue():
    assert set(ALERT_SOURCES.keys()) == {
        "risk_flag", "leave_request", "substitution", "document_failed",
        "document_low_confidence", "attendance_reconciliation", "anomaly_flag", "fee_overdue",
    }


# --- fee_overdue_alerts (8th source) ---


def test_recently_overdue_fee_is_normal_severity(db_session, base):
    schedule = FeeSchedule(school_id=base["school"].id, academic_year=ACADEMIC_YEAR, fee_type="tuition", amount=15000.0, due_date=date.today() - timedelta(days=5))
    db_session.add(schedule)
    db_session.flush()
    record = FeeRecord(student_id=base["student"].id, fee_schedule_id=schedule.id, amount_due=15000.0, amount_paid=0.0, status="overdue", due_date=schedule.due_date)
    db_session.add(record)
    db_session.commit()

    alert = _find(fee_overdue_alerts(db_session, today=date.today()), f"fee_overdue:{record.id}")
    assert alert.severity == "normal"
    assert alert.entity_type == "fee_records"
    assert alert.entity_id == record.id
    assert str(base["student"].id) in alert.message


def test_severely_overdue_fee_is_urgent(db_session, base):
    schedule = FeeSchedule(school_id=base["school"].id, academic_year=ACADEMIC_YEAR, fee_type="tuition", amount=15000.0, due_date=date.today() - timedelta(days=FEE_OVERDUE_URGENT_DAYS))
    db_session.add(schedule)
    db_session.flush()
    record = FeeRecord(student_id=base["student"].id, fee_schedule_id=schedule.id, amount_due=15000.0, amount_paid=5000.0, status="overdue", due_date=schedule.due_date)
    db_session.add(record)
    db_session.commit()

    alert = _find(fee_overdue_alerts(db_session, today=date.today()), f"fee_overdue:{record.id}")
    assert alert.severity == "urgent"


def test_paid_fee_record_is_not_an_alert(db_session, base):
    schedule = FeeSchedule(school_id=base["school"].id, academic_year=ACADEMIC_YEAR, fee_type="tuition", amount=15000.0, due_date=date.today() - timedelta(days=10))
    db_session.add(schedule)
    db_session.flush()
    record = FeeRecord(student_id=base["student"].id, fee_schedule_id=schedule.id, amount_due=15000.0, amount_paid=15000.0, status="paid", due_date=schedule.due_date)
    db_session.add(record)
    db_session.commit()

    assert f"fee_overdue:{record.id}" not in {a.id for a in fee_overdue_alerts(db_session)}


def test_pending_not_yet_due_fee_record_is_not_an_alert(db_session, base):
    schedule = FeeSchedule(school_id=base["school"].id, academic_year=ACADEMIC_YEAR, fee_type="tuition", amount=15000.0, due_date=date.today() + timedelta(days=10))
    db_session.add(schedule)
    db_session.flush()
    record = FeeRecord(student_id=base["student"].id, fee_schedule_id=schedule.id, amount_due=15000.0, amount_paid=0.0, status="pending", due_date=schedule.due_date)
    db_session.add(record)
    db_session.commit()

    assert f"fee_overdue:{record.id}" not in {a.id for a in fee_overdue_alerts(db_session)}


def test_real_registry_surfaces_a_real_overdue_fee(db_session, base):
    schedule = FeeSchedule(school_id=base["school"].id, academic_year=ACADEMIC_YEAR, fee_type="tuition", amount=15000.0, due_date=date.today() - timedelta(days=5))
    db_session.add(schedule)
    db_session.flush()
    record = FeeRecord(student_id=base["student"].id, fee_schedule_id=schedule.id, amount_due=15000.0, amount_paid=0.0, status="overdue", due_date=schedule.due_date)
    db_session.add(record)
    db_session.commit()

    alerts = aggregate_alerts(db_session)  # real ALERT_SOURCES, not fakes
    assert f"fee_overdue:{record.id}" in {a.id for a in alerts}
