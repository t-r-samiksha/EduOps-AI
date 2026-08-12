"""Face detection + recognition for CV-mode attendance.

Deliberately decoupled from the ORM, like timetable_solver.py: callers pass raw
image bytes and plain dataclasses, get plain dataclasses back. Detection uses
OpenCV for image decoding; recognition (face location + 128-d embedding) uses
dlib via face_recognition. This keeps the pipeline runnable and testable with
fixture images, without a live camera feed or the DB.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import face_recognition
import numpy as np

FACE_EMBEDDING_DIM = 128

# face_recognition/dlib's face_distance is a Euclidean distance between 128-d
# encodings; ~0.6 is the library's own conventional "same person" cutoff.
# match_distance_threshold: below this, a detected face is considered a match at
# all. review_distance_threshold: below this (stricter), the match is confident
# enough to auto-accept; between the two, it's a match but flagged for manual
# review. confidence is a simple monotonic proxy (1 - distance, clamped to
# [0, 1]) - not a calibrated probability, but good enough to rank/threshold on.
DEFAULT_MATCH_DISTANCE_THRESHOLD = 0.6
DEFAULT_REVIEW_DISTANCE_THRESHOLD = 0.45


class FaceCVError(Exception):
    """Base class for attendance_cv errors."""


class InvalidImageError(FaceCVError):
    """Image bytes could not be decoded."""


class NoFaceDetectedError(FaceCVError):
    """No face found where exactly one was expected (enrollment)."""


class MultipleFacesDetectedError(FaceCVError):
    """More than one face found where exactly one was expected (enrollment)."""


FaceLocation = tuple[int, int, int, int]
"""(top, right, bottom, left) pixel coordinates, matching face_recognition's convention."""


@dataclass(frozen=True)
class KnownFace:
    student_id: int
    embedding: list[float]


@dataclass(frozen=True)
class FaceMatch:
    student_id: int
    confidence: float
    face_location: FaceLocation
    needs_review: bool
    """True if this is a match but below the confident-auto-accept threshold."""


@dataclass(frozen=True)
class UnmatchedFace:
    face_location: FaceLocation
    best_confidence: float | None
    """Confidence of the closest known face, or None if there were no known
    embeddings to compare against at all."""


@dataclass(frozen=True)
class RecognitionResult:
    matches: list[FaceMatch]
    unmatched: list[UnmatchedFace]


def _decode_image(image_bytes: bytes) -> np.ndarray:
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if bgr is None:
        raise InvalidImageError("Could not decode image data - not a supported image format")
    return np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def _detect_and_encode(image_bytes: bytes, upsample: int) -> tuple[list[FaceLocation], list[np.ndarray]]:
    rgb_image = _decode_image(image_bytes)
    locations = face_recognition.face_locations(rgb_image, number_of_times_to_upsample=upsample)
    encodings = face_recognition.face_encodings(rgb_image, known_face_locations=locations)
    return locations, encodings


def _distance_to_confidence(distance: float) -> float:
    return max(0.0, min(1.0, 1.0 - distance))


def enroll_face(image_bytes: bytes, *, upsample: int = 2) -> list[float]:
    """Extract a single face embedding from a reference photo. Raises
    NoFaceDetectedError / MultipleFacesDetectedError if the photo doesn't contain
    exactly one face - enrolling an ambiguous photo would silently corrupt matching
    later, so this refuses rather than guessing."""
    _locations, encodings = _detect_and_encode(image_bytes, upsample)

    if not encodings:
        raise NoFaceDetectedError("No face detected in the reference photo")
    if len(encodings) > 1:
        raise MultipleFacesDetectedError(
            f"Expected exactly one face in the reference photo, found {len(encodings)}"
        )
    return encodings[0].tolist()


def recognize_faces(
    image_bytes: bytes,
    known_embeddings: list[KnownFace],
    *,
    match_distance_threshold: float = DEFAULT_MATCH_DISTANCE_THRESHOLD,
    review_distance_threshold: float = DEFAULT_REVIEW_DISTANCE_THRESHOLD,
    upsample: int = 2,
) -> RecognitionResult:
    """Detect every face in a classroom photo and match each against the known
    embeddings (typically every enrolled student in the class). A detected face
    with no known embedding within match_distance_threshold is unmatched; one
    within match_distance_threshold but not within the stricter
    review_distance_threshold is still a match, but flagged needs_review=True."""
    if review_distance_threshold > match_distance_threshold:
        raise ValueError("review_distance_threshold must be <= match_distance_threshold")

    locations, encodings = _detect_and_encode(image_bytes, upsample)

    known_matrix = np.array([k.embedding for k in known_embeddings], dtype=float) if known_embeddings else None

    matches: list[FaceMatch] = []
    unmatched: list[UnmatchedFace] = []

    for location, encoding in zip(locations, encodings):
        if known_matrix is None or len(known_matrix) == 0:
            unmatched.append(UnmatchedFace(face_location=location, best_confidence=None))
            continue

        distances = np.linalg.norm(known_matrix - encoding, axis=1)
        best_idx = int(np.argmin(distances))
        best_distance = float(distances[best_idx])
        confidence = _distance_to_confidence(best_distance)

        if best_distance <= match_distance_threshold:
            matches.append(
                FaceMatch(
                    student_id=known_embeddings[best_idx].student_id,
                    confidence=confidence,
                    face_location=location,
                    needs_review=best_distance > review_distance_threshold,
                )
            )
        else:
            unmatched.append(UnmatchedFace(face_location=location, best_confidence=confidence))

    return RecognitionResult(matches=matches, unmatched=unmatched)
