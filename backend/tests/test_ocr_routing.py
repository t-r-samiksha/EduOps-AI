from app.services.ocr_routing import ROUTING_TARGETS, RoutingResult, route_entities


def test_default_registry_stubs_every_known_document_type():
    # Checked before writing ocr_routing.py: no admissions table, no grades table -
    # every document_type is currently a documented stub. This test locks in that
    # honesty; it should start failing (and get updated deliberately) the day a
    # real target table lands and a real handler is wired in.
    for document_type in ("admission_form", "marksheet", "id_proof", "other"):
        result = route_entities(document_type, {"some_field": "some_value"})
        assert result.routed is False
        assert result.target_table is None
        assert result.reason  # non-empty, explains why


def test_unknown_document_type_is_not_routed():
    result = route_entities("nonexistent_type", {})
    assert result.routed is False
    assert result.target_table is None


def test_routing_mechanism_works_when_a_real_target_exists():
    # Proves the *mechanism* generically without pretending a real table exists in
    # this codebase today - see ocr_routing.py's module docstring.
    def fake_handler(entities: dict[str, str]) -> RoutingResult:
        return RoutingResult(routed=True, target_table="fake_admissions", reason="routed for test purposes")

    fake_registry = dict(ROUTING_TARGETS)
    fake_registry["admission_form"] = fake_handler

    result = route_entities("admission_form", {"applicant_name": "Alex Kim"}, registry=fake_registry)
    assert result.routed is True
    assert result.target_table == "fake_admissions"

    # The real, unmodified default registry is untouched by the fake one above.
    real_result = route_entities("admission_form", {"applicant_name": "Alex Kim"})
    assert real_result.routed is False


def test_registry_override_does_not_affect_other_document_types():
    fake_registry = dict(ROUTING_TARGETS)
    fake_registry["marksheet"] = lambda entities: RoutingResult(routed=True, target_table="fake_grades", reason="test")

    admission_result = route_entities("admission_form", {}, registry=fake_registry)
    assert admission_result.routed is False
