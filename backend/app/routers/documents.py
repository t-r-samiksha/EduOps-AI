from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admissions import AdmissionApplication
from app.models.document import Document, ExtractedEntity, OcrResult
from app.models.school import School
from app.services.audit_log import write_audit_log
from app.services.auth import CurrentUser, require_role
from app.services.ocr_engine import InvalidImageError, OcrEngineError, WordConfidence, extract_text
from app.services.ocr_postprocess import expected_fields, extract_entities
from app.services.ocr_routing import route_entities

router = APIRouter(tags=["document-ocr"])

VALID_DOCUMENT_TYPES = ("marksheet", "admission_form", "id_proof", "other")
DEFAULT_PAGE_SIZE = 20


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
    school_id: int | None
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
    suggested_payload: dict[str, str | int | list[int]] | None = None
    """Only set when routed=True - a pre-filled request body for the real
    downstream endpoint (e.g. POST /admin/admissions/applications), merging
    services/ocr_routing.py's extracted-field subset with school_id/
    ocr_document_ids from this Document row. Never auto-submitted anywhere - the
    frontend shows this as an editable, pre-filled form for a human to review and
    submit for real (see ocr_routing.py's module docstring for why)."""


def _linked_application_for_document(db: Session, document: Document) -> tuple[int, str] | None:
    """Which AdmissionApplication (if any) already has this document linked via its
    ocr_document_ids - the JSONB `@>` containment operator, not a Python-side scan.
    Powers the OCR page's drag-and-drop linking (a document can only be a valid drop
    TARGET, i.e. gain other documents attached to it, once some application already
    references it - see routers/admissions.py's attach_document), lets the frontend
    show which application any already-linked document belongs to, and returns the
    applicant's real name too - the board shows this next to every card in a group
    (not just the admission_form's own extracted fields, which a marksheet/id_proof
    don't share the same field names for anyway) so every card names whose file it
    actually is.

    Uses `.first()`, NOT `.scalar()` - found live (real sam school data, a document
    linked to two applications from before attach_document rejected double-linking)
    that `.scalar()` raises `MultipleResultsFound` the moment more than one
    application references the same document, 500ing the entire document list.
    Ordered by id so which one "wins" is at least deterministic (the oldest/first
    application to have claimed this document), not query-plan-dependent."""
    row = (
        db.query(AdmissionApplication.id, AdmissionApplication.applicant_name)
        .filter(AdmissionApplication.school_id == document.school_id, AdmissionApplication.ocr_document_ids.contains([document.id]))
        .order_by(AdmissionApplication.id)
        .limit(1)
        .first()
    )
    return (row.id, row.applicant_name) if row is not None else None


class DocumentDetailOut(BaseModel):
    id: int
    school_id: int | None
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
    expected_fields: list[str]
    """Every field this document_type's extraction rules look for, regardless of
    whether OCR actually found it here - lets the review UI show a real, editable
    row for a field that's genuinely missing (e.g. a garbled "Total Marks" line)
    instead of that field just not existing anywhere on the page."""
    application_id: int | None
    """Set once this document is linked into some AdmissionApplication's
    ocr_document_ids - null if it's still unlinked. See _linked_application_for_document."""
    application_applicant_name: str | None
    """The linked application's real applicant_name - null exactly when application_id
    is null. Not derived from this document's OWN extracted fields (a marksheet says
    student_name, an id_proof says full_name, not necessarily identical strings) -
    always the one canonical name off the application itself."""
    raw_text: str | None
    ocr_confidence: float | None
    routing: RoutingOut | None
    """Transparency into services/ocr_routing.py's outcome for this document_type -
    see that module's docstring for why every document_type is currently a stub."""
    error: str | None


