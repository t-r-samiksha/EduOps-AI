"""Confirms hitting each of the 11 privileged endpoints wired in this session
actually creates a real AuditLogEntry - not just that write_audit_log() works in
isolation (see test_audit_log.py for that). Each test calls the real endpoint
through the real router and then queries AuditLogEntry for the resulting row,
scoped to that test's own entity id (never a global count)."""

import uuid
from datetime import date, time

import pytest

from app.main import app
from app.models.audit import AuditLogEntry
from app.models.class_ import SchoolClass
from app.models.document import Document, ExtractedEntity
from app.models.risk import RiskFlag
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest, Substitution
from app.models.subject import Subject
from app.models.syllabus import AnomalyFlag
from app.models.timetable import Room, TeacherSubject, TimetableSlot
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int = 999):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role)

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
    student_role = db_session.query(Role).filter(Role.name == "student").one()

    admin_user = _make_user(db_session, admin_role, "admin", school)
    teacher = _make_user(db_session, teacher_role, "teacher", school)
    sub_teacher = _make_user(db_session, teacher_role, "sub-teacher", school)
    student = _make_user(db_session, student_role, "student", school)

    subject = Subject(name="Math", school_id=school.id)
    db_session.add(subject)
    db_session.flush()
    room = Room(name="R1", capacity=30, room_type="classroom", school_id=school.id)
    other_room = Room(name="R2", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add_all([room, other_room])
    db_session.flush()
    school_class = SchoolClass(name="8A", academic_year=ACADEMIC_YEAR, school_id=school.id, class_teacher_id=teacher.id)
    db_session.add(school_class)
    db_session.flush()

    db_session.add(TeacherSubject(teacher_id=sub_teacher.id, subject_id=subject.id))
    slot = TimetableSlot(
        day_of_week=date.today().weekday(), period_number=0, start_time=time(8, 0), end_time=time(8, 45),
        subject_id=subject.id, teacher_id=teacher.id, class_id=school_class.id, room_id=room.id,
        academic_year=ACADEMIC_YEAR, is_active=True,
    )
    db_session.add(slot)
    db_session.commit()
    db_session.refresh(slot)

    return {
        "school": school, "class": school_class, "subject": subject, "room": room, "other_room": other_room, "slot": slot,
        "admin_user": admin_user, "teacher": teacher, "sub_teacher": sub_teacher, "student": student,
    }


def _latest_entry(db_session, entity_type: str, entity_id: int) -> AuditLogEntry:
    return (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == entity_type, AuditLogEntry.entity_id == entity_id)
        .order_by(AuditLogEntry.id.desc())
        .first()
    )


# --- 1. timetable PUT /update ---


