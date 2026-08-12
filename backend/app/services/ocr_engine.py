"""Tesseract-based OCR text extraction.

SYSTEM DEPENDENCY WARNING - read before touching this file
--------------------------------------------------------------
Unlike every other pip package added to this project, `pytesseract` is a thin
subprocess wrapper around a *separately-installed system binary* (the real Tesseract
OCR engine) - it does NOT bundle the engine itself, unlike e.g. `dlib-bin` in the
attendance-CV work. `pip install pytesseract` alone gives you an import that raises
`pytesseract.TesseractNotFoundError` (surfaced here as OcrEngineError) the moment you
try to actually OCR anything. This is exactly the category of dependency that broke
`dlib` on this machine before - flagging loudly so nobody loses time on it again.

Setup (documented in CLAUDE.md's Commands section too):
  - Windows (this machine): `winget install --id UB-Mannheim.TesseractOCR`, which
    installs to `C:\\Program Files\\Tesseract-OCR\\tesseract.exe` by default. If it
    isn't on PATH, set `TESSERACT_CMD` in `.env` to the full binary path.
  - Linux/CI: `apt-get install tesseract-ocr` (Debian/Ubuntu) or your distro's
    equivalent package. There is no pip-installable substitute for the engine
    itself - `check_tesseract_available()` below is provided specifically so
    callers (and tests) can detect and report this cleanly instead of a confusing
    stack trace.

Decoupled from the ORM like timetable_solver.py/attendance_cv.py: takes raw image
bytes, returns a plain dataclass - testable standalone with fixture images, no DB.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

import pytesseract
from PIL import Image, UnidentifiedImageError

_TESSERACT_CMD = os.environ.get("TESSERACT_CMD")
if _TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD
elif os.name == "nt":
    _default_windows_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_default_windows_path):
        pytesseract.pytesseract.tesseract_cmd = _default_windows_path


class OcrEngineError(Exception):
    """The Tesseract binary itself isn't available/working - distinct from a normal
    "no text found in this image" result, which is not an error."""


class InvalidImageError(Exception):
    """Image bytes could not be decoded."""


@dataclass(frozen=True)
class WordConfidence:
    word: str
    confidence: float
    """0..1."""


@dataclass(frozen=True)
class OcrTextResult:
    raw_text: str
    confidence_score: float | None
    """0..1 mean word-level confidence, or None if no word was confidently recognized
    at all (e.g. a blank image)."""
    engine_version: str
    words: list[WordConfidence] = field(default_factory=list)
    """Word-level detail, used by ocr_postprocess.py to derive per-field confidence
    rather than reusing one flat overall score for every extracted field."""


def check_tesseract_available() -> bool:
    """True if the Tesseract binary is installed and runnable - check this before
    calling extract_text in a context where you want a clean error rather than a
    TesseractNotFoundError stack trace."""
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _decode_image(image_bytes: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        return image
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError("Could not decode image data - not a supported image format") from exc


def extract_text(image_bytes: bytes) -> OcrTextResult:
    image = _decode_image(image_bytes)

    try:
        raw_text = pytesseract.image_to_string(image)
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        version = str(pytesseract.get_tesseract_version())
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrEngineError(
            "Tesseract binary not found on this machine - see this module's docstring for install instructions"
        ) from exc

    words = [
        WordConfidence(word=text, confidence=conf / 100.0)
        for text, conf in zip(data.get("text", []), data.get("conf", []))
        if text.strip() and conf != -1
    ]
    confidence_score = (sum(w.confidence for w in words) / len(words)) if words else None

    return OcrTextResult(
        raw_text=raw_text, confidence_score=confidence_score, engine_version=f"tesseract {version}", words=words
    )