def _build_detail(db: Session, document: Document) -> DocumentDetailOut:
    ocr_result = db.query(OcrResult).filter(OcrResult.document_id == document.id).one_or_none()
    entities = db.query(ExtractedEntity).filter(ExtractedEntity.document_id == document.id).all()
    linked_application = _linked_application_for_document(db, document)

    extracted_fields = {e.field_name: (e.corrected_value if e.corrected_value is not None else e.field_value) for e in entities}
    routing = route_entities(document.document_type, extracted_fields) if entities else None

    suggested_payload = None
    if routing and routing.routed and routing.suggested_payload is not None:
        # ocr_routing.py only ever sees the extracted-field dict, not the Document
        # row - it has no opinion on school_id/ocr_document_ids. Those two ARE
        # fully derivable here (unlike academic_year, which only a human can
        # supply), so this is the one place they're merged in.
        suggested_payload = {
            **routing.suggested_payload,
            "school_id": document.school_id,
            "ocr_document_ids": [document.id],
        }

    return DocumentDetailOut(
        id=document.id,
        school_id=document.school_id,
        document_type=document.document_type,
        status=document.status,
        uploaded_at=document.uploaded_at,
        processed_at=document.processed_at,
        extracted_fields=extracted_fields,
        entities=[EntityOut.model_validate(e) for e in entities],
        expected_fields=expected_fields(document.document_type),
        application_id=linked_application[0] if linked_application else None,
        application_applicant_name=linked_application[1] if linked_application else None,
        raw_text=ocr_result.raw_text if ocr_result else None,
        ocr_confidence=ocr_result.confidence_score if ocr_result else None,
        routing=(
            RoutingOut(
                routed=routing.routed,
                target_table=routing.target_table,
                reason=routing.reason,
                suggested_payload=suggested_payload,
            )
            if routing
            else None
        ),
        error="OCR processing failed for this document" if document.status == "failed" else None,
    )


