import uuid
from pathlib import Path

import pytest

from app.main import app
from app.models.document import Document
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

FIXTURES = Path(__file__).parent / "fixtures" / "documents"


def _override_user(role: str, user_id: int = 999, school_id: int | None = None):
    def _fake_user():
        return CurrentUser(id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role, school_id=school_id)

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

    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    principal_role = db_session.query(Role).filter(Role.name == "principal").one()

    admin_user = User(supabase_id=uuid.uuid4(), email=f"admin-{uuid.uuid4()}@example.com", full_name="Admin", role_id=admin_role.id, school_id=school.id)
    principal_user = User(supabase_id=uuid.uuid4(), email=f"principal-{uuid.uuid4()}@example.com", full_name="Principal", role_id=principal_role.id, school_id=school.id)
    db_session.add_all([admin_user, principal_user])
    db_session.commit()

    return {"school": school, "admin_user": admin_user, "principal_user": principal_user}


def _upload(client, path: Path, document_type: str, school_id: int):
    return client.post(
        "/admin/ocr/documents",
        files={"file": (path.name, path.read_bytes(), "image/png")},
        data={"document_type": document_type, "school_id": str(school_id)},
    )


# --- RBAC: 401 no token, 403 wrong role ---


def test_upload_401_without_token(client):
    resp = _upload(client, FIXTURES / "admission_form.png", "admission_form", 1)
    assert resp.status_code == 401


def test_upload_403_for_teacher_role(client):
    _override_user("teacher")
    resp = _upload(client, FIXTURES / "admission_form.png", "admission_form", 1)
    assert resp.status_code == 403


def test_get_document_401_without_token(client):
    resp = client.get("/admin/ocr/documents/1", params={"school_id": 1})
    assert resp.status_code == 401


def test_get_document_403_for_student_role(client):
    _override_user("student")
    resp = client.get("/admin/ocr/documents/1", params={"school_id": 1})
    assert resp.status_code == 403


def test_correct_entity_401_without_token(client):
    resp = client.put("/admin/ocr/documents/1/entities/1", params={"school_id": 1}, json={"corrected_value": "x"})
    assert resp.status_code == 401


def test_correct_entity_403_for_parent_role(client):
    _override_user("parent")
    resp = client.put("/admin/ocr/documents/1/entities/1", params={"school_id": 1}, json={"corrected_value": "x"})
    assert resp.status_code == 403


def test_reextract_401_without_token(client):
    resp = client.post("/admin/ocr/documents/1/reextract", params={"school_id": 1}, json={})
    assert resp.status_code == 401


def test_reextract_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/ocr/documents/1/reextract", params={"school_id": 1}, json={})
    assert resp.status_code == 403


# --- POST /admin/ocr/documents: validation ---


