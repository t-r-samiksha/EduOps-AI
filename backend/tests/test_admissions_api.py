import uuid
from unittest.mock import patch

import pytest

from app.main import app
from app.models.admissions import AdmissionApplication
from app.models.class_ import SchoolClass
from app.models.document import Document, ExtractedEntity
from app.models.enrollment import Enrollment
from app.models.parent_student import ParentStudent
from app.models.role import Role
from app.models.school import School
from app.models.timetable import Room
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
    admin_user = _make_user(db_session, admin_role, "admin", school)

    # Real active section at grade_level=8 - no home_room_id, so capacity falls
    # back to DEFAULT_SECTION_CAPACITY (30).
    school_class = SchoolClass(
        name="Grade 8 - A", academic_year=ACADEMIC_YEAR, school_id=school.id, grade_level=8, section="A", is_active=True,
    )
    db_session.add(school_class)
    db_session.commit()
    db_session.refresh(school_class)

    return {"school": school, "class": school_class, "admin_user": admin_user}


def _submit(client, seed, grade="8"):
    return client.post(
        "/admin/admissions/applications",
        json={
            "school_id": seed["school"].id, "academic_year": ACADEMIC_YEAR, "applicant_name": "Jane Doe",
            "dob": "2015-04-01", "guardian_email": "guardian@example.com", "grade_applied": grade, "ocr_document_ids": [1],
        },
    )


def _fresh_uuid(**_kwargs):
    return uuid.uuid4()


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


def test_get_single_application_401_without_token(client):
    resp = client.get("/admin/admissions/applications/1")
    assert resp.status_code == 401


def test_grade_levels_401_without_token(client):
    resp = client.get("/admin/admissions/grade-levels", params={"school_id": 1, "academic_year": ACADEMIC_YEAR})
    assert resp.status_code == 401


# --- POST /admin/admissions/applications: grade LEVEL, not section (the real bug fix) ---


