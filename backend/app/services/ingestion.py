"""Resource -> kb_chunks ingestion: fetch, chunk, embed, upsert.

SYNCHRONOUS BY DESIGN, no queue and no webhook
--------------------------------------------------
`ingest_resource()` is called inline from POST /resources/upload, following the
`POST /admin/fees/schedules` precedent in routers/fees.py - that endpoint calls the
invoicing routine directly on creation rather than deferring it. There is no webhook
layer here for the same reason there is none anywhere else in this codebase: no
inbound webhook receiver exists to copy a pattern from, and there is no second service
to call one. The APScheduler job in app/scheduler.py is the safety net that catches
anything whose inline ingestion failed (`resources.indexed_at IS NULL`), not the
primary path.

IDEMPOTENT
-------------
Every chunk is written against the unique key (source_type, source_id, chunk_index).
Re-ingesting an edited resource overwrites chunk N in place; chunks beyond the new
length are deleted. Re-ingesting an unchanged resource is a no-op in content terms.
Without that key a reindex would silently double the corpus and bias retrieval toward
whatever had been ingested most often.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge import SOURCE_TYPE_RESOURCE, KbChunk
from app.models.resource import Resource
from app.services.llm import embed_documents
from app.services.supabase_admin import download_resource_file

PDF_MIME_TYPES = {"application/pdf"}


def extract_text(raw: bytes, *, mime_type: str, filename: str = "") -> str:
    """Bytes -> plain text, by type. Plain text/markdown pass through; PDFs go through
    pypdf's per-page text extraction.

    PDF SUPPORT IS TEXT-LAYER ONLY. pypdf reads the text a PDF already carries; it does
    NOT do OCR. A scanned PDF (pages that are images of text) extracts to nothing, and
    that is reported as a 422 by the upload endpoint rather than being ingested as an
    empty resource. This project does have a Tesseract OCR pipeline
    (services/ocr_engine.py), but it targets the separate `documents` admin flow and is
    not wired in here - bridging the two is real work, not a one-liner.
    """
    if mime_type in PDF_MIME_TYPES or filename.lower().endswith(".pdf"):
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        # Page-joined with blank lines so chunk_text's paragraph-preferring splitter
        # treats a page boundary as a natural break point.
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        return "\n\n".join(p for p in pages if p)

    return raw.decode("utf-8", errors="replace")


CHUNK_TARGET_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
_CHARS_PER_TOKEN = 4
"""Rough English average. We chunk on characters rather than running a real tokenizer:
adding tiktoken (an OpenAI tokenizer) to size chunks for a Gemini model would be both a
new dependency and the wrong tokenizer. The target is a comfortable chunk size, not an
exact token budget, so a 4-chars-per-token approximation is entirely adequate."""

CHUNK_TARGET_CHARS = CHUNK_TARGET_TOKENS * _CHARS_PER_TOKEN
CHUNK_OVERLAP_CHARS = CHUNK_OVERLAP_TOKENS * _CHARS_PER_TOKEN


def chunk_text(text: str, *, target_chars: int = CHUNK_TARGET_CHARS, overlap_chars: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    """Split into overlapping chunks, preferring paragraph then sentence boundaries.

    Overlap exists so a fact that straddles a boundary is not lost: a question about
    the last sentence of chunk 3 still retrieves usable context because that sentence
    also appears at the start of chunk 4.

    Splitting on a blank line first keeps markdown headings attached to the text they
    introduce, which matters for retrieval - a chunk that begins mid-table with no
    heading is far less useful as an answer's context.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= target_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + target_chars, len(text))
        if end < len(text):
            # Prefer a paragraph break, then a sentence end, then a space - searching
            # backwards from the hard limit within the last 40% of the window.
            window_floor = start + int(target_chars * 0.6)
            for separator in ("\n\n", ". ", "\n", " "):
                candidate = text.rfind(separator, window_floor, end)
                if candidate != -1:
                    end = candidate + len(separator)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def ingest_resource(db: Session, resource_id: int) -> int:
    """Chunk, embed and upsert one resource. Returns the number of chunks written.

    Does NOT commit - the caller owns the transaction, same convention as
    services/notify.py and services/audit_log.py. That is what lets the upload endpoint
    roll the resource row back if ingestion fails, rather than leaving a resource that
    exists but is permanently unsearchable.
    """
    resource = db.query(Resource).filter(Resource.id == resource_id).one_or_none()
    if resource is None:
        raise ValueError(f"Unknown resource_id {resource_id}")

    raw = download_resource_file(resource.file_url)
    text = extract_text(raw, mime_type=resource.mime_type, filename=resource.file_url)
    chunks = chunk_text(text)
    if not chunks:
        resource.needs_reindex = False
        resource.indexed_at = datetime.now(timezone.utc)
        return 0

    vectors = embed_documents(chunks)

    existing = {
        row.chunk_index: row
        for row in db.scalars(
            select(KbChunk).where(
                KbChunk.source_type == SOURCE_TYPE_RESOURCE,
                KbChunk.source_id == resource.id,
            )
        )
    }

    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
        row = existing.get(index)
        if row is None:
            db.add(
                KbChunk(
                    source_type=SOURCE_TYPE_RESOURCE,
                    source_id=resource.id,
                    chunk_index=index,
                    chunk_text=chunk,
                    embedding=vector,
                    school_id=resource.school_id,
                    grade_level=resource.grade_level,
                    subject_id=resource.subject_id,
                )
            )
        else:
            # Update in place rather than delete-and-insert so the unique key is never
            # transiently violated within the transaction.
            row.chunk_text = chunk
            row.embedding = vector
            row.school_id = resource.school_id
            row.grade_level = resource.grade_level
            row.subject_id = resource.subject_id
            row.indexed_at = datetime.now(timezone.utc)

    # An edited, shorter resource leaves orphan chunks behind otherwise - they would
    # stay searchable forever, quoting text that is no longer in the document.
    for index, row in existing.items():
        if index >= len(chunks):
            db.delete(row)

    resource.needs_reindex = False
    resource.indexed_at = datetime.now(timezone.utc)
    db.flush()
    return len(chunks)


def ingest_pending(db: Session, *, school_id: int | None = None) -> tuple[int, int]:
    """Ingest every resource with no indexed_at. Returns (resources, chunks).

    Used by both POST /bots/reindex (no school_id filter would be a cross-tenant leak,
    so the router always passes its caller's) and the periodic scheduler job (which
    passes None deliberately - it runs for every school).
    """
    query = db.query(Resource).filter(Resource.indexed_at.is_(None))
    if school_id is not None:
        query = query.filter(Resource.school_id == school_id)

    resources = 0
    chunks = 0
    for resource in query.order_by(Resource.id).all():
        chunks += ingest_resource(db, resource.id)
        resources += 1
    return resources, chunks
