from app.services.ocr_routing import ROUTING_TARGETS, RoutingResult, route_entities

REAL_ADMISSION_ENTITIES = {
    "applicant_name": "New Student",
    "dob": "2015-04-12",
    "guardian_email": "p3@sam.in",
    "grade_applied": "3",
}


def test_marksheet_id_proof_and_other_are_still_documented_stubs():
    # No grades table (Person B's gradebook) and no generic document-subject
    # linkage for id_proof/other exist yet - these three stay honest stubs. See
    # test_admission_form_* below for the one document_type that now routes for
    # real (AdmissionApplication landed in a later session than this module).
    for document_type in ("marksheet", "id_proof", "other"):
        result = route_entities(document_type, {"some_field": "some_value"})
        assert result.routed is False
        assert result.target_table is None
        assert result.reason  # non-empty, explains why


def test_unknown_document_type_is_not_routed():
    result = route_entities("nonexistent_type", {})
    assert result.routed is False
    assert result.target_table is None


# --- admission_form: the real (non-stub) handler ---


def test_admission_form_routes_when_all_required_fields_present():
    """Regression test for the routing stub going stale: AdmissionApplication and
    POST /admin/admissions/applications are real now (Fees & Admissions session),
    so a document with every required field extracted must produce a real,
    ready-to-submit suggestion - not the old "no admissions table exists" stub
    message a live document detail page was still showing."""
    result = route_entities("admission_form", REAL_ADMISSION_ENTITIES)
    assert result.routed is True
    assert result.target_table == "admission_applications"
    assert result.suggested_payload == {
        "applicant_name": "New Student",
        "dob": "2015-04-12",
        "guardian_email": "p3@sam.in",
        "grade_applied": "3",
    }


def test_admission_form_suggested_payload_normalizes_dob_defensively():
    """A human's corrected_value might not be ISO even if the original OCR
    extraction was - the routing handler re-normalizes defensively rather than
    passing a human correction straight through."""
    entities = {**REAL_ADMISSION_ENTITIES, "dob": "12.04.2015"}
    result = route_entities("admission_form", entities)
    assert result.routed is True
    assert result.suggested_payload["dob"] == "2015-04-12"


def test_admission_form_not_routed_when_a_required_field_is_missing():
    for missing_field in REAL_ADMISSION_ENTITIES:
        entities = {k: v for k, v in REAL_ADMISSION_ENTITIES.items() if k != missing_field}
        result = route_entities("admission_form", entities)
        assert result.routed is False
        assert result.target_table == "admission_applications"
        assert missing_field in result.reason
        assert result.suggested_payload is None


def test_admission_form_not_routed_when_no_entities_at_all():
    result = route_entities("admission_form", {})
    assert result.routed is False
    assert result.suggested_payload is None


# --- registry mechanism (generic, independent of which document_type is real) ---


def test_routing_mechanism_works_with_an_injected_fake_handler():
    def fake_handler(entities: dict[str, str]) -> RoutingResult:
        return RoutingResult(routed=True, target_table="fake_admissions", reason="routed for test purposes")

    fake_registry = dict(ROUTING_TARGETS)
    fake_registry["admission_form"] = fake_handler

    result = route_entities("admission_form", {"applicant_name": "Alex Kim"}, registry=fake_registry)
    assert result.routed is True
    assert result.target_table == "fake_admissions"

    # The real, unmodified default registry is untouched by the fake one above -
    # and (unlike before) genuinely does route when every required field is present.
    real_result = route_entities("admission_form", REAL_ADMISSION_ENTITIES)
    assert real_result.routed is True
    assert real_result.target_table == "admission_applications"


def test_registry_override_does_not_affect_other_document_types():
    fake_registry = dict(ROUTING_TARGETS)
    fake_registry["marksheet"] = lambda entities: RoutingResult(routed=True, target_table="fake_grades", reason="test")

    # Empty entities - genuinely missing every required field, so the real
    # admission_form handler still correctly declines to route.
    admission_result = route_entities("admission_form", {}, registry=fake_registry)
    assert admission_result.routed is False