def test_upload_rejects_invalid_document_type(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _upload(client, FIXTURES / "admission_form.png", "not_a_real_type", seed["school"].id)
    assert resp.status_code == 400


def test_upload_rejects_undecodable_image(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        "/admin/ocr/documents",
        files={"file": ("bad.png", b"not an image", "image/png")},
        data={"document_type": "other", "school_id": str(seed["school"].id)},
    )
    assert resp.status_code == 422


def test_upload_rejects_unknown_school_id(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _upload(client, FIXTURES / "admission_form.png", "admission_form", 999999999)
    assert resp.status_code == 400


# --- Full flow: upload -> get -> correct -> reextract ---


def test_full_document_lifecycle(client, db_session, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _upload(client, FIXTURES / "admission_form.png", "admission_form", seed["school"].id)
    assert resp.status_code == 200
    upload_body = resp.json()
    assert upload_body["status"] == "done"
    assert upload_body["document_type"] == "admission_form"
    assert upload_body["school_id"] == seed["school"].id
    document_id = upload_body["id"]

    resp = client.get(f"/admin/ocr/documents/{document_id}", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["status"] == "done"
    assert detail["extracted_fields"]["applicant_name"] == "Priya Sharma"
    assert detail["extracted_fields"]["dob"] == "2015-04-01"
    assert detail["raw_text"] is not None
    assert detail["ocr_confidence"] > 0.85
    # admission_form now DOES route for real (AdmissionApplication exists) - but
    # this fixture (see SOURCES.md: "applicant name, DOB, guardian name/phone"
    # only) never contained guardian_email/grade_applied, so it's still correctly
    # not routed - just for a real "missing fields" reason now, not the old
    # "no admissions table exists yet" stub message.
    assert detail["routing"]["routed"] is False
    assert "guardian_email" in detail["routing"]["reason"]
    assert "grade_applied" in detail["routing"]["reason"]
    assert detail["routing"]["suggested_payload"] is None
    assert len(detail["entities"]) == 4

    applicant_entity = next(e for e in detail["entities"] if e["field_name"] == "applicant_name")
    assert applicant_entity["corrected_value"] is None

    resp = client.put(
        f"/admin/ocr/documents/{document_id}/entities/{applicant_entity['id']}",
        params={"school_id": seed["school"].id},
        json={"corrected_value": "Priya A. Sharma"},
    )
    assert resp.status_code == 200
    corrected = resp.json()
    assert corrected["corrected_value"] == "Priya A. Sharma"
    assert corrected["corrected_by"] == seed["admin_user"].id
    assert corrected["corrected_at"] is not None
    assert corrected["field_value"] == "Priya Sharma"  # original OCR value preserved

    resp = client.get(f"/admin/ocr/documents/{document_id}", params={"school_id": seed["school"].id})
    assert resp.json()["extracted_fields"]["applicant_name"] == "Priya A. Sharma"  # correction wins

    _override_user("principal", user_id=seed["principal_user"].id)
    resp = client.post(f"/admin/ocr/documents/{document_id}/reextract", params={"school_id": seed["school"].id}, json={})
    assert resp.status_code == 200
    reextracted = resp.json()
    # Re-extraction supersedes old entities - the correction above doesn't survive
    # since it was tied to the previous entity row (see reextract's own docstring).
    assert reextracted["extracted_fields"]["applicant_name"] == "Priya Sharma"


def test_reextract_with_document_type_override(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _upload(client, FIXTURES / "marksheet.png", "other", seed["school"].id)
    document_id = resp.json()["id"]

    # Uploaded as "other" (no rules -> no fields); after realizing it's actually a
    # marksheet, re-extract with the corrected document_type against the same raw_text.
    detail = client.get(f"/admin/ocr/documents/{document_id}", params={"school_id": seed["school"].id}).json()
    assert detail["extracted_fields"] == {}

    resp = client.post(
        f"/admin/ocr/documents/{document_id}/reextract",
        params={"school_id": seed["school"].id},
        json={"document_type": "marksheet"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_type"] == "marksheet"
    assert body["extracted_fields"]["student_name"] == "Priya Sharma"
    assert body["extracted_fields"]["total_marks"] == "450"


def test_document_1012_reextraction_now_gets_dob_grade_applied_guardian_email_and_routes(client, db_session, seed):
    """Regression test for a real gap found via live testing on document #1012: its
    real raw OCR text (reproduced verbatim below) originally extracted only
    guardian_name/applicant_name/guardian_phone - dob failed on a real regex bug
    (ISO-only date pattern vs. the form's real "12.04.2015" DD.MM.YYYY), and
    grade_applied/guardian_email were never in scope at all. Also confirms routing
    now produces a real pre-fill suggestion instead of the old stub message,
    since AdmissionApplication exists now."""
    from app.models.document import OcrResult

    document = Document(
        uploaded_by=seed["admin_user"].id, school_id=seed["school"].id, document_type="admission_form",
        file_url="x", status="done",
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        OcrResult(
            document_id=document.id,
            raw_text=(
                "ADMISSION APPLICATION FORM\n�Sam School\n\nApplicant Details\n"
                "Applicant Name: New Student\nDate of Birth: 12.04.2015\nGender: Female\n\n"
                "Grade Applied For: 3\n\nGuardian Details\nGuardian Name: P3\n"
                "Guardian Email: p3@sam.in\n\nGuardian Phone: 9876543210\n\nAddress\n\n"
                "123 MG Road, Bengaluru, Karnataka, 560001\n\nPrevious Schoo! (if any)\n\n"
                "Little Stars Primary School\n\nDeclaration\n"
                "| hereby declare that the above information is true to the best of my knowledge.\n\n"
                "Signature: student\nDate: 15-08-2026\n"
            ),
            confidence_score=0.838,
            engine_version="test",
        )
    )
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/ocr/documents/{document.id}/reextract", params={"school_id": seed["school"].id}, json={})
    assert resp.status_code == 200
    body = resp.json()

    fields = body["extracted_fields"]
    assert fields["applicant_name"] == "New Student"
    assert fields["dob"] == "2015-04-12"  # normalized from 12.04.2015
    assert fields["gender"] == "Female"
    assert fields["grade_applied"] == "3"
    assert fields["guardian_name"] == "P3"
    assert fields["guardian_email"] == "p3@sam.in"
    assert fields["guardian_phone"] == "9876543210"

    assert body["routing"]["routed"] is True
    assert body["routing"]["target_table"] == "admission_applications"
    assert body["routing"]["suggested_payload"] == {
        "applicant_name": "New Student",
        "dob": "2015-04-12",
        "guardian_email": "p3@sam.in",
        "grade_applied": "3",
        # Real fix found live: guardian_name/guardian_phone were extracted here but
        # never carried into suggested_payload, so a real accept later created a
        # parent account with full_name=None despite the name being right there.
        "guardian_name": "P3",
        "guardian_phone": "9876543210",
        "school_id": seed["school"].id,
        "ocr_document_ids": [document.id],
    }


def test_low_confidence_field_is_flagged_and_correctable(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _upload(client, FIXTURES / "low_confidence_admission_form.png", "admission_form", seed["school"].id)
    assert resp.status_code == 200
    document_id = resp.json()["id"]

    detail = client.get(f"/admin/ocr/documents/{document_id}", params={"school_id": seed["school"].id}).json()
    assert len(detail["entities"]) >= 1
    low_conf_entities = [e for e in detail["entities"] if e["is_low_confidence"]]
    assert len(low_conf_entities) >= 1

    entity = low_conf_entities[0]
    resp = client.put(
        f"/admin/ocr/documents/{document_id}/entities/{entity['id']}",
        params={"school_id": seed["school"].id},
        json={"corrected_value": "2015-04-01"},
    )
    assert resp.status_code == 200
    assert resp.json()["corrected_value"] == "2015-04-01"


# --- expected_fields / application_id / manual entry ---


def test_detail_includes_expected_fields_for_marksheet(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _upload(client, FIXTURES / "marksheet.png", "marksheet", seed["school"].id)
    document_id = resp.json()["id"]

    detail = client.get(f"/admin/ocr/documents/{document_id}", params={"school_id": seed["school"].id}).json()
    assert set(detail["expected_fields"]) == {"student_name", "roll_number", "total_marks", "percentage"}


def test_application_id_is_null_until_linked(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _upload(client, FIXTURES / "marksheet.png", "marksheet", seed["school"].id)
    document_id = resp.json()["id"]

    detail = client.get(f"/admin/ocr/documents/{document_id}", params={"school_id": seed["school"].id}).json()
    assert detail["application_id"] is None

    listing = client.get("/admin/ocr/documents", params={"school_id": seed["school"].id}).json()
    listed = next(d for d in listing["items"] if d["id"] == document_id)
    assert listed["application_id"] is None


def test_application_id_is_set_once_attached_to_an_application(client, db_session, seed):
    from datetime import date

    from app.models.admissions import AdmissionApplication

    _override_user("admin", user_id=seed["admin_user"].id, school_id=seed["school"].id)
    marksheet_id = _upload(client, FIXTURES / "marksheet.png", "marksheet", seed["school"].id).json()["id"]

    application = AdmissionApplication(
        school_id=seed["school"].id, academic_year="2026-27", applicant_name="Jane Doe", dob=date(2015, 4, 1),
        guardian_email="g@example.com", grade_applied="8", status="submitted", submitted_by=seed["admin_user"].id,
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    attach_resp = client.post(f"/admin/admissions/applications/{application.id}/documents", json={"document_id": marksheet_id})
    assert attach_resp.status_code == 200

    detail = client.get(f"/admin/ocr/documents/{marksheet_id}", params={"school_id": seed["school"].id}).json()
    assert detail["application_id"] == application.id


def test_document_endpoints_survive_a_document_linked_to_two_applications(client, db_session, seed):
    """Regression test for a real crash found live in the real sam school: a
    document that ends up in TWO applications' ocr_document_ids (pre-existing data
    from before admissions.py's attach_document rejected double-linking) used to
    make _linked_application_for_document's .scalar() raise MultipleResultsFound,
    500ing the ENTIRE document list for that school - not just this one document.
    Constructs that exact shape directly (bypassing the now-guarded API) since
    legacy rows like this can still exist regardless of the new guard."""
    from datetime import date

    from app.models.admissions import AdmissionApplication

    document = Document(
        uploaded_by=seed["admin_user"].id, school_id=seed["school"].id, document_type="marksheet", file_url="x", status="done"
    )
    db_session.add(document)
    db_session.flush()

    first_app = AdmissionApplication(
        school_id=seed["school"].id, academic_year="2026-27", applicant_name="First Kid", dob=date(2015, 4, 1),
        guardian_email="first@example.com", grade_applied="8", status="submitted", submitted_by=seed["admin_user"].id,
        ocr_document_ids=[document.id],
    )
    second_app = AdmissionApplication(
        school_id=seed["school"].id, academic_year="2026-27", applicant_name="Second Kid", dob=date(2015, 4, 1),
        guardian_email="second@example.com", grade_applied="8", status="submitted", submitted_by=seed["admin_user"].id,
        ocr_document_ids=[document.id],
    )
    db_session.add_all([first_app, second_app])
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id)
    list_resp = client.get("/admin/ocr/documents", params={"school_id": seed["school"].id})
    assert list_resp.status_code == 200

    detail_resp = client.get(f"/admin/ocr/documents/{document.id}", params={"school_id": seed["school"].id})
    assert detail_resp.status_code == 200
    # Which of the two "wins" is deterministic (lowest id) but not the point - the
    # point is that it resolves to ONE of them instead of crashing.
    assert detail_resp.json()["application_id"] == min(first_app.id, second_app.id)


def test_add_manual_entity_for_a_field_ocr_never_found(client, db_session, seed):
    document = Document(
        uploaded_by=seed["admin_user"].id, school_id=seed["school"].id, document_type="marksheet", file_url="x", status="done"
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        f"/admin/ocr/documents/{document.id}/entities",
        params={"school_id": seed["school"].id},
        json={"field_name": "total_marks", "value": "450"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["extracted_fields"]["total_marks"] == "450"
    entity = next(e for e in body["entities"] if e["field_name"] == "total_marks")
    assert entity["confidence_score"] == 1.0
    assert entity["is_low_confidence"] is False


def test_add_manual_entity_rejects_unknown_field_name(client, db_session, seed):
    document = Document(
        uploaded_by=seed["admin_user"].id, school_id=seed["school"].id, document_type="marksheet", file_url="x", status="done"
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        f"/admin/ocr/documents/{document.id}/entities",
        params={"school_id": seed["school"].id},
        json={"field_name": "not_a_real_field", "value": "x"},
    )
    assert resp.status_code == 400


def test_add_manual_entity_rejects_empty_value(client, db_session, seed):
    document = Document(
        uploaded_by=seed["admin_user"].id, school_id=seed["school"].id, document_type="marksheet", file_url="x", status="done"
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        f"/admin/ocr/documents/{document.id}/entities",
        params={"school_id": seed["school"].id},
        json={"field_name": "total_marks", "value": "   "},
    )
    assert resp.status_code == 400


def test_add_manual_entity_conflicts_when_field_already_has_a_value(client, db_session, seed):
    from app.models.document import ExtractedEntity

    document = Document(
        uploaded_by=seed["admin_user"].id, school_id=seed["school"].id, document_type="marksheet", file_url="x", status="done"
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(ExtractedEntity(document_id=document.id, field_name="total_marks", field_value="450", confidence_score=0.9, is_low_confidence=False))
    db_session.commit()

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        f"/admin/ocr/documents/{document.id}/entities",
        params={"school_id": seed["school"].id},
        json={"field_name": "total_marks", "value": "460"},
    )
    assert resp.status_code == 409


def test_add_manual_entity_401_without_token(client):
    resp = client.post("/admin/ocr/documents/1/entities", params={"school_id": 1}, json={"field_name": "x", "value": "y"})
    assert resp.status_code == 401


def test_add_manual_entity_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/ocr/documents/1/entities", params={"school_id": 1}, json={"field_name": "x", "value": "y"})
    assert resp.status_code == 403


def test_add_manual_entity_404_for_document_in_a_different_school(client, db_session, seed, other_school):
    document = Document(
        uploaded_by=other_school["admin_user"].id, school_id=other_school["school"].id, document_type="marksheet", file_url="x", status="done"
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        f"/admin/ocr/documents/{document.id}/entities",
        params={"school_id": seed["school"].id},
        json={"field_name": "total_marks", "value": "450"},
    )
    assert resp.status_code == 404


def test_correct_entity_rejects_empty_value(client, db_session, seed):
    document = Document(
        uploaded_by=seed["admin_user"].id, school_id=seed["school"].id, document_type="admission_form", file_url="x", status="done"
    )
    db_session.add(document)
    db_session.flush()
    from app.models.document import ExtractedEntity

    entity = ExtractedEntity(document_id=document.id, field_name="applicant_name", field_value="X", confidence_score=0.9, is_low_confidence=False)
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(
        f"/admin/ocr/documents/{document.id}/entities/{entity.id}",
        params={"school_id": seed["school"].id},
        json={"corrected_value": "   "},
    )
    assert resp.status_code == 400


def test_get_document_returns_404_for_missing_document(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/ocr/documents/999999", params={"school_id": seed["school"].id})
    assert resp.status_code == 404


def test_correct_entity_returns_404_for_missing_entity(client, db_session, seed):
    document = Document(
        uploaded_by=seed["admin_user"].id, school_id=seed["school"].id, document_type="admission_form", file_url="x", status="done"
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(
        f"/admin/ocr/documents/{document.id}/entities/999999",
        params={"school_id": seed["school"].id},
        json={"corrected_value": "x"},
    )
    assert resp.status_code == 404


def test_reextract_returns_404_for_missing_document(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/admin/ocr/documents/999999/reextract", params={"school_id": seed["school"].id}, json={})
    assert resp.status_code == 404


def test_reextract_returns_400_when_no_ocr_result_exists(client, db_session, seed):
    document = Document(
        uploaded_by=seed["admin_user"].id, school_id=seed["school"].id, document_type="admission_form", file_url="x", status="queued"
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/ocr/documents/{document.id}/reextract", params={"school_id": seed["school"].id}, json={})
    assert resp.status_code == 400


# --- GET /admin/ocr/documents: list ---


def test_list_documents_401_without_token(client):
    resp = client.get("/admin/ocr/documents", params={"school_id": 1})
    assert resp.status_code == 401


def test_list_documents_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/admin/ocr/documents", params={"school_id": 1})
    assert resp.status_code == 403


def test_list_documents_returns_uploaded_documents(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    id1 = _upload(client, FIXTURES / "admission_form.png", "admission_form", seed["school"].id).json()["id"]
    id2 = _upload(client, FIXTURES / "marksheet.png", "marksheet", seed["school"].id).json()["id"]

    resp = client.get("/admin/ocr/documents", params={"school_id": seed["school"].id})
    assert resp.status_code == 200
    body = resp.json()
    returned_ids = {item["id"] for item in body["items"]}
    assert {id1, id2} <= returned_ids  # own fixtures present, not a global-count assertion

    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[id1]["document_type"] == "admission_form"
    assert by_id[id1]["status"] == "done"
    assert by_id[id1]["processed_at"] is not None
    assert by_id[id1]["school_id"] == seed["school"].id
    # Summary shape only - no extracted_fields/entities/raw_text on the list endpoint.
    assert "extracted_fields" not in by_id[id1]
    assert "entities" not in by_id[id1]


def test_list_documents_filters_by_status_and_document_type(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    admission_id = _upload(client, FIXTURES / "admission_form.png", "admission_form", seed["school"].id).json()["id"]
    marksheet_id = _upload(client, FIXTURES / "marksheet.png", "marksheet", seed["school"].id).json()["id"]

    resp = client.get("/admin/ocr/documents", params={"school_id": seed["school"].id, "document_type": "marksheet"})
    ids = {item["id"] for item in resp.json()["items"]}
    assert marksheet_id in ids
    assert admission_id not in ids

    resp = client.get("/admin/ocr/documents", params={"school_id": seed["school"].id, "status": "done"})
    ids = {item["id"] for item in resp.json()["items"]}
    assert {admission_id, marksheet_id} <= ids

    resp = client.get("/admin/ocr/documents", params={"school_id": seed["school"].id, "status": "failed"})
    ids = {item["id"] for item in resp.json()["items"]}
    assert admission_id not in ids
    assert marksheet_id not in ids


def test_list_documents_paginates(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    uploaded_ids = [
        _upload(client, FIXTURES / "id_proof.png", "id_proof", seed["school"].id).json()["id"] for _ in range(3)
    ]

    resp = client.get("/admin/ocr/documents", params={"school_id": seed["school"].id, "page": 1, "page_size": 2})
    body = resp.json()
    assert resp.status_code == 200
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    assert body["total"] >= 3  # at least our own 3 fixtures, other tests may add more in the same run

    # Walk pages until every one of our own uploaded ids has been seen - proves
    # pagination doesn't drop or duplicate rows across pages, without asserting
    # on a brittle global total.
    seen_ids = set()
    page = 1
    while len(seen_ids) < body["total"] and page <= body["total"]:
        page_resp = client.get("/admin/ocr/documents", params={"school_id": seed["school"].id, "page": page, "page_size": 2})
        items = page_resp.json()["items"]
        if not items:
            break
        seen_ids.update(item["id"] for item in items)
        page += 1
    assert set(uploaded_ids) <= seen_ids


def test_list_documents_rejects_invalid_pagination(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/ocr/documents", params={"school_id": seed["school"].id, "page": 0})
    assert resp.status_code == 400
    resp = client.get("/admin/ocr/documents", params={"school_id": seed["school"].id, "page_size": 0})
    assert resp.status_code == 400


# --- Cross-tenant isolation: the reliability-audit regression test ------------------


@pytest.fixture()
def other_school(db_session):
    """A second, entirely separate school/admin - for proving Admin A cannot
    reach Admin B's documents, the exact leak an empirical audit test found
    (two fresh schools, one admin per school, Admin A's list included Admin B's
    document)."""
    school = School(name="Other School")
    db_session.add(school)
    db_session.flush()
    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    admin_user = User(
        supabase_id=uuid.uuid4(), email=f"other-admin-{uuid.uuid4()}@example.com", role_id=admin_role.id, school_id=school.id
    )
    db_session.add(admin_user)
    db_session.commit()
    db_session.refresh(admin_user)
    return {"school": school, "admin_user": admin_user}


def test_list_documents_does_not_leak_across_schools(client, seed, other_school):
    _override_user("admin", user_id=seed["admin_user"].id)
    own_id = _upload(client, FIXTURES / "admission_form.png", "admission_form", seed["school"].id).json()["id"]

    _override_user("admin", user_id=other_school["admin_user"].id)
    other_id = _upload(client, FIXTURES / "marksheet.png", "marksheet", other_school["school"].id).json()["id"]

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/ocr/documents", params={"school_id": seed["school"].id})
    ids = {item["id"] for item in resp.json()["items"]}
    assert own_id in ids
    assert other_id not in ids


def test_get_document_returns_404_for_document_in_a_different_school(client, seed, other_school):
    _override_user("admin", user_id=other_school["admin_user"].id)
    other_id = _upload(client, FIXTURES / "admission_form.png", "admission_form", other_school["school"].id).json()["id"]

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get(f"/admin/ocr/documents/{other_id}", params={"school_id": seed["school"].id})
    assert resp.status_code == 404


def test_correct_entity_returns_404_for_document_in_a_different_school(client, seed, other_school):
    _override_user("admin", user_id=other_school["admin_user"].id)
    resp = _upload(client, FIXTURES / "admission_form.png", "admission_form", other_school["school"].id)
    other_id = resp.json()["id"]
    entity_id = client.get(f"/admin/ocr/documents/{other_id}", params={"school_id": other_school["school"].id}).json()["entities"][0]["id"]

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(
        f"/admin/ocr/documents/{other_id}/entities/{entity_id}",
        params={"school_id": seed["school"].id},
        json={"corrected_value": "hijacked"},
    )
    assert resp.status_code == 404


def test_reextract_returns_404_for_document_in_a_different_school(client, seed, other_school):
    _override_user("admin", user_id=other_school["admin_user"].id)
    other_id = _upload(client, FIXTURES / "admission_form.png", "admission_form", other_school["school"].id).json()["id"]

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/ocr/documents/{other_id}/reextract", params={"school_id": seed["school"].id}, json={})
    assert resp.status_code == 404
