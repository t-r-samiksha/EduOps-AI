from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.attendance_cv import (
    InvalidImageError,
    KnownFace,
    MultipleFacesDetectedError,
    NoFaceDetectedError,
    enroll_face,
    recognize_faces,
)

# See tests/fixtures/faces/SOURCES.md for image provenance (public-domain historical
# portraits from Wikimedia Commons).
FIXTURES = Path(__file__).parent / "fixtures" / "faces"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _blank_image_bytes() -> bytes:
    blank = np.full((200, 200, 3), 255, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", blank)
    assert ok
    return buf.tobytes()


def test_enroll_face_extracts_128d_embedding():
    embedding = enroll_face(_read("person_a_1.jpg"))
    assert len(embedding) == 128
    assert all(isinstance(v, float) for v in embedding)


def test_enroll_face_raises_on_multiple_faces():
    with pytest.raises(MultipleFacesDetectedError):
        enroll_face(_read("classroom_two_faces.jpg"))


def test_enroll_face_raises_on_no_face_detected():
    with pytest.raises(NoFaceDetectedError):
        enroll_face(_blank_image_bytes())


def test_enroll_face_raises_on_undecodable_image():
    with pytest.raises(InvalidImageError):
        enroll_face(b"this is not image data")


def test_recognize_faces_matches_same_person_across_photos():
    embedding_a = enroll_face(_read("person_a_1.jpg"))
    known = [KnownFace(student_id=1, embedding=embedding_a)]

    result = recognize_faces(_read("person_a_2.jpg"), known)

    assert len(result.matches) == 1
    assert result.matches[0].student_id == 1
    assert result.matches[0].confidence > 0.5
    assert result.unmatched == []


def test_recognize_faces_does_not_match_a_different_person():
    embedding_a = enroll_face(_read("person_a_1.jpg"))
    known = [KnownFace(student_id=1, embedding=embedding_a)]

    result = recognize_faces(_read("person_b_1.jpg"), known)

    assert result.matches == []
    assert len(result.unmatched) == 1
    assert result.unmatched[0].best_confidence is not None
    assert result.unmatched[0].best_confidence < 0.5


def test_recognize_faces_classroom_photo_matches_both_enrolled_students():
    embedding_a = enroll_face(_read("person_a_1.jpg"))
    embedding_b = enroll_face(_read("person_b_1.jpg"))
    known = [KnownFace(student_id=1, embedding=embedding_a), KnownFace(student_id=2, embedding=embedding_b)]

    result = recognize_faces(_read("classroom_two_faces.jpg"), known)

    assert {m.student_id for m in result.matches} == {1, 2}
    assert result.unmatched == []


def test_recognize_faces_with_no_known_embeddings_returns_all_unmatched():
    result = recognize_faces(_read("classroom_two_faces.jpg"), [])

    assert result.matches == []
    assert len(result.unmatched) == 2
    assert all(u.best_confidence is None for u in result.unmatched)


def test_recognize_faces_flags_needs_review_below_stricter_threshold():
    embedding_a = enroll_face(_read("person_a_1.jpg"))
    known = [KnownFace(student_id=1, embedding=embedding_a)]

    # person_a_2 is a real (non-zero) distance from person_a_1 - an artificially
    # strict review_distance_threshold forces needs_review=True deterministically,
    # proving the two-tier match/review thresholding actually wires through.
    result = recognize_faces(
        _read("person_a_2.jpg"), known, match_distance_threshold=0.6, review_distance_threshold=0.05
    )

    assert len(result.matches) == 1
    assert result.matches[0].needs_review is True


def test_recognize_faces_confident_match_not_flagged_for_review():
    embedding_a = enroll_face(_read("person_a_1.jpg"))
    known = [KnownFace(student_id=1, embedding=embedding_a)]

    result = recognize_faces(
        _read("person_a_2.jpg"), known, match_distance_threshold=0.6, review_distance_threshold=0.45
    )

    assert len(result.matches) == 1
    assert result.matches[0].needs_review is False


def test_recognize_faces_rejects_inverted_thresholds():
    with pytest.raises(ValueError):
        recognize_faces(_read("person_a_1.jpg"), [], match_distance_threshold=0.4, review_distance_threshold=0.6)