def test_submit_valid_application(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = _submit(client, seed)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "submitted"
    assert body["submitted_by"] == seed["admin_user"].id
    assert body["ocr_document_ids"] == [1]
    assert body["grade_applied"] == "8"


def test_submit_rejects_grade_level_not_offered(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = _submit(client, seed, grade="99")
    assert resp.status_code == 400
    assert "Grade 99" in resp.json()["detail"]


def test_submit_rejects_a_specific_section_name_the_old_way(client, seed):
    """Regression test for the exact bug found live: submitting a section NAME
    (e.g. "Grade 8 - A") instead of a bare grade level must now be rejected -
    grade_applied is a grade LEVEL, never a section name."""
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = _submit(client, seed, grade="Grade 8 - A")
    assert resp.status_code == 400


def test_submit_accepts_lkg_negative_grade_level(client, db_session, seed):
    lkg_class = SchoolClass(
        name="LKG - A", academic_year=ACADEMIC_YEAR, school_id=seed["school"].id, grade_level=-2, section="A", is_active=True,
    )
    db_session.add(lkg_class)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = _submit(client, seed, grade="-2")
    assert resp.status_code == 200
    assert resp.json()["grade_applied"] == "-2"


def test_submit_ignores_inactive_sections_when_checking_eligibility(client, db_session, seed):
    inactive_class = SchoolClass(
        name="Grade 12 - A", academic_year=ACADEMIC_YEAR, school_id=seed["school"].id, grade_level=12, section="A", is_active=False,
    )
    db_session.add(inactive_class)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = _submit(client, seed, grade="12")
    assert resp.status_code == 400


def test_submit_rejects_empty_applicant_name(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        "/admin/admissions/applications",
        json={"school_id": seed["school"].id, "academic_year": ACADEMIC_YEAR, "applicant_name": "  ", "dob": "2015-04-01", "guardian_email": "g@example.com", "grade_applied": "8"},
    )
    assert resp.status_code == 400


# --- GET /admin/admissions/grade-levels ---


def test_grade_levels_returns_real_offered_levels_with_friendly_display(client, db_session, seed):
    lkg_class = SchoolClass(
        name="LKG - A", academic_year=ACADEMIC_YEAR, school_id=seed["school"].id, grade_level=-2, section="A", is_active=True,
    )
    db_session.add(lkg_class)
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/admissions/grade-levels", params={"school_id": seed["school"].id, "academic_year": ACADEMIC_YEAR})
    assert resp.status_code == 200
    items = resp.json()["items"]
    by_level = {i["grade_level"]: i["display"] for i in items}
    assert by_level == {8: "Grade 8", -2: "LKG"}


# --- GET /admin/admissions/applications ---


def test_list_returns_submitted_application(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.get("/admin/admissions/applications", params={"status": "submitted"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(a["id"] == app_id for a in body["items"])
    assert body["total"] >= 1


def test_get_single_application_returns_full_detail(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.get(f"/admin/admissions/applications/{app_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == app_id
    assert resp.json()["ocr_document_ids"] == [1]


def test_get_single_application_404_for_missing_id(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.get("/admin/admissions/applications/999999")
    assert resp.status_code == 404


# --- Cross-school scoping: a real bug found live (a cross-school admin login during
# manual walkthrough testing saw every other school's applications) - list/get/patch
# all filter on the caller's own school_id now, matching students.py/teachers.py/
# parents.py's existing convention. ---


def test_list_never_returns_another_schools_application(client, db_session, seed):
    other_school = School(name="Another School")
    db_session.add(other_school)
    db_session.commit()
    db_session.refresh(other_school)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    _override_user("admin", user_id=999999, school_id=other_school.id)
    resp = client.get("/admin/admissions/applications")
    assert resp.status_code == 200
    assert all(a["id"] != app_id for a in resp.json()["items"])


def test_get_single_application_404s_for_another_schools_application(client, db_session, seed):
    other_school = School(name="Another School")
    db_session.add(other_school)
    db_session.commit()
    db_session.refresh(other_school)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    _override_user("admin", user_id=999999, school_id=other_school.id)
    resp = client.get(f"/admin/admissions/applications/{app_id}")
    assert resp.status_code == 404


def test_update_404s_for_another_schools_application(client, db_session, seed):
    other_school = School(name="Another School")
    db_session.add(other_school)
    db_session.commit()
    db_session.refresh(other_school)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    _override_user("admin", user_id=999999, school_id=other_school.id)
    resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
    assert resp.status_code == 404


# --- POST /admin/admissions/applications/{id}/documents: multi-document linking ---


def _make_document(db_session, school, document_type, fields, uploaded_by):
    """A minimal real Document + ExtractedEntity row(s), bypassing actual Tesseract -
    same pattern as test_documents_api.py's own direct-construction tests."""
    document = Document(uploaded_by=uploaded_by, school_id=school.id, document_type=document_type, file_url="x", status="done")
    db_session.add(document)
    db_session.flush()
    for field_name, value in fields.items():
        db_session.add(
            ExtractedEntity(document_id=document.id, field_name=field_name, field_value=value, confidence_score=0.9, is_low_confidence=False)
        )
    db_session.commit()
    db_session.refresh(document)
    return document


def _attach_required_documents(client, db_session, seed, app_id):
    """A real marksheet + id_proof, directly linked to app_id via the real attach
    endpoint - REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE means every test that
    exercises an actual accept now needs these first, or the accept 400s on
    missing documents before it ever reaches whatever that test is really about."""
    marksheet = _make_document(db_session, seed["school"], "marksheet", {"total_marks": "450"}, seed["admin_user"].id)
    id_proof = _make_document(db_session, seed["school"], "id_proof", {"id_number": "AB1234567"}, seed["admin_user"].id)
    client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": marksheet.id})
    client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": id_proof.id})


def test_attach_document_appends_and_returns_full_detail(client, db_session, seed):
    marksheet = _make_document(db_session, seed["school"], "marksheet", {"student_name": "Jane Doe", "total_marks": "450"}, seed["admin_user"].id)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": marksheet.id})
    assert resp.status_code == 200
    body = resp.json()
    assert marksheet.id in body["ocr_document_ids"]
    linked = next(d for d in body["documents"] if d["id"] == marksheet.id)
    assert linked["document_type"] == "marksheet"
    assert linked["extracted_fields"]["student_name"] == "Jane Doe"

    # Persisted for real, not just in the response - a fresh GET sees it too.
    refetched = client.get(f"/admin/admissions/applications/{app_id}").json()
    assert marksheet.id in refetched["ocr_document_ids"]


def test_attach_multiple_document_types_all_appear_together(client, db_session, seed):
    marksheet = _make_document(db_session, seed["school"], "marksheet", {"total_marks": "450"}, seed["admin_user"].id)
    id_proof = _make_document(db_session, seed["school"], "id_proof", {"id_number": "AB1234567"}, seed["admin_user"].id)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": marksheet.id})
    resp = client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": id_proof.id})
    assert resp.status_code == 200
    body = resp.json()

    doc_types = {d["document_type"] for d in body["documents"]}
    # ocr_document_ids started with the seed's phantom id=1 (see _submit) plus the
    # two real ones just attached - only the two real documents resolve.
    assert doc_types == {"marksheet", "id_proof"}
    assert len(body["documents"]) == 2


def test_attach_document_is_idempotent_when_already_linked(client, db_session, seed):
    marksheet = _make_document(db_session, seed["school"], "marksheet", {"total_marks": "450"}, seed["admin_user"].id)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": marksheet.id})
    resp = client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": marksheet.id})
    assert resp.status_code == 200
    assert resp.json()["ocr_document_ids"].count(marksheet.id) == 1
    assert len(resp.json()["documents"]) == 1


def test_attach_document_404s_for_unknown_application(client, db_session, seed):
    marksheet = _make_document(db_session, seed["school"], "marksheet", {"total_marks": "450"}, seed["admin_user"].id)
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post("/admin/admissions/applications/999999/documents", json={"document_id": marksheet.id})
    assert resp.status_code == 404


def test_attach_document_404s_for_unknown_document_id(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]
    resp = client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": 999999})
    assert resp.status_code == 404


def test_attach_document_404s_for_document_in_a_different_school(client, db_session, seed):
    other_school = School(name="Another School")
    db_session.add(other_school)
    db_session.commit()
    db_session.refresh(other_school)
    other_doc = _make_document(db_session, other_school, "id_proof", {"id_number": "XY999"}, seed["admin_user"].id)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": other_doc.id})
    assert resp.status_code == 404

    # Confirm it genuinely wasn't linked, not just a misleading error after a real append.
    refetched = client.get(f"/admin/admissions/applications/{app_id}").json()
    assert other_doc.id not in refetched["ocr_document_ids"]


def test_attach_document_404s_for_another_schools_application(client, db_session, seed):
    other_school = School(name="Another School")
    db_session.add(other_school)
    db_session.commit()
    db_session.refresh(other_school)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]
    own_doc = _make_document(db_session, seed["school"], "marksheet", {"total_marks": "450"}, seed["admin_user"].id)

    _override_user("admin", user_id=999999, school_id=other_school.id)
    resp = client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": own_doc.id})
    assert resp.status_code == 404


def test_attach_document_rejects_linking_to_a_second_application(client, db_session, seed):
    """Regression test for a real crash found live (real sam school data): before
    this guard existed, the same document could end up in two applications'
    ocr_document_ids, which then made documents.py::_linked_application_for_document
    raise MultipleResultsFound and 500 the entire document list for that school."""
    marksheet = _make_document(db_session, seed["school"], "marksheet", {"total_marks": "450"}, seed["admin_user"].id)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    first_app_id = _submit(client, seed).json()["id"]
    second_app_id = _submit(client, seed).json()["id"]

    resp = client.post(f"/admin/admissions/applications/{first_app_id}/documents", json={"document_id": marksheet.id})
    assert resp.status_code == 200

    resp = client.post(f"/admin/admissions/applications/{second_app_id}/documents", json={"document_id": marksheet.id})
    assert resp.status_code == 409
    assert str(first_app_id) in resp.json()["detail"]

    # Confirm it genuinely wasn't linked to the second application.
    refetched = client.get(f"/admin/admissions/applications/{second_app_id}").json()
    assert marksheet.id not in refetched["ocr_document_ids"]


# --- PATCH /admin/admissions/applications/{id}: state machine ---


def test_submitted_to_under_review_succeeds(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "under_review"


def test_submitted_directly_to_accepted_is_rejected(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
    assert resp.status_code == 400
    assert "under_review" in resp.json()["detail"]


def test_accepted_is_terminal_via_api(client, db_session, seed):
    application = AdmissionApplication(
        school_id=seed["school"].id, academic_year=ACADEMIC_YEAR, applicant_name="X", dob="2015-01-01",
        guardian_email="g@example.com", grade_applied="8", status="accepted", submitted_by=seed["admin_user"].id,
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.patch(f"/admin/admissions/applications/{application.id}", json={"status": "under_review"})
    assert resp.status_code == 400


def test_update_404_for_missing_application(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.patch("/admin/admissions/applications/999999", json={"status": "under_review"})
    assert resp.status_code == 404


# --- reject: requires a real reason ---


def test_reject_without_reason_is_blocked(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "rejected"})
    assert resp.status_code == 400
    assert "reason" in resp.json()["detail"].lower()

    resp2 = client.get(f"/admin/admissions/applications/{app_id}")
    assert resp2.json()["status"] == "submitted"  # untouched - reject was blocked


def test_reject_with_real_reason_succeeds_and_is_terminal(client, db_session, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.patch(
        f"/admin/admissions/applications/{app_id}",
        json={"status": "rejected", "decision_justification": "Grade not offered at this campus for this student's age"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert resp.json()["enrollment_created"] is False

    application = db_session.query(AdmissionApplication).filter(AdmissionApplication.id == app_id).one()
    assert application.decision_justification == "Grade not offered at this campus for this student's age"
    assert application.enrolled_student_id is None

    # terminal - rejecting again (even with a reason) is illegal
    resp2 = client.patch(
        f"/admin/admissions/applications/{app_id}",
        json={"status": "rejected", "decision_justification": "another reason"},
    )
    assert resp2.status_code == 400


# --- accept: the real, automatic pipeline (section + student + guardian + enrollment) ---


def test_accept_creates_real_student_account_section_and_enrollment(client, db_session, seed):
    with patch("app.routers.admissions.create_auth_account", side_effect=_fresh_uuid) as mock_create:
        _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
        app_id = _submit(client, seed).json()["id"]
        client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
        _attach_required_documents(client, db_session, seed, app_id)

        resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["enrollment_created"] is True
        assert body["assigned_class_id"] == seed["class"].id
        assert body["parent_account_created"] is True
        student_id = body["enrolled_student_id"]
        parent_id = body["parent_user_id"]

        assert mock_create.call_count == 2  # a real student account + a real new parent account

    student_role = db_session.query(Role).filter(Role.name == "student").one()
    student = db_session.query(User).filter(User.id == student_id).one()
    assert student.role_id == student_role.id
    assert student.full_name == "Jane Doe"
    assert student.school_id == seed["school"].id
    assert student.is_active is True

    enrollment = (
        db_session.query(Enrollment)
        .filter(Enrollment.student_id == student_id, Enrollment.class_id == seed["class"].id, Enrollment.subject_id.is_(None))
        .one()
    )
    assert enrollment.is_primary is True

    parent_role = db_session.query(Role).filter(Role.name == "parent").one()
    parent = db_session.query(User).filter(User.id == parent_id).one()
    assert parent.role_id == parent_role.id
    assert parent.email == "guardian@example.com"

    link = db_session.query(ParentStudent).filter(ParentStudent.parent_id == parent_id, ParentStudent.student_id == student_id).one()
    assert link is not None

    application = db_session.query(AdmissionApplication).filter(AdmissionApplication.id == app_id).one()
    assert application.enrolled_student_id == student_id


def test_accept_reuses_an_existing_parent_account_for_the_same_guardian_email(client, db_session, seed):
    """Real test: a returning family's second child - guardian_email already
    belongs to a real parent account from an earlier acceptance. Must be
    reused, not duplicated."""
    parent_role = db_session.query(Role).filter(Role.name == "parent").one()
    existing_parent = User(
        supabase_id=uuid.uuid4(), email="guardian@example.com", full_name="Existing Parent",
        role_id=parent_role.id, school_id=seed["school"].id,
    )
    db_session.add(existing_parent)
    db_session.commit()
    db_session.refresh(existing_parent)

    with patch("app.routers.admissions.create_auth_account", side_effect=_fresh_uuid) as mock_create:
        _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
        app_id = _submit(client, seed).json()["id"]
        client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
        _attach_required_documents(client, db_session, seed, app_id)
        resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["parent_account_created"] is False
        assert body["parent_user_id"] == existing_parent.id
        assert mock_create.call_count == 1  # only the student - parent was reused, not recreated


def test_accept_fails_cleanly_when_guardian_email_belongs_to_a_non_parent_account(client, db_session, seed):
    teacher_role = db_session.query(Role).filter(Role.name == "teacher").one()
    db_session.add(
        User(supabase_id=uuid.uuid4(), email="guardian@example.com", full_name="A Teacher", role_id=teacher_role.id, school_id=seed["school"].id)
    )
    db_session.commit()

    with patch("app.routers.admissions.create_auth_account", side_effect=_fresh_uuid) as mock_create:
        _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
        app_id = _submit(client, seed).json()["id"]
        client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
        _attach_required_documents(client, db_session, seed, app_id)
        resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
        assert resp.status_code == 400
        assert "guardian@example.com" in resp.json()["detail"]

        # No real account was ever created - the conflict is validated BEFORE
        # any create_auth_account call (never orphans a real Supabase account).
        mock_create.assert_not_called()

    application = db_session.query(AdmissionApplication).filter(AdmissionApplication.id == app_id).one()
    assert application.enrolled_student_id is None


def test_accept_auto_assigns_the_least_filled_section(client, db_session, seed):
    """Two real sections at the same grade level, one already has students - the
    less-filled one must be picked automatically, never manually specified."""
    fuller_class = SchoolClass(
        name="Grade 8 - B", academic_year=ACADEMIC_YEAR, school_id=seed["school"].id, grade_level=8, section="B", is_active=True,
    )
    db_session.add(fuller_class)
    db_session.commit()
    db_session.refresh(fuller_class)

    # Pre-fill seed["class"] (Grade 8 - A) with 5 real students, fuller_class (B) with 0.
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    for i in range(5):
        s = _make_user(db_session, student_role, f"existing{i}", seed["school"])
        db_session.add(Enrollment(student_id=s.id, class_id=seed["class"].id, subject_id=None, is_primary=True))
    db_session.commit()

    with patch("app.routers.admissions.create_auth_account", side_effect=_fresh_uuid):
        _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
        app_id = _submit(client, seed).json()["id"]
        client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
        _attach_required_documents(client, db_session, seed, app_id)
        resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
        assert resp.status_code == 200
        # fuller_class (0 students) is less filled than seed["class"] (5 students)
        assert resp.json()["assigned_class_id"] == fuller_class.id


def test_accept_returns_clear_error_when_grade_level_is_completely_full(client, db_session, seed):
    """Fill the one real section at this grade level to capacity, then attempt
    to accept one more - must get a clean, specific error, never a silent
    overfill."""
    room = Room(name="R1", capacity=2, room_type="classroom", school_id=seed["school"].id)
    db_session.add(room)
    db_session.flush()
    seed["class"].home_room_id = room.id
    db_session.commit()

    student_role = db_session.query(Role).filter(Role.name == "student").one()
    for i in range(2):
        s = _make_user(db_session, student_role, f"existing{i}", seed["school"])
        db_session.add(Enrollment(student_id=s.id, class_id=seed["class"].id, subject_id=None, is_primary=True))
    db_session.commit()

    with patch("app.routers.admissions.create_auth_account", side_effect=_fresh_uuid) as mock_create:
        _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
        app_id = _submit(client, seed).json()["id"]
        client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
        _attach_required_documents(client, db_session, seed, app_id)
        resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
        assert resp.status_code == 400
        assert resp.json()["detail"] == "No available seats in Grade 8 for 2026-27 - all sections full"

        # No real account was created - capacity is checked before any account creation.
        mock_create.assert_not_called()

    application = db_session.query(AdmissionApplication).filter(AdmissionApplication.id == app_id).one()
    assert application.status == "under_review"  # decision was never finalized
    assert application.enrolled_student_id is None


def test_accept_uses_room_capacity_when_home_room_is_set(client, db_session, seed):
    """A section with a real home_room_id uses that Room's real capacity, not
    the DEFAULT_SECTION_CAPACITY fallback."""
    room = Room(name="Small Room", capacity=1, room_type="classroom", school_id=seed["school"].id)
    db_session.add(room)
    db_session.flush()
    seed["class"].home_room_id = room.id
    db_session.commit()

    student_role = db_session.query(Role).filter(Role.name == "student").one()
    s = _make_user(db_session, student_role, "existing", seed["school"])
    db_session.add(Enrollment(student_id=s.id, class_id=seed["class"].id, subject_id=None, is_primary=True))
    db_session.commit()

    with patch("app.routers.admissions.create_auth_account", side_effect=_fresh_uuid):
        _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
        app_id = _submit(client, seed).json()["id"]
        client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
        _attach_required_documents(client, db_session, seed, app_id)
        resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
        # capacity=1, already 1 enrolled -> full, even though DEFAULT_SECTION_CAPACITY (30) would have room
        assert resp.status_code == 400


def test_accept_rejects_an_application_whose_grade_applied_predates_the_grade_level_convention(client, db_session, seed):
    """A pre-existing application submitted under the OLD section-name
    convention (e.g. "Grade 3 - A") can't be auto-assigned a section - must
    fail with a clear error, not crash."""
    application = AdmissionApplication(
        school_id=seed["school"].id, academic_year=ACADEMIC_YEAR, applicant_name="Old Style", dob="2015-01-01",
        guardian_email="old@example.com", grade_applied="Grade 8 - A", status="under_review", submitted_by=seed["admin_user"].id,
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    _attach_required_documents(client, db_session, seed, application.id)
    resp = client.patch(f"/admin/admissions/applications/{application.id}", json={"status": "accepted"})
    assert resp.status_code == 400
    assert "not a valid grade level" in resp.json()["detail"]


# --- accept: marksheet + id_proof are now a real, hard requirement ---


def test_accept_fails_when_no_documents_are_linked_at_all(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]
    client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})

    resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
    assert resp.status_code == 400
    assert "marksheet" in resp.json()["detail"]
    assert "id_proof" in resp.json()["detail"]

    refetched = client.get(f"/admin/admissions/applications/{app_id}").json()
    assert refetched["status"] == "under_review"  # never mutated toward accepted


def test_accept_fails_when_only_marksheet_is_linked(client, db_session, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]
    client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})

    marksheet = _make_document(db_session, seed["school"], "marksheet", {"total_marks": "450"}, seed["admin_user"].id)
    client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": marksheet.id})

    resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
    assert resp.status_code == 400
    assert "id_proof" in resp.json()["detail"]
    assert "marksheet" not in resp.json()["detail"]  # only the genuinely missing type is named


def test_accept_fails_when_only_id_proof_is_linked(client, db_session, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]
    client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})

    id_proof = _make_document(db_session, seed["school"], "id_proof", {"id_number": "AB1234567"}, seed["admin_user"].id)
    client.post(f"/admin/admissions/applications/{app_id}/documents", json={"document_id": id_proof.id})

    resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
    assert resp.status_code == 400
    assert "marksheet" in resp.json()["detail"]
    assert "id_proof" not in resp.json()["detail"]


def test_accept_succeeds_once_both_required_documents_are_linked(client, db_session, seed):
    with patch("app.routers.admissions.create_auth_account", side_effect=_fresh_uuid):
        _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
        app_id = _submit(client, seed).json()["id"]
        client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
        _attach_required_documents(client, db_session, seed, app_id)

        resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"


def test_reject_never_requires_marksheet_or_id_proof(client, seed):
    """The hard requirement is accept-only - rejecting an application with zero
    documents linked must still work (no reason to demand evidence for a
    rejection)."""
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.patch(
        f"/admin/admissions/applications/{app_id}", json={"status": "rejected", "decision_justification": "Not a fit"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


# --- guardian_name/guardian_phone: real fields, real parent account names ---


def test_submit_stores_guardian_name_and_phone(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.post(
        "/admin/admissions/applications",
        json={
            "school_id": seed["school"].id, "academic_year": ACADEMIC_YEAR, "applicant_name": "Jane Doe",
            "dob": "2015-04-01", "guardian_email": "guardian@example.com", "guardian_name": "Rajesh Sharma",
            "guardian_phone": "9876543210", "grade_applied": "8",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["guardian_name"] == "Rajesh Sharma"
    assert resp.json()["guardian_phone"] == "9876543210"


def test_submit_allows_omitting_guardian_name_and_phone(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = _submit(client, seed)
    assert resp.status_code == 200
    assert resp.json()["guardian_name"] is None
    assert resp.json()["guardian_phone"] is None


def test_accept_gives_the_new_parent_account_a_real_name_when_available(client, db_session, seed):
    """Regression test for a real gap found live (sam school): parent accounts
    created by accept had full_name=None because guardian_name never reached this
    far - now it does, end to end from submission through to the real account."""
    with patch("app.routers.admissions.create_auth_account", side_effect=_fresh_uuid):
        _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
        resp = client.post(
            "/admin/admissions/applications",
            json={
                "school_id": seed["school"].id, "academic_year": ACADEMIC_YEAR, "applicant_name": "Jane Doe",
                "dob": "2015-04-01", "guardian_email": "guardian@example.com", "guardian_name": "Rajesh Sharma",
                "grade_applied": "8", "ocr_document_ids": [1],
            },
        )
        app_id = resp.json()["id"]
        client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
        _attach_required_documents(client, db_session, seed, app_id)

        resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
        assert resp.status_code == 200
        parent_id = resp.json()["parent_user_id"]

    parent = db_session.query(User).filter(User.id == parent_id).one()
    assert parent.full_name == "Rajesh Sharma"


def test_accept_leaves_parent_full_name_null_when_guardian_name_was_never_given(client, db_session, seed):
    with patch("app.routers.admissions.create_auth_account", side_effect=_fresh_uuid):
        _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
        app_id = _submit(client, seed).json()["id"]  # _submit sends no guardian_name
        client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
        _attach_required_documents(client, db_session, seed, app_id)

        resp = client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})
        parent_id = resp.json()["parent_user_id"]

    parent = db_session.query(User).filter(User.id == parent_id).one()
    assert parent.full_name is None


# --- PATCH /admin/admissions/applications/{id}/details ---


def test_edit_details_updates_applicant_name(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.patch(f"/admin/admissions/applications/{app_id}/details", json={"applicant_name": "Jane A. Doe"})
    assert resp.status_code == 200
    assert resp.json()["applicant_name"] == "Jane A. Doe"
    # untouched fields survive a partial update
    assert resp.json()["guardian_email"] == "guardian@example.com"


def test_edit_details_updates_guardian_name_dob_email_phone_together(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.patch(
        f"/admin/admissions/applications/{app_id}/details",
        json={"dob": "2016-01-01", "guardian_email": "new@example.com", "guardian_name": "New Guardian", "guardian_phone": "9999999999"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dob"] == "2016-01-01"
    assert body["guardian_email"] == "new@example.com"
    assert body["guardian_name"] == "New Guardian"
    assert body["guardian_phone"] == "9999999999"


def test_edit_details_rejects_empty_applicant_name(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.patch(f"/admin/admissions/applications/{app_id}/details", json={"applicant_name": "   "})
    assert resp.status_code == 400


def test_edit_details_rejects_empty_guardian_email(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    resp = client.patch(f"/admin/admissions/applications/{app_id}/details", json={"guardian_email": "   "})
    assert resp.status_code == 400


def test_edit_details_blocked_once_accepted(client, db_session, seed):
    with patch("app.routers.admissions.create_auth_account", side_effect=_fresh_uuid):
        _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
        app_id = _submit(client, seed).json()["id"]
        client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "under_review"})
        _attach_required_documents(client, db_session, seed, app_id)
        client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "accepted"})

    resp = client.patch(f"/admin/admissions/applications/{app_id}/details", json={"applicant_name": "Changed"})
    assert resp.status_code == 400
    assert "accepted" in resp.json()["detail"].lower()


def test_edit_details_still_allowed_after_reject(client, seed):
    """Rejected is terminal for the STATE MACHINE (no further transitions), but
    editing the record's own details afterward is harmless - no real account was
    ever created from a rejected application."""
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]
    client.patch(f"/admin/admissions/applications/{app_id}", json={"status": "rejected", "decision_justification": "x"})

    resp = client.patch(f"/admin/admissions/applications/{app_id}/details", json={"applicant_name": "Changed"})
    assert resp.status_code == 200
    assert resp.json()["applicant_name"] == "Changed"


def test_edit_details_404_for_unknown_application(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    resp = client.patch("/admin/admissions/applications/999999/details", json={"applicant_name": "x"})
    assert resp.status_code == 404


def test_edit_details_404_for_another_schools_application(client, db_session, seed):
    other_school = School(name="Another School")
    db_session.add(other_school)
    db_session.commit()
    db_session.refresh(other_school)

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    app_id = _submit(client, seed).json()["id"]

    _override_user("admin", user_id=999999, school_id=other_school.id)
    resp = client.patch(f"/admin/admissions/applications/{app_id}/details", json={"applicant_name": "x"})
    assert resp.status_code == 404


def test_edit_details_401_without_token(client):
    resp = client.patch("/admin/admissions/applications/1/details", json={"applicant_name": "x"})
    assert resp.status_code == 401


def test_edit_details_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.patch("/admin/admissions/applications/1/details", json={"applicant_name": "x"})
    assert resp.status_code == 403
