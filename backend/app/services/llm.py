"""Thin Gemini client wrapper - embeddings and one-shot generation.

Deliberately NOT a framework. No LangChain, no LlamaIndex: this project needs three
functions (embed a batch of documents, embed a query, generate an answer), all of
which are a direct SDK call plus retry. A framework would add a dependency tree, an
abstraction layer over an API we call in exactly three ways, and a second place for
the task-type/normalization rules below to be silently wrong.

WHY gemini-embedding-001 AND NOT gemini-embedding-2 - do not "upgrade" this
==========================================================================
`gemini-embedding-2` is newer, and looks like the obvious choice. It is not, for two
reasons that both fail SILENTLY rather than raising:

  1. NO TASK TYPES. Per the embeddings docs, gemini-embedding-2 does not accept a
     `task_type` parameter at all - task instructions are meant to be baked into the
     prompt text instead. Gemini embeddings are task-conditioned: embedding a stored
     chunk with RETRIEVAL_DOCUMENT and an incoming question with RETRIEVAL_QUERY is
     what makes asymmetric retrieval work. Moving to -2 would drop that distinction
     and measurably degrade retrieval, with no error anywhere.

  2. BATCHING MEANS SOMETHING DIFFERENT. gemini-embedding-2 returns ONE AGGREGATED
     embedding when a request carries several inputs; per-item vectors require
     wrapping each input in a `Content` object or using the Batch API. Our
     embed_documents() passes N chunks and expects N vectors. On -2 the naive form of
     that call returns 1 vector for N chunks - the ingestion would "succeed", write
     garbage, and only show up as inexplicably bad retrieval days later.

Both models are Matryoshka-trained, so 1536 dims is a valid truncation on either.
The normalization rule differs though (see EMBEDDING_DIMENSIONS below), which is a
third thing that would need changing in lockstep. If someone does move to -2 later,
all three of those have to change together - that is the whole reason this comment
exists.
"""

from __future__ import annotations

import math
import os
import random
import time

from dotenv import load_dotenv

load_dotenv()

from google import genai  # noqa: E402
from google.genai import types as genai_types  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. The RAG pipeline (embeddings + Doubt Bot) cannot "
        "start without it. Add it to backend/.env - see .env.example. Get a key at "
        "https://aistudio.google.com/apikey"
    )

EMBEDDING_MODEL = "gemini-embedding-001"
GENERATION_MODEL = "gemini-3.5-flash-lite"
"""Fast/cheap tier, chosen for a grounded-QA task where the model summarizes supplied
context rather than reasoning from scratch. Move up to `gemini-3.7-flash` if answer
quality is visibly poor - that is a one-line change here, nothing else depends on it."""

EMBEDDING_DIMENSIONS = 1536
"""Two hard constraints meet here, from opposite directions:

  - pgvector's HNSW index supports at most 2000 dims for the `vector` type, and
    gemini-embedding-001 defaults to 3072. Storing the default would mean no HNSW
    index at all (a brute-force scan, like face_embeddings does today).
  - 1536 is one of the sizes Google documents as a recommended MRL truncation.

`halfvec` (available here - pgvector 0.8.2) would allow indexing the full 3072 dims,
and was explicitly considered and rejected: 1536 halves storage and query cost, and
retrieval quality across a small curriculum corpus is not dimension-bound."""

_NORMALIZE_REQUIRED = True
"""gemini-embedding-001 returns L2-NORMALIZED vectors ONLY at its native 3072 dims.
Any truncated output_dimensionality (ours is 1536) comes back UNNORMALIZED and the
caller must normalize. This is the single most dangerous line in the file: cosine
similarity over unnormalized vectors still returns plausible-looking numbers in the
right range, just subtly wrong ordering - retrieval that looks like it works and
quietly returns the wrong chunks. Set to False only if the model is changed to one
that auto-normalizes truncated dims (gemini-embedding-2 does; -001 does not)."""

DOCUMENT_TASK_TYPE = "RETRIEVAL_DOCUMENT"
QUERY_TASK_TYPE = "RETRIEVAL_QUERY"

