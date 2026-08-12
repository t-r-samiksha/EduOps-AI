from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.document import Document, ExtractedEntity, OcrResult
from app.services.auth import CurrentUser, require_role
from app.services.ocr_engine import InvalidImageError, OcrEngineError, WordConfidence, extract_text
from app.services.ocr_postprocess import extract_entities
from app.services.ocr_routing import route_entities

router = APIRouter(tags=["document-ocr"])

VALID_DOCUMENT_TYPES = ("marksheet", "admission_form", "id_proof", "other")


def _words_to_metadata(words: list[WordConfidence]) -> dict:
    """Persists word-level OCR confidence into OcrResult.ocr_metadata (a free-form
    JSONB field) so POST .../reextract can recompute genuine per-field confidence
    from the stored raw_text without needing the original image again."""
    return {"words": [{"word": w.word, "confidence": w.confidence} for w in words]}


def _metadata_to_words(metadata: dict | None) -> list[WordConfidence]:
    if not metadata:
        return []
    return [WordConfidence(word=w["word"], confidence=w["confidence"]) for w in metadata.get("words", [])]


class DocumentCreateOut(BaseModel):
    id: int
    document_type: str
    status: str
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EntityOut(BaseModel):
    id: int
    field_name: str
    field_value: str
    confidence_score: float
    is_low_confidence: bool
    corrected_value: str | None
    corrected_by: int | None
    corrected_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class RoutingOut(BaseModel):
    routed: bool
    target_table: str | None
    reason: str


class DocumentDetailOut(BaseModel):
    id: int
    document_type: str
    status: str
    uploaded_at: datetime
    processed_at: datetime | None
    extracted_fields: dict[str, str]
    """field_name -> value, using corrected_value where a correction exists - matches
    the original api-contract.md stub's shape."""
    entities: list[EntityOut]
    """Full per-field detail (confidence, correction state) for the correction UI -
    an addition beyond the original stub, needed to know which entity_id to PUT to."""
    raw_text: str | None
    ocr_confidence: float | None
    routing: RoutingOut | None
    """Transparency into services/ocr_routing.py's outcome for this document_type -
    see that module's docstring for why every document_type is currently a stub."""
    error: str | None


def _build_detail(db: Session, document: Document) -> DocumentDetailOut:
    ocr_result = db.query(OcrResult).filter(OcrResult.document_id == document.id).one_or_none()
    entities = db.query(ExtractedEntity).filter(ExtractedEntity.document_id == document.id).all()

    extracted_fields = {e.field_name: (e.corrected_value if e.corrected_value is not None else e.field_value) for e in entities}
    routing = route_entities(document.document_type, extracted_fields) if entities else None

    return DocumentDetailOut(
        id=document.id,
        document_type=document.document_type,
        status=document.status,
        uploaded_at=document.uploaded_at,
        processed_at=document.processed_at,
        extracted_fields=extracted_fields,
        entities=[EntityOut.model_validate(e) for e in entities],
        raw_text=ocr_result.raw_text if ocr_result else None,
        ocr_confidence=ocr_result.confidence_score if ocr_result else None,
        routing=RoutingOut(routed=routing.routed, target_table=routing.target_table, reason=routing.reason) if routing else None,
        error="OCR processing failed for this document" if document.status == "failed" else None,
    )


@router.post("/admin/ocr/documents", response_model=DocumentCreateOut)
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if document_type not in VALID_DOCUMENT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"document_type must be one of {VALID_DOCUMENT_TYPES}")

    document = Document(
        uploaded_by=user.id, document_type=document_type, file_url="pending", status="queued"
    )
    db.add(document)
    db.flush()
    # Descriptive reference only - see Document's docstring: the image itself is
    # processed in-memory below and not persisted anywhere durable.
    document.file_url = f"documents/{document.id}/{file.filename or 'upload'}"

    image_bytes = await file.read()
    document.status = "processing"
    db.flush()

    try:
        ocr_result = extract_text(image_bytes)
    except InvalidImageError as exc:
        document.status = "failed"
        document.processed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except OcrEngineError as exc:
        document.status = "failed"
        document.processed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    db.add(
        OcrResult(
            document_id=document.id,
            raw_text=ocr_result.raw_text,
            confidence_score=ocr_result.confidence_score,
            engine_version=ocr_result.engine_version,
            ocr_metadata=_words_to_metadata(ocr_result.words),
        )
    )

    fields = extract_entities(ocr_result.raw_text, document_type, ocr_result.words)
    for f in fields:
        db.add(
            ExtractedEntity(
                document_id=document.id,
                field_name=f.field_name,
                field_value=f.field_value,
                confidence_score=f.confidence_score,
                is_low_confidence=f.is_low_confidence,
            )
        )

    document.status = "done"
    document.processed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(document)

    return DocumentCreateOut.model_validate(document)


@router.get("/admin/ocr/documents/{document_id}", response_model=DocumentDetailOut)
def get_document(
    document_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    document = db.query(Document).filter(Document.id == document_id).one_or_none()
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return _build_detail(db, document)


class CorrectionRequest(BaseModel):
    corrected_value: str


@router.put("/admin/ocr/documents/{document_id}/entities/{entity_id}", response_model=EntityOut)
def correct_entity(
    document_id: int,
    entity_id: int,
    body: CorrectionRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if not body.corrected_value.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "corrected_value must not be empty")

    entity = (
        db.query(ExtractedEntity)
        .filter(ExtractedEntity.id == entity_id, ExtractedEntity.document_id == document_id)
        .one_or_none()
    )
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Extracted entity not found")

    entity.corrected_value = body.corrected_value
    entity.corrected_by = user.id
    entity.corrected_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(entity)
    return EntityOut.model_validate(entity)


class ReextractRequest(BaseModel):
    document_type: str | None = None
    """Override - e.g. re-extract after realizing the document was mis-classified.
    Omit to re-run with the document's existing document_type (a plain retry)."""


@router.post("/admin/ocr/documents/{document_id}/reextract", response_model=DocumentDetailOut)
def reextract_document(
    document_id: int,
    body: ReextractRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    document = db.query(Document).filter(Document.id == document_id).one_or_none()
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    ocr_result = db.query(OcrResult).filter(OcrResult.document_id == document_id).one_or_none()
    if ocr_result is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No OCR result exists for this document yet - nothing to re-extract from")

    if body.document_type is not None:
        if body.document_type not in VALID_DOCUMENT_TYPES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"document_type must be one of {VALID_DOCUMENT_TYPES}")
        document.document_type = body.document_type

    # Old entities (and any corrections against them) are tied to whatever
    # document_type produced them - superseded by a fresh extraction rather than
    # merged, since field names may not even carry over across a type change.
    db.query(ExtractedEntity).filter(ExtractedEntity.document_id == document_id).delete()

    words = _metadata_to_words(ocr_result.ocr_metadata)
    fields = extract_entities(ocr_result.raw_text, document.document_type, words)
    for f in fields:
        db.add(
            ExtractedEntity(
                document_id=document.id,
                field_name=f.field_name,
                field_value=f.field_value,
                confidence_score=f.confidence_score,
                is_low_confidence=f.is_low_confidence,
            )
        )

    document.processed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(document)

    return _build_detail(db, document)