@router.post("/admin/ocr/documents", response_model=DocumentCreateOut)
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    school_id: int = Form(...),
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if document_type not in VALID_DOCUMENT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"document_type must be one of {VALID_DOCUMENT_TYPES}")
    if db.query(School).filter(School.id == school_id).one_or_none() is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown school_id {school_id}")

    document = Document(
        uploaded_by=user.id, school_id=school_id, document_type=document_type, file_url="pending", status="queued"
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


class DocumentSummaryOut(BaseModel):
    id: int
    school_id: int | None
    document_type: str
    status: str
    uploaded_at: datetime
    processed_at: datetime | None
    application_id: int | None
    """Same meaning as DocumentDetailOut's own field - lets the list view group/nest
    documents by the application they're already linked to without a separate
    detail fetch per row."""
    application_applicant_name: str | None
    """Same meaning as DocumentDetailOut's own field - the board shows this next to
    every card in a group so an admin sees whose file it is at a glance."""


class DocumentsListResponse(BaseModel):
    items: list[DocumentSummaryOut]
    total: int
    page: int
    page_size: int


@router.get("/admin/ocr/documents", response_model=DocumentsListResponse)
def list_documents(
    school_id: int,
    status_filter: str | None = Query(None, alias="status"),
    document_type: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """Not in the original stub - added because the frontend's document review
    screen had no real way to browse previously-uploaded documents, only fetch one
    by a known id (see GET .../{document_id} below). Summary shape only (no
    extracted_fields/entities/raw_text) - that detail stays on the single-document
    GET, same split as e.g. GET /admin/admissions/applications vs a single
    application's full record.

    `school_id` is REQUIRED (a reliability-audit fix - this had zero tenant
    scoping before, confirmed empirically to leak another school's documents).
    A row with no school_id (pre-migration legacy - see the migration's docstring)
    never matches any real school_id here, so it's simply never listed."""
    if page < 1 or page_size < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "page and page_size must be positive")

    query = db.query(Document).filter(Document.school_id == school_id)
    if status_filter is not None:
        query = query.filter(Document.status == status_filter)
    if document_type is not None:
        query = query.filter(Document.document_type == document_type)

    total = query.count()
    # Secondary sort by id: uploaded_at alone can tie (Postgres freezes now() for
    # the whole transaction, so rows inserted in quick succession within one
    # transaction can share an identical timestamp), which makes pagination
    # non-deterministic - rows could be skipped or duplicated across pages.
    rows = (
        query.order_by(Document.uploaded_at.desc(), Document.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    def _summary(d: Document) -> DocumentSummaryOut:
        linked_application = _linked_application_for_document(db, d)
        return DocumentSummaryOut(
            id=d.id, school_id=d.school_id, document_type=d.document_type, status=d.status,
            uploaded_at=d.uploaded_at, processed_at=d.processed_at,
            application_id=linked_application[0] if linked_application else None,
            application_applicant_name=linked_application[1] if linked_application else None,
        )

    items = [_summary(d) for d in rows]
    return DocumentsListResponse(items=items, total=total, page=page, page_size=page_size)


def _get_scoped_document_or_404(db: Session, document_id: int, school_id: int) -> Document:
    """Same-shape 404 whether the document doesn't exist at all or exists but
    belongs to a different school - doesn't distinguish the two, so a caller
    can't use this to probe which document ids exist in another tenant."""
    document = (
        db.query(Document).filter(Document.id == document_id, Document.school_id == school_id).one_or_none()
    )
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


@router.get("/admin/ocr/documents/{document_id}", response_model=DocumentDetailOut)
def get_document(
    document_id: int,
    school_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    document = _get_scoped_document_or_404(db, document_id, school_id)
    return _build_detail(db, document)


class CorrectionRequest(BaseModel):
    corrected_value: str


@router.put("/admin/ocr/documents/{document_id}/entities/{entity_id}", response_model=EntityOut)
def correct_entity(
    document_id: int,
    entity_id: int,
    school_id: int,
    body: CorrectionRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if not body.corrected_value.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "corrected_value must not be empty")
    _get_scoped_document_or_404(db, document_id, school_id)

    entity = (
        db.query(ExtractedEntity)
        .filter(ExtractedEntity.id == entity_id, ExtractedEntity.document_id == document_id)
        .one_or_none()
    )
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Extracted entity not found")

    previous_value = entity.field_value if entity.corrected_value is None else entity.corrected_value
    entity.corrected_value = body.corrected_value
    entity.corrected_by = user.id
    entity.corrected_at = datetime.now(timezone.utc)
    write_audit_log(
        db, actor_id=user.id, action="correct", entity_type="extracted_entities", entity_id=entity.id,
        detail={"field_name": entity.field_name, "previous_value": previous_value, "corrected_value": body.corrected_value},
    )
    db.commit()
    db.refresh(entity)
    return EntityOut.model_validate(entity)


class ManualEntityRequest(BaseModel):
    field_name: str
    value: str


@router.post("/admin/ocr/documents/{document_id}/entities", response_model=DocumentDetailOut)
def add_manual_entity(
    document_id: int,
    school_id: int,
    body: ManualEntityRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    """For a field OCR never found at all (no ExtractedEntity row exists yet) -
    genuinely different from PUT .../entities/{entity_id} above, which corrects an
    EXISTING (if wrong/low-confidence) value. A garbled marksheet can lose a field
    entirely (see the real "Total Marks" -> "otal Mark" OCR failure this was built
    for) - there is no entity id to PUT to in that case, so this creates one.
    Human-entered, so trusted outright: confidence_score=1.0, is_low_confidence=False,
    no corrected_value (nothing to correct - this value IS the record)."""
    document = _get_scoped_document_or_404(db, document_id, school_id)

    if not body.field_name.strip() or not body.value.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "field_name and value must not be empty")
    if body.field_name not in expected_fields(document.document_type):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{body.field_name}' is not a field this document_type ({document.document_type}) extracts",
        )

    existing = (
        db.query(ExtractedEntity)
        .filter(ExtractedEntity.document_id == document_id, ExtractedEntity.field_name == body.field_name)
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{body.field_name}' already has a value on this document - use PUT .../entities/{{entity_id}} to correct it instead",
        )

    entity = ExtractedEntity(
        document_id=document_id, field_name=body.field_name, field_value=body.value.strip(),
        confidence_score=1.0, is_low_confidence=False,
    )
    db.add(entity)
    db.flush()  # need entity.id for the audit log entry below
    write_audit_log(
        db, actor_id=user.id, action="manual_entry", entity_type="extracted_entities", entity_id=entity.id,
        detail={"document_id": document_id, "field_name": body.field_name, "value": body.value.strip()},
    )
    db.commit()
    db.refresh(document)
    return _build_detail(db, document)


class ReextractRequest(BaseModel):
    document_type: str | None = None
    """Override - e.g. re-extract after realizing the document was mis-classified.
    Omit to re-run with the document's existing document_type (a plain retry)."""


@router.post("/admin/ocr/documents/{document_id}/reextract", response_model=DocumentDetailOut)
def reextract_document(
    document_id: int,
    school_id: int,
    body: ReextractRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    document = _get_scoped_document_or_404(db, document_id, school_id)

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