EMBED_BATCH_SIZE = 32
"""Chunks per embed call. gemini-embedding-001 returns one vector per input, so a
batch is a genuine round-trip saving, unlike on -2 (see the module docstring)."""

_MAX_RETRIES = 5
_INITIAL_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 30.0

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Lazily constructed and reused. Unlike supabase_admin.py's deliberately
    un-cached client (whose auth state is mutated by sign-in calls), the genai client
    is stateless across calls - there is no equivalent poisoning hazard here."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _is_retryable(exc: Exception) -> bool:
    """429 (rate limit) and 5xx (transient server) are worth retrying; 400/403 are
    our own bad request and never will be. Free-tier rate limits are real and WILL be
    hit during bulk ingestion, which is the reason this exists at all."""
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None)
        return code == 429 or (isinstance(code, int) and 500 <= code < 600)
    return False


def _with_retry(fn, *, what: str):
    """Bounded exponential backoff with jitter. Jitter matters during ingestion:
    without it, a batch of embed calls that all get rate-limited retry in lockstep and
    hit the limit again together."""
    backoff = _INITIAL_BACKOFF_SECONDS
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below if not retryable
            last_exc = exc
            if not _is_retryable(exc) or attempt == _MAX_RETRIES - 1:
                raise
            sleep_for = min(backoff, _MAX_BACKOFF_SECONDS) * (0.5 + random.random())
            time.sleep(sleep_for)
            backoff *= 2
    raise RuntimeError(f"{what} failed after {_MAX_RETRIES} attempts") from last_exc


def l2_normalize(vector: list[float]) -> list[float]:
    """Scale to unit length so cosine distance depends on direction only.

    A zero vector is returned unchanged rather than dividing by zero - it cannot
    happen with real embedding output, but a mocked/degenerate vector in a test
    should not crash the pipeline.
    """
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        return list(vector)
    return [component / norm for component in vector]


def _embed(texts: list[str], *, task_type: str) -> list[list[float]]:
    client = _get_client()
    config = genai_types.EmbedContentConfig(
        task_type=task_type,
        output_dimensionality=EMBEDDING_DIMENSIONS,
    )

    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        response = _with_retry(
            lambda b=batch: client.models.embed_content(model=EMBEDDING_MODEL, contents=b, config=config),
            what=f"embed_content({task_type})",
        )
        embeddings = list(response.embeddings or [])
        if len(embeddings) != len(batch):
            # Guards the exact gemini-embedding-2 aggregation failure described in the
            # module docstring: N inputs must yield N vectors. Loud failure beats
            # silently storing one vector for a whole batch.
            raise RuntimeError(
                f"Embedding API returned {len(embeddings)} vectors for {len(batch)} inputs "
                f"(model={EMBEDDING_MODEL}). Expected one per input."
            )
        for embedding in embeddings:
            values = list(embedding.values or [])
            if len(values) != EMBEDDING_DIMENSIONS:
                raise RuntimeError(
                    f"Embedding API returned {len(values)} dims, expected {EMBEDDING_DIMENSIONS}"
                )
            vectors.append(l2_normalize(values) if _NORMALIZE_REQUIRED else values)
    return vectors


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed stored chunks. Uses RETRIEVAL_DOCUMENT - see embed_query's note."""
    if not texts:
        return []
    return _embed(texts, task_type=DOCUMENT_TASK_TYPE)


def embed_query(text: str) -> list[float]:
    """Embed an incoming question.

    RETRIEVAL_QUERY, deliberately NOT the same task type used for documents. Gemini
    embeddings are task-conditioned and the document/query pair is trained to be
    asymmetric; using one type for both is a documented way to degrade retrieval while
    everything still appears to work.
    """
    return _embed([text], task_type=QUERY_TASK_TYPE)[0]


def generate(system: str, user: str) -> str:
    """One-shot, non-streaming generation. Streaming is deliberately not built - the
    ask endpoint returns a whole answer and the chat UI renders it in one go."""
    client = _get_client()
    response = _with_retry(
        lambda: client.models.generate_content(
            model=GENERATION_MODEL,
            contents=user,
            config=genai_types.GenerateContentConfig(system_instruction=system),
        ),
        what="generate_content",
    )
    return (response.text or "").strip()
