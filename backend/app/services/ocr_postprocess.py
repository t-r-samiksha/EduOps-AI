"""Document-type-specific structured-entity extraction from raw OCR text.

Deliberately regex/pattern-based, not an NLP/NER pipeline - honest for demo scale
(a handful of document layouts with predictable "Label: value" lines) and far easier
to reason about, debug, and demo than a trained model would be. Each document_type's
rules are just a list of (field_name, compiled regex with one capture group) - add a
new document_type by adding a new list, no other code changes needed.

PER-FIELD CONFIDENCE
----------------------
Tesseract gives per-*word* confidence, not per-regex-match confidence. For each
matched field, this module looks up the confidence of the OCR words that make up the
matched value (via services/ocr_engine.py's OcrTextResult.words) and averages them -
a real, if approximate, per-field signal rather than reusing one flat document-wide
score for every field. Falls back to the overall OCR confidence only if none of the
matched value's words can be found in the word list (e.g. the regex captured
something OCR run together differently than word-tokenized).
"""

from __future__ import annotations

import re
import string
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.services.ocr_engine import WordConfidence

LOW_CONFIDENCE_THRESHOLD = 0.6
"""Below this, is_low_confidence=True and the field should be surfaced for manual
review/correction rather than trusted outright."""

DEFAULT_FALLBACK_CONFIDENCE = 0.5
"""Used only when a matched value's words can't be found in the OCR word list at
all - an honest "we don't really know" middle value, not a fabricated high score."""

_DATE_VALUE_PATTERN = r"(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-\d{1,2}-\d{4})"
"""Matches a date value in ISO (YYYY-MM-DD) or common DD.MM.YYYY / DD/MM/YYYY /
DD-MM-YYYY forms. Found live: a real uploaded admission form (document #1012)
wrote "Date of Birth: 12.04.2015" - the original ISO-only value pattern matched
the label fine but the whole regex.search() still failed (a regex match is all-
or-nothing), so `dob` was silently skipped entirely, no error. Real forms are
filled in by office staff/parents in whatever format they're used to, not
necessarily ISO."""

_DATE_INPUT_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y")


def normalize_date(value: str) -> str:
    """Best-effort normalize a captured date value to ISO (YYYY-MM-DD) so every
    downstream consumer (the correction UI, the admissions routing pre-fill -
    see services/ocr_routing.py) sees one consistent format regardless of which
    real-world format the original form used. Falls back to the raw captured
    value, unchanged, if none of the known formats parse it - an honest
    "couldn't normalize" rather than a fabricated/guessed date."""
    for fmt in _DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


FIELD_NORMALIZERS: dict[str, Callable[[str], str]] = {
    "dob": normalize_date,
    "date_of_birth": normalize_date,
}
"""Applied AFTER confidence scoring (see extract_entities) but before the value is
stored - _confidence_for_value looks up the ORIGINAL OCR-recognized token, which
would never be found post-normalization (OCR genuinely produced "12.04.2015", not
"2015-04-12"), so normalizing first would silently collapse every dob's
confidence to DEFAULT_FALLBACK_CONFIDENCE regardless of the real OCR read."""


@dataclass(frozen=True)
class ExtractedField:
    field_name: str
    field_value: str
    confidence_score: float
    is_low_confidence: bool