def test_timetable_update_writes_audit_entry(client, db_session, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put("/timetable/update", json={"slot_id": seed["slot"].id, "room_id": seed["other_room"].id})
    assert resp.status_code == 200

    entry = _latest_entry(db_session, "timetable_slots", seed["slot"].id)
    assert entry is not None
    assert entry.action == "update"
    assert entry.actor_id == seed["admin_user"].id


# --- 2. attendance PUT /{id}/review ---


def test_attendance_review_writes_audit_entry(client, db_session, seed):
    from app.models.attendance import AttendanceRecord

    record = AttendanceRecord(student_id=seed["student"].id, class_id=seed["class"].id, date=date.today(), status="absent", source="manual")
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(f"/attendance/{record.id}/review", json={"status": "present"})
    assert resp.status_code == 200

    entry = _latest_entry(db_session, "attendance_records", record.id)
    assert entry is not None
    assert entry.action == "review"
    assert entry.detail["previous_status"] == "absent"
    assert entry.detail["new_status"] == "present"


# --- 3. staffing PUT /staff/approve_leave ---


def test_approve_leave_writes_audit_entry(client, db_session, seed):
    leave = LeaveRequest(teacher_id=seed["teacher"].id, start_date=date.today(), end_date=date.today(), reason="sick", status="pending")
    db_session.add(leave)
    db_session.commit()
    db_session.refresh(leave)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put("/staff/approve_leave", json={"leave_request_id": leave.id, "decision": "approved", "academic_year": ACADEMIC_YEAR})
    assert resp.status_code == 200

    entry = _latest_entry(db_session, "leave_requests", leave.id)
    assert entry is not None
    assert entry.action == "approve"


# --- 4. staffing PUT /substitution/{id}/confirm ---


def test_confirm_substitution_writes_audit_entry(client, db_session, seed):
    leave = LeaveRequest(teacher_id=seed["teacher"].id, start_date=date.today(), end_date=date.today(), reason="sick", status="approved")
    db_session.add(leave)
    db_session.flush()
    sub = Substitution(leave_request_id=leave.id, timetable_slot_id=seed["slot"].id, original_teacher_id=seed["teacher"].id, status="suggested")
    db_session.add(sub)
    db_session.commit()
    db_session.refresh(sub)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(f"/substitution/{sub.id}/confirm", json={"substitute_teacher_id": seed["sub_teacher"].id})
    assert resp.status_code == 200
    assert resp.json()["substitution"] is not None  # confirm actually succeeded, not blocked by conflicts

    entry = _latest_entry(db_session, "substitutions", sub.id)
    assert entry is not None
    assert entry.action == "confirm"


# --- 5/6/7. risk acknowledge / intervention / resolve ---


@pytest.fixture()
def risk_flag(db_session, seed):
    flag = RiskFlag(student_id=seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(flag)
    db_session.commit()
    db_session.refresh(flag)
    return flag


def test_risk_acknowledge_writes_audit_entry(client, db_session, seed, risk_flag):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(f"/risk/{risk_flag.id}/acknowledge")
    assert resp.status_code == 200

    entry = _latest_entry(db_session, "risk_flags", risk_flag.id)
    assert entry is not None
    assert entry.action == "acknowledge"


def test_risk_intervention_writes_audit_entry(client, db_session, seed, risk_flag):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/risk/{risk_flag.id}/intervention", json={"note": "Called parent", "action_taken": "called_parent"})
    assert resp.status_code == 200
    intervention_id = resp.json()["id"]

    entry = _latest_entry(db_session, "interventions", intervention_id)
    assert entry is not None
    assert entry.action == "create"
    assert entry.detail["risk_flag_id"] == risk_flag.id


def test_risk_resolve_writes_audit_entry(client, db_session, seed, risk_flag):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(f"/risk/{risk_flag.id}/resolve")
    assert resp.status_code == 200

    entry = _latest_entry(db_session, "risk_flags", risk_flag.id)
    assert entry is not None
    assert entry.action == "resolve"


# --- 8. documents PUT /entities/{id} correction ---


def test_document_correction_writes_audit_entry(client, db_session, seed):
    doc = Document(uploaded_by=seed["admin_user"].id, document_type="admission_form", file_url="x", status="done")
    db_session.add(doc)
    db_session.flush()
    entity = ExtractedEntity(document_id=doc.id, field_name="dob", field_value="2016-04-01", confidence_score=0.4, is_low_confidence=True)
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(f"/admin/ocr/documents/{doc.id}/entities/{entity.id}", json={"corrected_value": "2015-04-01"})
    assert resp.status_code == 200

    entry = _latest_entry(db_session, "extracted_entities", entity.id)
    assert entry is not None
    assert entry.action == "correct"
    assert entry.detail["previous_value"] == "2016-04-01"
    assert entry.detail["corrected_value"] == "2015-04-01"


# --- 9. syllabus PUT /admin/anomalies/{id}/resolve ---


def test_anomaly_resolve_writes_audit_entry(client, db_session, seed):
    flag = AnomalyFlag(type="teacher_overload", entity_type="users", entity_id=seed["teacher"].id, severity="normal", detail={"message": "x"}, status="open")
    db_session.add(flag)
    db_session.commit()
    db_session.refresh(flag)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(f"/admin/anomalies/{flag.id}/resolve")
    assert resp.status_code == 200

    entry = _latest_entry(db_session, "anomaly_flags", flag.id)
    assert entry is not None
    assert entry.action == "resolve"


# --- 10/11. admin_alerts POST /admin/alerts/{id}/resolve - both branches ---


def test_admin_alerts_resolve_real_status_branch_writes_audit_entry(client, db_session, seed, risk_flag):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/alerts/risk_flag:{risk_flag.id}/resolve")
    assert resp.status_code == 200

    entry = _latest_entry(db_session, "risk_flags", risk_flag.id)
    assert entry is not None
    assert entry.action == "resolve"


def test_admin_alerts_resolve_dismissal_branch_writes_audit_entry(client, db_session, seed):
    leave = LeaveRequest(teacher_id=seed["teacher"].id, start_date=date.today(), end_date=date.today(), reason="sick", status="pending")
    db_session.add(leave)
    db_session.commit()
    db_session.refresh(leave)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/alerts/leave_request:{leave.id}/resolve")
    assert resp.status_code == 200

    entry = _latest_entry(db_session, "leave_requests", leave.id)
    assert entry is not None
    assert entry.action == "dismiss_alert"
    # The underlying LeaveRequest row was NOT changed by this path - only dismissed
    # from the feed. Confirms the audit action name is honest about what happened.
    db_session.refresh(leave)
    assert leave.status == "pending"
