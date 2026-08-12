from pathlib import Path

import pytest

from app.services.ocr_engine import (
    InvalidImageError,
    check_tesseract_available,
    extract_text,
)

# See tests/fixtures/documents/SOURCES.md - synthetic, self-authored renders.
FIXTURES = Path(__file__).parent / "fixtures" / "documents"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_tesseract_is_available_in_this_environment():
    # If this fails, every other test in this file will too - a clear, named
    # failure here is much more useful than a TesseractNotFoundError deep in a
    # traceback. See ocr_engine.py's docstring for the install step.
    assert check_tesseract_available() is True


def test_extracts_clean_admission_form_text():
    result = extract_text(_read("admission_form.png"))
    assert "Applicant Name" in result.raw_text
    assert "Priya Sharma" in result.raw_text
    assert "2015-04-01" in result.raw_text


def test_clean_document_has_high_confidence():
    result = extract_text(_read("admission_form.png"))
    assert result.confidence_score is not None
    assert result.confidence_score > 0.85


def test_word_level_confidences_are_populated():
    result = extract_text(_read("admission_form.png"))
    assert len(result.words) > 0
    for w in result.words:
        assert 0.0 <= w.confidence <= 1.0
        assert w.word.strip()


def test_engine_version_is_reported():
    result = extract_text(_read("admission_form.png"))
    assert "tesseract" in result.engine_version.lower()


def test_degraded_image_has_lower_confidence_than_clean_one():
    clean = extract_text(_read("admission_form.png"))
    degraded = extract_text(_read("low_confidence_admission_form.png"))
    assert degraded.confidence_score is not None
    assert degraded.confidence_score < clean.confidence_score
    assert degraded.confidence_score < 0.6


def test_blank_image_yields_no_confident_words():
    from PIL import Image
    import io

    blank = Image.new("RGB", (200, 100), color="white")
    buf = io.BytesIO()
    blank.save(buf, format="PNG")

    result = extract_text(buf.getvalue())
    assert result.confidence_score is None
    assert result.words == []


def test_invalid_image_bytes_raise():
    with pytest.raises(InvalidImageError):
        extract_text(b"this is not an image")


def test_marksheet_and_id_proof_fixtures_extract_expected_text():
    marksheet = extract_text(_read("marksheet.png"))
    assert "Roll No" in marksheet.raw_text
    assert "450" in marksheet.raw_text

    id_proof = extract_text(_read("id_proof.png"))
    assert "AB1234567" in id_proof.raw_text
