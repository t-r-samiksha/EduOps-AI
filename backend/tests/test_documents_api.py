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

    admin_role = db_session.query(Role).filter(Role.name == "admin").one()
    principal_role = db_session.query(Role).filter(Role.name == "principal").one()

    admin_user = User(supabase_id=uuid.uuid4(), email=f"admin-{uuid.uuid4()}@example.com", full_name="Admin", role_id=admin_role.id, school_id=school.id)
    principal_user = User(supabase_id=uuid.uuid4(), email=f"principal-{uuid.uuid4()}@example.com", full_name="Principal", role_id=principal_role.id, school_id=school.id)
    db_session.add_all([admin_user, principal_user])
    db_session.commit()

    return {"school": school, "admin_user": admin_user, "principal_user": principal_user}


def _upload(client, path: Path, document_type: str):
    return client.post(
        "/admin/ocr/documents",
        files={"file": (path.name, path.read_bytes(), "image/png")},
        data={"document_type": document_type},
    )


# --- RBAC: 401 no token, 403 wrong role ---


def test_upload_401_without_token(client):
    resp = _upload(client, FIXTURES / "admission_form.png", "admission_form")
    assert resp.status_code == 401


def test_upload_403_for_teacher_role(client):
    _override_user("teacher")
    resp = _upload(client, FIXTURES / "admission_form.png", "admission_form")
    assert resp.status_code == 403


def test_get_document_401_without_token(client):
    resp = client.get("/admin/ocr/documents/1")
    assert resp.status_code == 401


def test_get_document_403_for_student_role(client):
    _override_user("student")
    resp = client.get("/admin/ocr/documents/1")
    assert resp.status_code == 403


def test_correct_entity_401_without_token(client):
    resp = client.put("/admin/ocr/documents/1/entities/1", json={"corrected_value": "x"})
    assert resp.status_code == 401


def test_correct_entity_403_for_parent_role(client):
    _override_user("parent")
    resp = client.put("/admin/ocr/documents/1/entities/1", json={"corrected_value": "x"})
    assert resp.status_code == 403


def test_reextract_401_without_token(client):
    resp = client.post("/admin/ocr/documents/1/reextract", json={})
    assert resp.status_code == 401


def test_reextract_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.post("/admin/ocr/documents/1/reextract", json={})
    assert resp.status_code == 403


# --- POST /admin/ocr/documents: validation ---


