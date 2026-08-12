from pathlib import Path

from app.services.ocr_engine import WordConfidence, extract_text
from app.services.ocr_postprocess import (
    LOW_CONFIDENCE_THRESHOLD,
    extract_entities,
)

FIXTURES = Path(__file__).parent / "fixtures" / "documents"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _words(*pairs: tuple[str, float]) -> list[WordConfidence]:
    return [WordConfidence(word=w, confidence=c) for w, c in pairs]


# --- per-document_type extraction correctness, against real OCR fixtures ---


def test_admission_form_extracts_all_fields():
    ocr = extract_text(_read("admission_form.png"))
    fields = extract_entities(ocr.raw_text, "admission_form", ocr.words)
    by_name = {f.field_name: f for f in fields}

    assert by_name["applicant_name"].field_value == "Priya Sharma"
    assert by_name["dob"].field_value == "2015-04-01"
    assert by_name["guardian_name"].field_value == "Rajesh Sharma"
    assert by_name["guardian_phone"].field_value == "9876543210"
    assert all(not f.is_low_confidence for f in fields)


def test_marksheet_extracts_all_fields():
    ocr = extract_text(_read("marksheet.png"))
    fields = extract_entities(ocr.raw_text, "marksheet", ocr.words)
    by_name = {f.field_name: f for f in fields}

    assert by_name["student_name"].field_value == "Priya Sharma"
    assert by_name["roll_number"].field_value == "8A-01"
    assert by_name["total_marks"].field_value == "450"
    assert by_name["percentage"].field_value == "90.0"


def test_id_proof_extracts_all_fields():
    ocr = extract_text(_read("id_proof.png"))
    fields = extract_entities(ocr.raw_text, "id_proof", ocr.words)
    by_name = {f.field_name: f for f in fields}

    assert by_name["full_name"].field_value == "Rajesh Sharma"
    assert by_name["id_number"].field_value == "AB1234567"
    assert by_name["date_of_birth"].field_value == "1985-06-15"


def test_other_document_type_extracts_nothing_by_design():
    fields = extract_entities("some random text that matches nothing", "other", [])
    assert fields == []


def test_unknown_document_type_extracts_nothing():
    fields = extract_entities("Applicant Name: Someone", "not_a_real_type", [])
    assert fields == []


# --- low-confidence flagging ---


def test_degraded_document_flags_low_confidence_field():
    ocr = extract_text(_read("low_confidence_admission_form.png"))
    fields = extract_entities(ocr.raw_text, "admission_form", ocr.words)

    assert len(fields) >= 1
    assert any(f.is_low_confidence for f in fields)
    for f in fields:
        if f.is_low_confidence:
            assert f.confidence_score < LOW_CONFIDENCE_THRESHOLD


def test_confidence_threshold_boundary_via_constructed_words():
    raw_text = "Applicant Name: Alex Kim"
    high_conf_words = _words(("Applicant", 0.9), ("Name:", 0.9), ("Alex", 0.9), ("Kim", 0.9))
    low_conf_words = _words(("Applicant", 0.3), ("Name:", 0.3), ("Alex", 0.3), ("Kim", 0.3))

    high = extract_entities(raw_text, "admission_form", high_conf_words)[0]
    low = extract_entities(raw_text, "admission_form", low_conf_words)[0]

    assert high.is_low_confidence is False
    assert low.is_low_confidence is True
    assert high.confidence_score > low.confidence_score


def test_per_field_confidence_derived_from_matching_words_not_flat_average():
    # applicant_name's words are high-confidence, dob's words are low-confidence -
    # the two fields must NOT end up with the same confidence score.
    raw_text = "Applicant Name: Alex Kim\nDOB: 2010-01-01"
    words = _words(
        ("Applicant", 0.95), ("Name:", 0.95), ("Alex", 0.95), ("Kim", 0.95),
        ("DOB:", 0.2), ("2010-01-01", 0.2),
    )
    fields = extract_entities(raw_text, "admission_form", words)
    by_name = {f.field_name: f for f in fields}

    assert by_name["applicant_name"].confidence_score > 0.9
    assert by_name["dob"].confidence_score < 0.3


def test_missing_word_data_falls_back_to_default_confidence():
    fields = extract_entities("Applicant Name: Alex Kim", "admission_form", [])
    assert len(fields) == 1
    assert fields[0].confidence_score == 0.5
    assert fields[0].is_low_confidence is True  # 0.5 < LOW_CONFIDENCE_THRESHOLD (0.6)


def test_empty_capture_group_is_skipped():
    fields = extract_entities("Applicant Name:   \nDOB: 2010-01-01", "admission_form", [])
    names = {f.field_name for f in fields}
    assert "applicant_name" not in names
    assert "dob" in names
