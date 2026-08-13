import uuid

import pytest

from app.main import app
from app.models.admissions import AdmissionApplication
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.role import Role
from app.models.school import School
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
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    admin_user = _make_user(db_session, admin_role, "admin", school)
    existing_student = _make_user(db_session, student_role, "existing-student", school)

    school_class = SchoolClass(name="Grade 8", academic_year=ACADEMIC_YEAR, school_id=school.id)
    db_session.add(school_class)
    db_session.commit()

    return {"school": school, "class": school_class, "admin_user": admin_user, "existing_student": existing_student}


def _submit(client, seed, grade="Grade 8"):
    return client.post(
        "/admin/admissions/applications",
        json={
            "school_id": seed["school"].id, "academic_year": ACADEMIC_YEAR, "applicant_name": "Jane Doe",
            "dob": "2015-04-01", "guardian_email": "guardian@example.com", "grade_applied": grade, "ocr_document_ids": [1],
        },
    )


# --- RBAC ---


def test_submit_401_without_token(client):
    resp = client.post("/admin/admissions/applications", json={})
    assert resp.status_code == 401


def test_submit_403_for_principal_role(client):
    # Per stub: submission is admin-only, not principal.
    _override_user("principal")
    resp = client.post("/admin/admissions/applications", json={})
    assert resp.status_code == 403


def test_list_401_without_token(client):
    resp = client.get("/admin/admissions/applications")
    assert resp.status_code == 401


def test_list_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/admin/admissions/applications")
    assert resp.status_code == 403


def test_update_401_without_token(client):
    resp = client.patch("/admin/admissions/applications/1", json={"status": "under_review"})
    assert resp.status_code == 401


def test_update_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.patch("/admin/admissions/applications/1", json={"status": "under_review"})
    assert resp.status_code == 403


# --- POST /admin/admissions/applications ---


def test_submit_valid_application(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _submit(client, seed)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "submitted"
    assert body["submitted_by"] == seed["admin_user"].id
    assert body["ocr_document_ids"] == [1]


def test_submit_rejects_grade_not_offered(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _submit(client, seed, grade="Grade 99")
    assert resp.status_code == 400


def test_submit_rejects_empty_applicant_name(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        "/admin/admissions/applications",
        json={"school_id": seed["school"].id, "academic_year": ACADEMIC_YEAR, "applicant_name": "  ", "dob": "2015-04-01", "guardian_email": "g@example.com", "grade_applied": "Grade 8"},
    )
    assert resp.status_code == 400


# --- GET /admin/admissions/applications ---


def test_list_returns_submitted_application(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.get("/admin/admissions/applications", params={"status": "submitted"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(a["id"] == app_id for a in body["items"])
    assert body["total"] >= 1


# --- PATCH /admin/admissions/applications/{id}: state machine ---


def test_submitted_to_under_review_succeeds(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "under_review"


def test_submitted_directly_to_accepted_is_rejected(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
    assert resp.status_code == 400
    assert "under_review" in resp.json()["detail"]


def test_accepted_is_terminal_via_api(client, db_session, seed):
    application = AdmissionApplication(
        school_id=seed["school"].id, academic_year=ACADEMIC_YEAR, applicant_name="X", dob="2015-01-01",
        guardian_email="g@example.com", grade_applied="Grade 8", status="accepted", submitted_by=seed["admin_user"].id,
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.patch(f"/admin/admissions/applications/{application.id}", json={"status": "under_review"})
    assert resp.status_code == 400


def test_update_404_for_missing_application(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.patch("/admin/admissions/applications/999999", json={"status": "under_review"})
    assert resp.status_code == 404


# --- accept -> real Enrollment wiring ---


def test_accept_with_student_and_class_creates_real_enrollment(client, db_session, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    app_id = _submit(client, seed).json()["id"]
    client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})

    resp = client.patch(
        f"/admin/admissions/applications/{app_id}",
        json={"status": "accepted", "student_user_id": seed["existing_student"].id, "class_id": seed["class"].id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["enrollment_created"] is True

    enrollment = (
        db_session.query(Enrollment)
        .filter(Enrollment.student_id == seed["existing_student"].id, Enrollment.class_id == seed["class"].id)
        .one()
    )
    assert enrollment.is_primary is True

    application = db_session.query(AdmissionApplication).filter(AdmissionApplication.id == app_id).one()
    assert application.enrolled_student_id == seed["existing_student"].id


def test_accept_without_student_user_id_does_not_create_enrollment(client, db_session, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    app_id = _submit(client, seed).json()["id"]
    client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})

    resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["enrollment_created"] is False

    application = db_session.query(AdmissionApplication).filter(AdmissionApplication.id == app_id).one()
    assert application.enrolled_student_id is None


def test_accept_with_unknown_student_user_id_returns_404(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    app_id = _submit(client, seed).json()["id"]
    client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})

    resp = client.patch(
        f"/admin/admissions/applications/{app_id}",
        json={"status": "accepted", "student_user_id": 999999, "class_id": seed["class"].id},
    )
    assert resp.status_code == 404
