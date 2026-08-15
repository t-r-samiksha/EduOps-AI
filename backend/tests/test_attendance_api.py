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


# --- GET /attendance/enrollments --------------------------------------------
# Real, persisted enrollment state - backs the Enroll tab's list so it
# survives a full page reload (a client-only session list, by contrast,
# deliberately does not need to - it's reading DB truth fresh each time).


def test_enrollments_returns_401_without_token(client):
    resp = client.get("/attendance/enrollments", params={"school_id": 1})
    assert resp.status_code == 401


def test_enrollments_returns_403_for_student_role(client):
    _override_user("student")
    resp = client.get("/attendance/enrollments", params={"school_id": 1})
    assert resp.status_code == 403


def test_enrollments_returns_real_persisted_enrollments_for_the_school(client, seed):
    _override_user("admin")
    resp1 = client.post(
        "/attendance/enroll",
        data={"student_id": str(seed["student1"].id)},
        files={"file": ("a.jpg", (FIXTURES / "person_a_1.jpg").read_bytes(), "image/jpeg")},
    )
    assert resp1.status_code == 200
    resp2 = client.post(
        "/attendance/enroll",
        data={"student_id": str(seed["student2"].id)},
        files={"file": ("b.jpg", (FIXTURES / "person_b_1.jpg").read_bytes(), "image/jpeg")},
    )
    assert resp2.status_code == 200

    resp = client.get("/attendance/enrollments", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    body = resp.json()
    assert {item["student_id"] for item in body} == {seed["student1"].id, seed["student2"].id}
    # Newest first.
    assert body[0]["id"] == resp2.json()["id"]
    assert body[1]["id"] == resp1.json()["id"]


def test_enrollments_scoped_to_the_requested_school_only(client, seed, db_session):
    from app.models.role import Role
    from app.models.school import School

    other_school = School(name="Other School")
    db_session.add(other_school)
    db_session.flush()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    other_student = User(
        supabase_id=uuid.uuid4(), email=f"other-{uuid.uuid4()}@example.com", role_id=student_role.id,
        school_id=other_school.id,
    )
    db_session.add(other_student)
    db_session.commit()
    db_session.refresh(other_student)

    _override_user("admin")
    client.post(
        "/attendance/enroll",
        data={"student_id": str(seed["student1"].id)},
        files={"file": ("a.jpg", (FIXTURES / "person_a_1.jpg").read_bytes(), "image/jpeg")},
    )
    client.post(
        "/attendance/enroll",
        data={"student_id": str(other_student.id)},
        files={"file": ("b.jpg", (FIXTURES / "person_b_1.jpg").read_bytes(), "image/jpeg")},
    )

    resp = client.get("/attendance/enrollments", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    assert {item["student_id"] for item in resp.json()} == {seed["student1"].id}


def test_enroll_returns_422_for_a_real_two_face_photo(client, seed):
    """Real (unmocked) end-to-end check that a genuinely ambiguous reference
    photo is refused with a clear reason, not enrolled against one arbitrary
    face - enrollment requires exactly one unambiguous face."""
    _override_user("admin")
    resp = client.post(
        "/attendance/enroll",
        data={"student_id": str(seed["student1"].id)},
        files={"file": ("classroom.jpg", (FIXTURES / "classroom_two_faces.jpg").read_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "2" in detail  # names the actual face count found, not a generic message
    assert "one face" in detail.lower()


# --- POST /attendance/mark: real end-to-end multi-face recognition ---------
# (no monkeypatch - genuine images through the real detection/matching
# pipeline, confirming each face in a group photo is matched independently)


def test_mark_real_group_photo_matches_both_enrolled_students(client, seed, db_session):
    _override_user("admin")
    resp = client.post(
        "/attendance/enroll",
        data={"student_id": str(seed["student1"].id)},
        files={"file": ("a.jpg", (FIXTURES / "person_a_1.jpg").read_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200
    resp = client.post(
        "/attendance/enroll",
        data={"student_id": str(seed["student2"].id)},
        files={"file": ("b.jpg", (FIXTURES / "person_b_1.jpg").read_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200

    _override_user("teacher", user_id=seed["teacher"].id)
    resp = client.post(
        "/attendance/mark",
        data={"timetable_slot_id": str(seed["slot"].id)},
        files={"file": ("classroom.jpg", (FIXTURES / "classroom_two_faces.jpg").read_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()
    matched_student_ids = {m["student_id"] for m in body["matches"]}
    assert matched_student_ids == {seed["student1"].id, seed["student2"].id}
    assert body["records_created"] == 2
    assert body["unmatched_faces"] == []

    records = db_session.query(AttendanceRecord).filter(AttendanceRecord.timetable_slot_id == seed["slot"].id).all()
    assert {r.student_id for r in records} == {seed["student1"].id, seed["student2"].id}
    assert all(r.status == "present" and r.source == "cv" for r in records)


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


# --- PUT /attendance/{record_id}/review: student reassignment --------------
# A needs_review match can be wrong about WHICH student a face belongs to,
# not just uncertain about presence - these confirm the admin can correct
# the identity, not merely confirm/reject the original (possibly wrong) one.


def test_review_reassigns_to_a_different_enrolled_student(client, seed, db_session):
    record = AttendanceRecord(
        student_id=seed["student1"].id,
        class_id=seed["class"].id,
        timetable_slot_id=seed["slot"].id,
        date=date.today(),
        status="present",
        source="cv",
        confidence_score=0.45,
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    # A real user id - reviewed_by is a genuine FK, unlike the plain-403/400
    # tests elsewhere in this file that never reach the write.
    _override_user("admin", user_id=seed["teacher"].id)
    resp = client.put(
        f"/attendance/{record.id}/review", json={"status": "present", "student_id": seed["student2"].id}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["student_id"] == seed["student2"].id
    assert body["status"] == "present"

    db_session.refresh(record)
    assert record.student_id == seed["student2"].id


def test_review_rejects_reassignment_to_a_student_not_enrolled_in_the_class(client, seed, db_session):
    other_role_student = seed["student1"]  # stand-in; real check is against a genuinely unenrolled id
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
    resp = client.put(f"/attendance/{record.id}/review", json={"status": "present", "student_id": 999999999})
    assert resp.status_code == 400
    db_session.refresh(record)
    assert record.student_id == other_role_student.id  # unchanged


def test_review_rejects_reassignment_that_would_collide_with_an_existing_record(client, seed, db_session):
    record1 = AttendanceRecord(
        student_id=seed["student1"].id,
        class_id=seed["class"].id,
        timetable_slot_id=seed["slot"].id,
        date=date.today(),
        status="present",
        source="cv",
    )
    record2 = AttendanceRecord(
        student_id=seed["student2"].id,
        class_id=seed["class"].id,
        timetable_slot_id=seed["slot"].id,
        date=date.today(),
        status="present",
        source="cv",
    )
    db_session.add_all([record1, record2])
    db_session.commit()
    db_session.refresh(record1)

    # Reassigning record1 to student2 would collide with record2's own
    # (student2, slot, date, source) row - must be rejected, not silently
    # create a duplicate the unique constraint would otherwise reject with an
    # unhandled IntegrityError.
    _override_user("admin")
    resp = client.put(
        f"/attendance/{record1.id}/review", json={"status": "present", "student_id": seed["student2"].id}
    )
    assert resp.status_code == 400
    db_session.refresh(record1)
    assert record1.student_id == seed["student1"].id  # unchanged


def test_mark_response_includes_class_roster(client, seed):
    _override_user("admin")
    resp = client.post(
        "/attendance/mark",
        data={"timetable_slot_id": str(seed["slot"].id)},
        files={"file": ("classroom.jpg", (FIXTURES / "classroom_two_faces.jpg").read_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200
    roster_ids = {r["student_id"] for r in resp.json()["class_roster"]}
    assert roster_ids == {seed["student1"].id, seed["student2"].id}
