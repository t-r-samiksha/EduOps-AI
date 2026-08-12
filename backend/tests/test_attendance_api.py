import uuid
from datetime import date, time
from pathlib import Path

import pytest

import app.routers.attendance as attendance_router
from app.main import app
from app.models.attendance import AttendanceRecord
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.role import Role
from app.models.school import School
from app.models.subject import Subject
from app.models.timetable import Room, TimetableSlot
from app.models.user import User
from app.services.attendance_cv import FaceMatch, RecognitionResult, UnmatchedFace
from app.services.auth import CurrentUser, get_current_user

FIXTURES = Path(__file__).parent / "fixtures" / "faces"


def _override_user(role: str, user_id: int = 999):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role)

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_user_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def seed(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    student_role = db_session.query(Role).filter(Role.name == "student").one()

    teacher = User(
        supabase_id=uuid.uuid4(), email=f"t-{uuid.uuid4()}@example.com", role_id=teacher_role.id, school_id=school.id
    )
    db_session.add(teacher)
    db_session.flush()

    school_class = SchoolClass(
        name="Grade 8 - A", academic_year="2026-27", school_id=school.id, class_teacher_id=teacher.id
    )
    db_session.add(school_class)
    db_session.flush()

    subject = Subject(name="Math", school_id=school.id)
    room = Room(name="R1", capacity=30, room_type="classroom", school_id=school.id)
    db_session.add_all([subject, room])
    db_session.flush()

    student1 = User(
        supabase_id=uuid.uuid4(), email=f"s1-{uuid.uuid4()}@example.com", role_id=student_role.id, school_id=school.id
    )
    student2 = User(
        supabase_id=uuid.uuid4(), email=f"s2-{uuid.uuid4()}@example.com", role_id=student_role.id, school_id=school.id
    )
    db_session.add_all([student1, student2])
    db_session.flush()

    db_session.add_all(
        [
            Enrollment(student_id=student1.id, class_id=school_class.id, is_primary=True),
            Enrollment(student_id=student2.id, class_id=school_class.id, is_primary=True),
        ]
    )

    slot = TimetableSlot(
        day_of_week=0,
        period_number=0,
        start_time=time(8, 0),
        end_time=time(8, 45),
        subject_id=subject.id,
        teacher_id=teacher.id,
        class_id=school_class.id,
        room_id=room.id,
        academic_year="2026-27",
        is_active=True,
    )
    db_session.add(slot)
    db_session.commit()
    db_session.refresh(slot)

    return {
        "school": school,
        "class": school_class,
        "teacher": teacher,
        "student1": student1,
        "student2": student2,
        "slot": slot,
    }


# --- RBAC: 401 with no token, 403 with wrong role ---


def test_enroll_returns_401_without_token(client):
    resp = client.post("/attendance/enroll", data={"student_id": "1"}, files={"file": ("x.jpg", b"x", "image/jpeg")})
    assert resp.status_code == 401


def test_enroll_returns_403_for_student_role(client):
    _override_user("student")
    resp = client.post("/attendance/enroll", data={"student_id": "1"}, files={"file": ("x.jpg", b"x", "image/jpeg")})
    assert resp.status_code == 403


def test_mark_returns_401_without_token(client):
    resp = client.post(
        "/attendance/mark", data={"timetable_slot_id": "1"}, files={"file": ("x.jpg", b"x", "image/jpeg")}
    )
    assert resp.status_code == 401


def test_mark_returns_403_for_student_role(client):
    _override_user("student")
    resp = client.post(
        "/attendance/mark", data={"timetable_slot_id": "1"}, files={"file": ("x.jpg", b"x", "image/jpeg")}
    )
    assert resp.status_code == 403


def test_summary_returns_401_without_token(client):
    resp = client.get("/attendance/summary", params={"from_date": "2026-01-01", "to_date": "2026-01-31"})
    assert resp.status_code == 401


def test_review_returns_401_without_token(client):
    resp = client.put("/attendance/1/review", json={"status": "present"})
    assert resp.status_code == 401


def test_review_returns_403_for_student_role(client):
    _override_user("student")
    resp = client.put("/attendance/1/review", json={"status": "present"})
    assert resp.status_code == 403


# --- POST /attendance/enroll ---


def test_enroll_stores_embedding_for_real_face(client, seed):
    _override_user("admin")
    resp = client.post(
        "/attendance/enroll",
        data={"student_id": str(seed["student1"].id)},
        files={"file": ("ref.jpg", (FIXTURES / "person_a_1.jpg").read_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["student_id"] == seed["student1"].id


def test_enroll_returns_422_when_no_face_in_photo(client, seed):
    import cv2
    import numpy as np

    blank = np.full((100, 100, 3), 255, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", blank)
    assert ok

    _override_user("teacher", user_id=seed["teacher"].id)
    resp = client.post(
        "/attendance/enroll",
        data={"student_id": str(seed["student1"].id)},
        files={"file": ("blank.jpg", buf.tobytes(), "image/jpeg")},
    )
    assert resp.status_code == 422


def test_enroll_returns_404_for_unknown_student(client, seed):
    _override_user("admin")
    resp = client.post(
        "/attendance/enroll",
        data={"student_id": "999999"},
        files={"file": ("ref.jpg", (FIXTURES / "person_a_1.jpg").read_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 404


# --- POST /attendance/mark (recognition mocked, per task brief) ---


def test_mark_creates_records_for_matches_and_reports_unmatched(client, seed, db_session, monkeypatch):
    fake_result = RecognitionResult(
        matches=[
            FaceMatch(student_id=seed["student1"].id, confidence=0.9, face_location=(0, 10, 10, 0), needs_review=False),
            FaceMatch(student_id=seed["student2"].id, confidence=0.5, face_location=(0, 20, 10, 10), needs_review=True),
        ],
        unmatched=[UnmatchedFace(face_location=(0, 30, 10, 20), best_confidence=0.2)],
    )
    monkeypatch.setattr(attendance_router, "recognize_faces", lambda *a, **k: fake_result)

    _override_user("teacher", user_id=seed["teacher"].id)
    resp = client.post(
        "/attendance/mark",
        data={"timetable_slot_id": str(seed["slot"].id)},
        files={"file": ("classroom.jpg", b"fake-bytes", "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["records_created"] == 2
    assert len(body["matches"]) == 2
    assert len(body["unmatched_faces"]) == 1

    by_student = {m["student_id"]: m for m in body["matches"]}
    assert by_student[seed["student1"].id]["needs_review"] is False
    assert by_student[seed["student2"].id]["needs_review"] is True
    assert all(m["already_marked"] is False for m in body["matches"])

    records = db_session.query(AttendanceRecord).filter(AttendanceRecord.timetable_slot_id == seed["slot"].id).all()
    assert len(records) == 2
    assert all(r.source == "cv" and r.status == "present" for r in records)


def test_mark_is_idempotent_for_already_marked_students(client, seed, db_session, monkeypatch):
    existing = AttendanceRecord(
        student_id=seed["student1"].id,
        class_id=seed["class"].id,
        timetable_slot_id=seed["slot"].id,
        date=date.today(),
        status="present",
        source="cv",
        confidence_score=0.9,
    )
    db_session.add(existing)
    db_session.commit()
    db_session.refresh(existing)

    fake_result = RecognitionResult(
        matches=[
            FaceMatch(student_id=seed["student1"].id, confidence=0.95, face_location=(0, 10, 10, 0), needs_review=False)
        ],
        unmatched=[],
    )
    monkeypatch.setattr(attendance_router, "recognize_faces", lambda *a, **k: fake_result)

    _override_user("admin")
    resp = client.post(
        "/attendance/mark",
        data={"timetable_slot_id": str(seed["slot"].id)},
        files={"file": ("classroom.jpg", b"fake-bytes", "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["records_created"] == 0
    assert body["matches"][0]["already_marked"] is True
    assert body["matches"][0]["record_id"] == existing.id


def test_mark_returns_404_for_unknown_slot(client, seed, monkeypatch):
    monkeypatch.setattr(
        attendance_router, "recognize_faces", lambda *a, **k: RecognitionResult(matches=[], unmatched=[])
    )
    _override_user("admin")
    resp = client.post(
        "/attendance/mark", data={"timetable_slot_id": "999999"}, files={"file": ("c.jpg", b"x", "image/jpeg")}
    )
    assert resp.status_code == 404


# --- GET /attendance/summary: role scoping ---


def test_summary_admin_sees_all(client, seed, db_session):
    db_session.add(
        AttendanceRecord(
            student_id=seed["student1"].id,
            class_id=seed["class"].id,
            timetable_slot_id=seed["slot"].id,
            date=date.today(),
            status="present",
            source="manual",
        )
    )
    db_session.commit()

    _override_user("admin")
    resp = client.get("/attendance/summary", params={"from_date": "2026-01-01", "to_date": "2026-12-31"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(item["student_id"] == seed["student1"].id for item in body["items"])


def test_summary_student_cannot_see_another_students_data(client, seed, db_session):
    db_session.add_all(
        [
            AttendanceRecord(
                student_id=seed["student1"].id,
                class_id=seed["class"].id,
                timetable_slot_id=seed["slot"].id,
                date=date.today(),
                status="present",
                source="manual",
            ),
            AttendanceRecord(
                student_id=seed["student2"].id,
                class_id=seed["class"].id,
                timetable_slot_id=seed["slot"].id,
                date=date.today(),
                status="absent",
                source="manual",
            ),
        ]
    )
    db_session.commit()

    _override_user("student", user_id=seed["student1"].id)
    # Even asking for student2 explicitly, scoping must force it back to the caller.
    resp = client.get(
        "/attendance/summary",
        params={"from_date": "2026-01-01", "to_date": "2026-12-31", "student_id": seed["student2"].id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert all(item["student_id"] == seed["student1"].id for item in body["items"])


def test_summary_teacher_sees_own_class(client, seed, db_session):
    db_session.add(
        AttendanceRecord(
            student_id=seed["student1"].id,
            class_id=seed["class"].id,
            timetable_slot_id=seed["slot"].id,
            date=date.today(),
            status="present",
            source="manual",
        )
    )
    db_session.commit()

    _override_user("teacher", user_id=seed["teacher"].id)
    resp = client.get("/attendance/summary", params={"from_date": "2026-01-01", "to_date": "2026-12-31"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["present_count"] == 1
    assert body["items"][0]["present_pct"] == 100.0


def test_summary_teacher_cannot_see_another_teachers_class(client, seed):
    _override_user("teacher", user_id=888888)
    resp = client.get(
        "/attendance/summary",
        params={"from_date": "2026-01-01", "to_date": "2026-12-31", "class_id": seed["class"].id},
    )
    assert resp.status_code == 403


def test_summary_parent_requires_linked_student(client, seed):
    _override_user("parent")
    resp = client.get(
        "/attendance/summary",
        params={"from_date": "2026-01-01", "to_date": "2026-12-31", "student_id": seed["student1"].id},
    )
    assert resp.status_code == 403


# --- PUT /attendance/{record_id}/review ---


def test_review_updates_status_and_records_reviewer(client, seed, db_session):
    record = AttendanceRecord(
        student_id=seed["student1"].id,
        class_id=seed["class"].id,
        timetable_slot_id=seed["slot"].id,
        date=date.today(),
        status="present",
        source="cv",
        confidence_score=0.4,
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    _override_user("teacher", user_id=seed["teacher"].id)
    resp = client.put(f"/attendance/{record.id}/review", json={"status": "absent"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "absent"
    assert body["reviewed_by"] == seed["teacher"].id
    assert body["reviewed_at"] is not None


def test_review_returns_403_for_teacher_not_owning_class(client, seed, db_session):
    record = AttendanceRecord(
        student_id=seed["student1"].id,
        class_id=seed["class"].id,
        timetable_slot_id=seed["slot"].id,
        date=date.today(),
        status="present",
        source="cv",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    _override_user("teacher", user_id=777777)
    resp = client.put(f"/attendance/{record.id}/review", json={"status": "absent"})
    assert resp.status_code == 403


def test_review_returns_400_for_invalid_status(client, seed, db_session):
    record = AttendanceRecord(
        student_id=seed["student1"].id,
        class_id=seed["class"].id,
        timetable_slot_id=seed["slot"].id,
        date=date.today(),
        status="present",
        source="cv",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    _override_user("admin")
    resp = client.put(f"/attendance/{record.id}/review", json={"status": "on_fire"})
    assert resp.status_code == 400


def test_review_returns_404_for_missing_record(client, seed):
    _override_user("admin")
    resp = client.put("/attendance/999999/review", json={"status": "present"})
    assert resp.status_code == 404
