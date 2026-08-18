"""Turns classroom post attachments into real, bot-searchable `Resource` rows.

WHY THIS EXISTS
---------------
`POST /classroom/{id}/upload` stored bytes in the `resources` bucket and stopped there:
no `resources` row, and no `ingest_resource` call. Only `POST /resources/upload` built the
RAG corpus (Resource -> chunk -> embed -> `kb_chunks`, which `services/retrieval.py`
searches). So a teacher who posted a worksheet to their class stream had shared it with
students but NOT with the Doubt Bot, and nothing in either screen said so - the Resources
page would sit at "Showing 0 academic resources" directly beside its own
"Knowledge Base Indexed for Doubt Bot" label. The only way to get both was to upload the
same PDF twice, in two different places.

The classroom stream and the resources library are kept as separate SCREENS on purpose -
one is a chronological per-section feed ("what did my teacher post this week"), the other
a searchable corpus organised by subject/unit that can be shared grade-wide. What is
unified is the WRITE path: posting a material to a stream now also files it in the library
and indexes it, so it is uploaded once and appears in both.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.class_ import SchoolClass
from app.models.classroom import Classroom, PostAttachment
from app.models.resource import Resource
from app.services.ingestion import ingest_resource

logger = logging.getLogger(__name__)


def _is_indexable(mime_type: str) -> bool:
    """Images carry no extractable text, so chunking them yields nothing.

    Mirrors routers/resources.py's own `is_text_bearing` check rather than inventing a
    second rule - an image attachment still becomes a Resource (so it is visible in the
    library), it just never goes through ingestion.
    """
    return not (mime_type or "").startswith("image/")


def index_post_attachments(
    db: Session,
    *,
    classroom: Classroom,
    post_title: str,
    attachments: list[PostAttachment],
    uploader_id: int,
    share_with_grade: bool = True,
) -> list[str]:
    """Create a `Resource` for each attachment and index it for the bots.

    Returns a list of human-readable warnings - one per attachment whose text extraction
    or embedding failed. The caller surfaces these on the response; an empty list means
    everything indexed.

    DOES NOT COMMIT, and does not raise for an ingestion failure. Both are deliberate:

    - No commit, matching services/notify.py and services/ingestion.py - the router owns
      the transaction.
    - INGESTION FAILURE IS NOT FATAL HERE, which is the opposite of
      `POST /resources/upload`. That endpoint rolls the whole request back so an
      unsearchable resource never persists, which is right when the file IS the request.
      Here the request is a teacher's post: throwing away their note and its attachment
      because a PDF had no extractable text layer would be a much worse outcome than an
      unindexed file. So `indexed_at` is left NULL - and the periodic reindex job selects
      exactly `indexed_at IS NULL` (see Resource.indexed_at's docstring), so these are
      retried automatically. The failure is returned to the caller AND logged, never
      silently swallowed.
    """
    if not attachments:
        return []

    school_class = (
        db.query(SchoolClass).filter(SchoolClass.id == classroom.class_id).one_or_none()
    )
    # grade_level is NOT NULL on resources and is the unit every RAG path scopes by, so
    # without it there is nothing safe to write. Skipping beats guessing a grade.
    if school_class is None or school_class.grade_level is None:
        logger.warning(
            "classroom %s: class %s has no grade_level, attachments not indexed",
            classroom.id,
            classroom.class_id,
        )
        return [
            "Attachments were saved but not added to the Doubt Bot's knowledge base: "
            "this class section has no grade level set."
        ]

    warnings: list[str] = []

    for attachment in attachments:
        resource = Resource(
            school_id=classroom.school_id,
            grade_level=school_class.grade_level,
            # GRADE-WIDE BY DEFAULT (class_id=None). A worksheet posted to Grade 3-B Math
            # is almost always just as relevant to Grade 3-A Math, and `class_id IS NULL
            # AND grade_level = :grade` is the shape the bot's retrieval already expects
            # (see Resource.class_id's docstring - class_id narrows library BROWSING only
            # and never scopes bot retrieval). `share_with_grade=False` pins it to the one
            # section for material that genuinely should not travel.
            class_id=None if share_with_grade else classroom.class_id,
            subject_id=classroom.subject_id,
            # The post's title, with the filename appended when several files share one
            # post - otherwise three attachments would produce three identically-named
            # library rows and the bot's citations could not be told apart.
            title=(
                post_title
                if len(attachments) == 1
                else f"{post_title} - {attachment.file_name}"
            )[:255],
            description=f"Posted to {classroom.class_name} classroom stream.",
            file_url=attachment.file_url,
            mime_type=attachment.file_type,
            file_size=attachment.file_size,
            uploaded_by=uploader_id,
        )
        db.add(resource)
        db.flush()  # need resource.id for both the link and ingest_resource

        attachment.resource_id = resource.id

        if not _is_indexable(attachment.file_type):
            # Visible in the library, deliberately never indexed. indexed_at stays NULL,
            # so mark it as not needing a reindex or the nightly job retries it forever.
            resource.needs_reindex = False
            continue

        try:
            ingest_resource(db, resource.id)
        except Exception as exc:  # noqa: BLE001 - reported and logged, see docstring
            logger.warning(
                "classroom %s: failed to index attachment %r as resource %s: %s",
                classroom.id,
                attachment.file_name,
                resource.id,
                exc,
            )
            warnings.append(
                f"'{attachment.file_name}' was saved and shared, but could not be added "
                "to the Doubt Bot's knowledge base yet. It will be retried automatically."
            )

    return warnings