# document_type -> [(field_name, compiled regex with exactly one capture group), ...]
# Whitespace between a label's colon and its value is matched with [ \t]* (not \s*)
# deliberately - \s* also matches newlines, so on a blank field it would silently
# cross the line break and capture the *next* label's line as this field's value.
EXTRACTION_RULES: dict[str, list[tuple[str, re.Pattern]]] = {
    "admission_form": [
        ("applicant_name", re.compile(r"Applicant Name:[ \t]*(.+)", re.IGNORECASE)),
        ("dob", re.compile(rf"(?:Date of Birth|DOB):[ \t]*{_DATE_VALUE_PATTERN}", re.IGNORECASE)),
        ("gender", re.compile(r"Gender:[ \t]*(.+)", re.IGNORECASE)),
        ("grade_applied", re.compile(r"Grade Applied(?: For)?:[ \t]*(.+)", re.IGNORECASE)),
        ("guardian_name", re.compile(r"Guardian Name:[ \t]*(.+)", re.IGNORECASE)),
        ("guardian_email", re.compile(r"Guardian Email:[ \t]*(\S+@\S+)", re.IGNORECASE)),
        ("guardian_phone", re.compile(r"Guardian Phone:[ \t]*([\d\-\+ ]{8,})", re.IGNORECASE)),
    ],
    # address/previous_school are deliberately NOT extracted yet - on a real form
    # (see document #1012) their label and value sit on separate lines ("Address\n\n
    # 123 MG Road...", "Previous Schoo! (if any)\n\nLittle Stars..."), which needs a
    # genuinely different multi-line pattern shape, not a same-line "Label: value"
    # regex like every field above - a deliberate scope cut, not an oversight.
    "marksheet": [
        ("student_name", re.compile(r"Student Name:[ \t]*(.+)", re.IGNORECASE)),
        ("roll_number", re.compile(r"Roll (?:No|Number)\.?:[ \t]*(\S+)", re.IGNORECASE)),
        ("total_marks", re.compile(r"Total Marks:[ \t]*(\d+)", re.IGNORECASE)),
        ("percentage", re.compile(r"Percentage:[ \t]*([\d.]+)%?", re.IGNORECASE)),
    ],
    "id_proof": [
        ("full_name", re.compile(r"Name:[ \t]*(.+)", re.IGNORECASE)),
        ("id_number", re.compile(r"ID (?:No|Number)\.?:[ \t]*(\S+)", re.IGNORECASE)),
        ("date_of_birth", re.compile(rf"(?:Date of Birth|DOB):[ \t]*{_DATE_VALUE_PATTERN}", re.IGNORECASE)),
    ],
    "other": [],
    # No rules for "other" by design - it's an intentional catch-all for documents
    # that don't fit a known layout; extraction correctly finds nothing for it.
}


def expected_fields(document_type: str) -> list[str]:
    """The full set of fields this document_type's rules look for - regardless of
    whether OCR actually found each one on a given document. Lets a caller (the
    manual-entry UI) show a real, editable row for a field that legitimately went
    missing (e.g. a garbled "Total Marks" line), rather than that field silently
    not existing anywhere."""
    return [field_name for field_name, _ in EXTRACTION_RULES.get(document_type, [])]


def _strip_punct(token: str) -> str:
    return token.strip(string.punctuation).lower()


def _confidence_for_value(value: str, words: list[WordConfidence]) -> float:
    remaining = list(words)
    matched: list[float] = []
    for token in value.split():
        target = _strip_punct(token)
        if not target:
            continue
        for i, w in enumerate(remaining):
            if _strip_punct(w.word) == target:
                matched.append(w.confidence)
                del remaining[i]
                break
    if not matched:
        return DEFAULT_FALLBACK_CONFIDENCE
    return sum(matched) / len(matched)


def extract_entities(
    raw_text: str, document_type: str, words: list[WordConfidence] | None = None
) -> list[ExtractedField]:
    rules = EXTRACTION_RULES.get(document_type, [])
    words = words or []

    results = []
    for field_name, pattern in rules:
        match = pattern.search(raw_text)
        if not match:
            continue
        value = match.group(1).strip()
        if not value:
            continue
        # Confidence must be scored against the RAW captured text - the OCR word
        # list only ever contains what OCR actually read (e.g. "12.04.2015"), never
        # a normalized form (see FIELD_NORMALIZERS' docstring).
        confidence = _confidence_for_value(value, words)
        normalizer = FIELD_NORMALIZERS.get(field_name)
        if normalizer is not None:
            value = normalizer(value)
        results.append(
            ExtractedField(
                field_name=field_name,
                field_value=value,
                confidence_score=round(confidence, 3),
                is_low_confidence=confidence < LOW_CONFIDENCE_THRESHOLD,
            )
        )
    return results