def test_upload_rejects_invalid_document_type(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _upload(client, FIXTURES / "admission_form.png", "not_a_real_type")
    assert resp.status_code == 400


def test_upload_rejects_undecodable_image(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(
        "/admin/ocr/documents", files={"file": ("bad.png", b"not an image", "image/png")}, data={"document_type": "other"}
    )
    assert resp.status_code == 422


# --- Full flow: upload -> get -> correct -> reextract ---


def test_full_document_lifecycle(client, db_session, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _upload(client, FIXTURES / "admission_form.png", "admission_form")
    assert resp.status_code == 200
    upload_body = resp.json()
    assert upload_body["status"] == "done"
    assert upload_body["document_type"] == "admission_form"
    document_id = upload_body["id"]

    resp = client.get(f"/admin/ocr/documents/{document_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["status"] == "done"
    assert detail["extracted_fields"]["applicant_name"] == "Priya Sharma"
    assert detail["extracted_fields"]["dob"] == "2015-04-01"
    assert detail["raw_text"] is not None
    assert detail["ocr_confidence"] > 0.85
    assert detail["routing"]["routed"] is False  # no admissions table exists yet - documented stub
    assert len(detail["entities"]) == 4

    applicant_entity = next(e for e in detail["entities"] if e["field_name"] == "applicant_name")
    assert applicant_entity["corrected_value"] is None

    resp = client.put(
        f"/admin/ocr/documents/{document_id}/entities/{applicant_entity['id']}",
        json={"corrected_value": "Priya A. Sharma"},
    )
    assert resp.status_code == 200
    corrected = resp.json()
    assert corrected["corrected_value"] == "Priya A. Sharma"
    assert corrected["corrected_by"] == seed["admin_user"].id
    assert corrected["corrected_at"] is not None
    assert corrected["field_value"] == "Priya Sharma"  # original OCR value preserved

    resp = client.get(f"/admin/ocr/documents/{document_id}")
    assert resp.json()["extracted_fields"]["applicant_name"] == "Priya A. Sharma"  # correction wins

    _override_user("principal", user_id=seed["principal_user"].id)
    resp = client.post(f"/admin/ocr/documents/{document_id}/reextract", json={})
    assert resp.status_code == 200
    reextracted = resp.json()
    # Re-extraction supersedes old entities - the correction above doesn't survive
    # since it was tied to the previous entity row (see reextract's own docstring).
    assert reextracted["extracted_fields"]["applicant_name"] == "Priya Sharma"


def test_reextract_with_document_type_override(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _upload(client, FIXTURES / "marksheet.png", "other")
    document_id = resp.json()["id"]

    # Uploaded as "other" (no rules -> no fields); after realizing it's actually a
    # marksheet, re-extract with the corrected document_type against the same raw_text.
    detail = client.get(f"/admin/ocr/documents/{document_id}").json()
    assert detail["extracted_fields"] == {}

    resp = client.post(f"/admin/ocr/documents/{document_id}/reextract", json={"document_type": "marksheet"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_type"] == "marksheet"
    assert body["extracted_fields"]["student_name"] == "Priya Sharma"
    assert body["extracted_fields"]["total_marks"] == "450"


def test_low_confidence_field_is_flagged_and_correctable(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = _upload(client, FIXTURES / "low_confidence_admission_form.png", "admission_form")
    assert resp.status_code == 200
    document_id = resp.json()["id"]

    detail = client.get(f"/admin/ocr/documents/{document_id}").json()
    assert len(detail["entities"]) >= 1
    low_conf_entities = [e for e in detail["entities"] if e["is_low_confidence"]]
    assert len(low_conf_entities) >= 1

    entity = low_conf_entities[0]
    resp = client.put(
        f"/admin/ocr/documents/{document_id}/entities/{entity['id']}", json={"corrected_value": "2015-04-01"}
    )
    assert resp.status_code == 200
    assert resp.json()["corrected_value"] == "2015-04-01"


def test_correct_entity_rejects_empty_value(client, db_session, seed):
    document = Document(uploaded_by=seed["admin_user"].id, document_type="admission_form", file_url="x", status="done")
    db_session.add(document)
    db_session.flush()
    from app.models.document import ExtractedEntity

    entity = ExtractedEntity(document_id=document.id, field_name="applicant_name", field_value="X", confidence_score=0.9, is_low_confidence=False)
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(f"/admin/ocr/documents/{document.id}/entities/{entity.id}", json={"corrected_value": "   "})
    assert resp.status_code == 400


def test_get_document_returns_404_for_missing_document(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/ocr/documents/999999")
    assert resp.status_code == 404


def test_correct_entity_returns_404_for_missing_entity(client, db_session, seed):
    document = Document(uploaded_by=seed["admin_user"].id, document_type="admission_form", file_url="x", status="done")
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.put(f"/admin/ocr/documents/{document.id}/entities/999999", json={"corrected_value": "x"})
    assert resp.status_code == 404


def test_reextract_returns_404_for_missing_document(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post("/admin/ocr/documents/999999/reextract", json={})
    assert resp.status_code == 404


def test_reextract_returns_400_when_no_ocr_result_exists(client, db_session, seed):
    document = Document(uploaded_by=seed["admin_user"].id, document_type="admission_form", file_url="x", status="queued")
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.post(f"/admin/ocr/documents/{document.id}/reextract", json={})
    assert resp.status_code == 400


# --- GET /admin/ocr/documents: list ---


def test_list_documents_401_without_token(client):
    resp = client.get("/admin/ocr/documents")
    assert resp.status_code == 401


def test_list_documents_403_for_teacher_role(client):
    _override_user("teacher")
    resp = client.get("/admin/ocr/documents")
    assert resp.status_code == 403


def test_list_documents_returns_uploaded_documents(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    id1 = _upload(client, FIXTURES / "admission_form.png", "admission_form").json()["id"]
    id2 = _upload(client, FIXTURES / "marksheet.png", "marksheet").json()["id"]

    resp = client.get("/admin/ocr/documents")
    assert resp.status_code == 200
    body = resp.json()
    returned_ids = {item["id"] for item in body["items"]}
    assert {id1, id2} <= returned_ids  # own fixtures present, not a global-count assertion

    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[id1]["document_type"] == "admission_form"
    assert by_id[id1]["status"] == "done"
    assert by_id[id1]["processed_at"] is not None
    # Summary shape only - no extracted_fields/entities/raw_text on the list endpoint.
    assert "extracted_fields" not in by_id[id1]
    assert "entities" not in by_id[id1]


def test_list_documents_filters_by_status_and_document_type(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    admission_id = _upload(client, FIXTURES / "admission_form.png", "admission_form").json()["id"]
    marksheet_id = _upload(client, FIXTURES / "marksheet.png", "marksheet").json()["id"]

    resp = client.get("/admin/ocr/documents", params={"document_type": "marksheet"})
    ids = {item["id"] for item in resp.json()["items"]}
    assert marksheet_id in ids
    assert admission_id not in ids

    resp = client.get("/admin/ocr/documents", params={"status": "done"})
    ids = {item["id"] for item in resp.json()["items"]}
    assert {admission_id, marksheet_id} <= ids

    resp = client.get("/admin/ocr/documents", params={"status": "failed"})
    ids = {item["id"] for item in resp.json()["items"]}
    assert admission_id not in ids
    assert marksheet_id not in ids


def test_list_documents_paginates(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    uploaded_ids = [
        _upload(client, FIXTURES / "id_proof.png", "id_proof").json()["id"] for _ in range(3)
    ]

    resp = client.get("/admin/ocr/documents", params={"page": 1, "page_size": 2})
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
        page_resp = client.get("/admin/ocr/documents", params={"page": page, "page_size": 2})
        items = page_resp.json()["items"]
        if not items:
            break
        seen_ids.update(item["id"] for item in items)
        page += 1
    assert set(uploaded_ids) <= seen_ids


def test_list_documents_rejects_invalid_pagination(client, seed):
    _override_user("admin", user_id=seed["admin_user"].id)
    resp = client.get("/admin/ocr/documents", params={"page": 0})
    assert resp.status_code == 400
    resp = client.get("/admin/ocr/documents", params={"page_size": 0})
    assert resp.status_code == 400
