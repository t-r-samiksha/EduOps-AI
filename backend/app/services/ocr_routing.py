"""Auto-routing of extracted document entities into other tables.

Per the playbook: "Async task (Celery/Dramatiq/Huey) to auto-route extracted
entities to relevant tables."

SCHEDULING/QUEUE REALITY CHECK - same finding as Early-Warning's nightly job
---------------------------------------------------------------------------------
Checked first: still no Celery, Dramatiq, Huey, APScheduler, or any task queue
anywhere in this repo. Standing up real async infrastructure for one routing step is
over-investment for a single feature. `route_entities()` below is a plain,
synchronous, dependency-free function with a clean, side-effect-free boundary (one
call in, one RoutingResult out) - deliberately shaped so a real task queue could wrap
it in a `.delay()`/`.send()` later without touching its signature or internals. It
does not actually run asynchronously today.

WHICH DOCUMENT TYPES ROUTE FOR REAL, TODAY: admission_form ONLY
-----------------------------------------------------------------
This module's original finding ("no admissions table, no grades table - every
document_type is a stub") is now half-stale: `AdmissionApplication` and the real
`/admin/admissions/applications` CRUD landed in a later session (Fees & Admissions),
found live via a document detail page still showing the old stub message. Person B's
gradebook/marksheet table still doesn't exist, so `marksheet`/`id_proof`/`other`
remain honest stubs below.

"Routes for real" here means PRE-FILL, not silent auto-creation: admission_form's
handler returns a suggested `POST /admin/admissions/applications` payload for a human
to review and submit for real, never writes an AdmissionApplication row itself. Three
reasons this stops short of full auto-routing: (1) `academic_year` is never printed on
the physical form, so it's genuinely not derivable from extracted entities alone -
only a human (or the calling UI's own context) can supply it; (2) auto-creating a
real application from unreviewed OCR text would bypass the office-staff review the
product's own docs describe ("typically entered by office staff, possibly pre-filled
via OCR"); (3) a wrong/garbled OCR read (this module has no way to know if `dob` was
misread) becoming a real submitted application with no human in the loop is a real
data-quality risk a demo-scale regex extractor shouldn't be trusted to take alone.

ROUTING_TARGETS is a pluggable registry specifically so that reality (mostly-stub
today) doesn't have to compromise testability - tests inject a fake handler to prove
the routing *mechanism* works generically. Wire a real handler in here (and only
here) once a document type's target table lands - no other code needs to change
(confirmed: admission_form's addition below touched only this file plus the router
call site that merges in school_id/ocr_document_ids from the Document row itself,
neither of which this module has access to or opinions about).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.services.ocr_postprocess import normalize_date

RoutingHandler = Callable[[dict[str, str]], "RoutingResult"]


@dataclass(frozen=True)
class RoutingResult:
    routed: bool
    target_table: str | None
    reason: str
    suggested_payload: dict[str, str] | None = None
    """Only set when routed=True - the subset of a downstream endpoint's request
    body this module can derive purely from extracted entities (e.g.
    applicant_name/dob/guardian_email/grade_applied for
    POST /admin/admissions/applications). The caller (routers/documents.py) merges
    in school_id/ocr_document_ids from the Document row; a human still supplies
    academic_year and reviews/edits before submitting for real - see this module's
    docstring for why this stops at pre-fill, not auto-creation."""


def _stub_handler(document_type: str, would_route_to: str) -> RoutingHandler:
    def handler(entities: dict[str, str]) -> RoutingResult:
        return RoutingResult(
            routed=False,
            target_table=None,
            reason=(
                f"No '{would_route_to}' table exists yet for document_type={document_type!r} - "
                "extraction is persisted as ExtractedEntity rows, routing is a documented stub"
            ),
        )

    return handler


REQUIRED_ADMISSION_FIELDS = ("applicant_name", "dob", "guardian_email", "grade_applied")
"""Mirrors AdmissionApplication's own non-nullable columns (school_id/academic_year/
submitted_by are supplied by the caller, not extracted from the document) - see
models/admissions.py."""


def _admission_form_handler(entities: dict[str, str]) -> RoutingResult:
    missing = [f for f in REQUIRED_ADMISSION_FIELDS if not entities.get(f)]
    if missing:
        return RoutingResult(
            routed=False,
            target_table="admission_applications",
            reason=(
                f"Missing required field(s) for an admission application: {', '.join(missing)} - "
                "extract (or correct) them on this document before creating an application from it."
            ),
        )
    payload = {
        "applicant_name": entities["applicant_name"],
        # Already normalized to ISO by ocr_postprocess before this ever runs -
        # normalize_date here is a defensive no-op re-application (e.g. a
        # human's `corrected_value` might not be ISO), not a second real pass.
        "dob": normalize_date(entities["dob"]),
        "guardian_email": entities["guardian_email"],
        "grade_applied": entities["grade_applied"],
    }
    # Optional (not in REQUIRED_ADMISSION_FIELDS - a form missing these shouldn't
    # block routing) but real once present: found live that guardian_name was
    # extracted here and then silently dropped, never reaching the application or
    # the real parent account eventually created from it (which had no name to
    # give). Included whenever OCR actually found them.
    if entities.get("guardian_name"):
        payload["guardian_name"] = entities["guardian_name"]
    if entities.get("guardian_phone"):
        payload["guardian_phone"] = entities["guardian_phone"]

    return RoutingResult(
        routed=True,
        target_table="admission_applications",
        reason="Ready to pre-fill a new admission application from this document's extracted fields.",
        suggested_payload=payload,
    )


ROUTING_TARGETS: dict[str, RoutingHandler] = {
    "admission_form": _admission_form_handler,
    "marksheet": _stub_handler("marksheet", "grades"),
    # id_proof would plausibly update the uploading student's User record (full_name)
    # once Document carries a target student reference - it doesn't today (uploaded_by
    # is the *uploader*, e.g. an admin, not necessarily the document's subject).
    "id_proof": _stub_handler("id_proof", "users (student identity fields)"),
    "other": _stub_handler("other", "n/a"),
}


def route_entities(
    document_type: str,
    entities: dict[str, str],
    *,
    registry: dict[str, RoutingHandler] = ROUTING_TARGETS,
) -> RoutingResult:
    """Look up and invoke the routing handler for document_type. `registry` defaults
    to the real (currently all-stub) production registry - tests override it to
    exercise the "a real target table exists" branch of the mechanism."""
    handler = registry.get(document_type)
    if handler is None:
        return RoutingResult(
            routed=False, target_table=None, reason=f"No routing handler registered for document_type={document_type!r}"
        )
    return handler(entities)
