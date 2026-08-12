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

WHICH DOCUMENT TYPES ROUTE FOR REAL, TODAY: NONE
-----------------------------------------------------
Checked backend/app/models/ before writing this module: there is no admissions/
applications table (Task Group 9 - not started) and no grades/marksheet table
(Person B's gradebook - not started, confirmed again this session). Every
document_type below is therefore a documented stub: extraction still happens for
real (services/ocr_postprocess.py) and is persisted as real ExtractedEntity rows
regardless, but nothing is currently written anywhere beyond this feature's own
tables.

ROUTING_TARGETS is a pluggable registry specifically so that reality (zero real
targets today) doesn't have to compromise testability - tests inject a fake handler
to prove the routing *mechanism* works generically, without this module pretending a
real downstream table exists when it doesn't. Wire a real handler in here (and only
here) once Person A's admissions table or Person B's gradebook lands - no other code
needs to change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

RoutingHandler = Callable[[dict[str, str]], "RoutingResult"]


@dataclass(frozen=True)
class RoutingResult:
    routed: bool
    target_table: str | None
    reason: str


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


ROUTING_TARGETS: dict[str, RoutingHandler] = {
    "admission_form": _stub_handler("admission_form", "admissions/applications"),
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
