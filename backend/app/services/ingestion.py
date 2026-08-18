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

from app.models.class_ import SchoolClass
from app.models.doubt import DoubtThread, ThreadReply
from app.models.knowledge import SOURCE_TYPE_RESOURCE, SOURCE_TYPE_VERIFIED_DOUBT_ANSWER, KbChunk
from app.models.resource import Resource
from app.models.user import User
from app.services.llm import embed_documents
from app.services.supabase_admin import download_resource_file

PDF_MIME_TYPES = {"application/pdf"}


def extract_text(raw: bytes, *, mime_type: str, filename: str = "") -> str:
    """Bytes -> plain text, by type. Plain text/markdown pass through; PDFs go through
    pypdf's per-page text extraction. Images return empty text.

    PDF SUPPORT IS TEXT-LAYER ONLY. pypdf reads the text a PDF already carries; it does
    NOT do OCR. A scanned PDF (pages that are images of text) extracts to nothing, and
    that is reported as a 422 by the upload endpoint rather than being ingested as an
    empty resource. This project does have a Tesseract OCR pipeline
    (services/ocr_engine.py), but it targets the separate `documents` admin flow and is
    not wired in here - bridging the two is real work, not a one-liner.

    DO NOT WRAP THE PARSE IN `except Exception: return ""`. Returning empty text on a
    malformed PDF makes ingest_resource() stamp `indexed_at` and produce zero chunks, so
    the resource is marked "done", is invisible to every bot, and the nightly re-index
    job (which selects `indexed_at IS NULL`) never retries it. The teacher sees
    201 Created and nothing else, forever. Let the parse raise and let the upload
    endpoint turn it into a 422 the caller can act on.
    """
    if mime_type.startswith("image/"):
        # Images carry no text layer and are not OCR'd here (see the docstring). Empty
        # is the CORRECT answer for them, not a swallowed failure.
        return ""

    if mime_type in PDF_MIME_TYPES or filename.lower().endswith(".pdf"):
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        # Page-joined with blank lines so chunk_text's paragraph-preferring splitter
        # treats a page boundary as a natural break point.
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        # NUL bytes are stripped because Postgres `text` rejects them outright - a PDF
        # carrying one would fail the kb_chunks INSERT, not the extraction.
        return "\n\n".join(p for p in pages if p).replace("\x00", "")

    return raw.decode("utf-8", errors="replace").replace("\x00", "")


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


# --- Verified doubt answers ------------------------------------------------------------
# The second consumer of kb_chunks, and the reason SOURCE_TYPE_VERIFIED_DOUBT_ANSWER
# exists. Shares embed_documents() and the upsert-by-unique-key idiom above; skips the
# parts that only make sense for a file.
#
# NO STORAGE FETCH, NO SPLITTER. There is no file - the content is two rows already in
# Postgres - and a Q&A pair is a few hundred characters, well under CHUNK_TARGET_CHARS,
# so chunk_text() would return a single chunk anyway. Calling it would just add a code
# path that could one day split a question away from its answer, which is the one way
# this content must never be divided.


def build_verified_answer_text(*, title: str, body: str, answer: str, verifier: str | None) -> str:
    """The chunk text for a verified answer: the question, then the certified answer.

    Shaped as an explicit Q&A because that is what it has to match at retrieval time -
    a student asking the same question should land on near-identical text. The
    attribution line is inside the CHUNK, not only in the citation title, so the LLM
    generating the answer also knows this came from a teacher and can say so.
    """
    question = f"Question: {title}".strip()
    if body.strip():
        question = f"{question}\n{body.strip()}"
    attribution = f"Verified answer from {verifier}" if verifier else "Verified answer from the class teacher"
    return f"{question}\n\n{attribution}:\n{answer.strip()}"


def ingest_verified_doubt_answer(db: Session, thread_id: int) -> int:
    """Embed and upsert one thread's verified answer. Returns chunks written (0 or 1).

    Does NOT commit, same convention as ingest_resource - the verify endpoint owns the
    transaction so a failed embedding rolls back the verification too, rather than
    leaving a thread marked verified whose answer never reached the corpus.

    Raises ValueError for states the caller should turn into a 4xx: unknown thread, no
    verified reply, or a class with no grade_level (kb_chunks.grade_level is NOT NULL,
    so there would be nothing to scope the chunk by - a clean 400 beats an
    IntegrityError).
    """
    thread = db.query(DoubtThread).filter(DoubtThread.id == thread_id).one_or_none()
    if thread is None:
        raise ValueError(f"Unknown thread_id {thread_id}")
    if thread.verified_reply_id is None:
        raise ValueError(f"Thread {thread_id} has no verified reply to ingest")

    reply = db.query(ThreadReply).filter(ThreadReply.id == thread.verified_reply_id).one_or_none()
    if reply is None:
        raise ValueError(f"Thread {thread_id}'s verified reply {thread.verified_reply_id} is missing")

    school_class = db.query(SchoolClass).filter(SchoolClass.id == thread.class_id).one_or_none()
    if school_class is None or school_class.grade_level is None:
        raise ValueError("This thread's class has no grade level set, so its answer cannot be indexed")

    verifier = db.query(User).filter(User.id == reply.author_id).one_or_none()
    text = build_verified_answer_text(
        title=thread.title,
        body=thread.body,
        answer=reply.body,
        verifier=(verifier.full_name or verifier.email) if verifier else None,
    )

    vector = embed_documents([text])[0]

    # GRADE-level, not class-level - see models/doubt.py's asymmetry note. The thread
    # stays private to its class; the certified answer joins the grade's corpus.
    existing = db.scalars(
        select(KbChunk).where(
            KbChunk.source_type == SOURCE_TYPE_VERIFIED_DOUBT_ANSWER,
            KbChunk.source_id == thread.id,
        )
    ).all()

    row = next((r for r in existing if r.chunk_index == 0), None)
    if row is None:
        db.add(
            KbChunk(
                source_type=SOURCE_TYPE_VERIFIED_DOUBT_ANSWER,
                source_id=thread.id,
                chunk_index=0,
                chunk_text=text,
                embedding=vector,
                school_id=thread.school_id,
                grade_level=school_class.grade_level,
                subject_id=thread.subject_id,
            )
        )
    else:
        # Re-verifying a different reply overwrites in place - the unique key makes
        # this idempotent, so a teacher changing their mind doesn't leave two answers
        # to the same question competing in retrieval.
        row.chunk_text = text
        row.embedding = vector
        row.school_id = thread.school_id
        row.grade_level = school_class.grade_level
        row.subject_id = thread.subject_id
        row.indexed_at = datetime.now(timezone.utc)

    # Defensive: a Q&A pair is always one chunk, but if an earlier version of this ever
    # wrote more, they would stay searchable forever quoting a retracted answer.
    for extra in existing:
        if extra.chunk_index > 0:
            db.delete(extra)

    db.flush()
    return 1


def remove_verified_doubt_answer(db: Session, thread_id: int) -> int:
    """Delete a thread's chunks from the corpus. Returns how many were removed.

    THE RETRACTION HALF, and not optional. Unverifying that only cleared a flag would
    leave the answer permanently searchable - a teacher who withdrew a wrong answer
    would keep watching the bot cite it, with no way to remove it short of SQL.
    """
    rows = db.scalars(
        select(KbChunk).where(
            KbChunk.source_type == SOURCE_TYPE_VERIFIED_DOUBT_ANSWER,
            KbChunk.source_id == thread_id,
        )
    ).all()
    for row in rows:
        db.delete(row)
    db.flush()
    return len(rows)


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
