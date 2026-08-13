"""State machine + eligibility rules for admission applications, per the playbook:
"State machine (admission state transitions) and rules engine (eligibility logic)."

STATE MACHINE - explicit legal transitions, illegal ones documented and rejected
------------------------------------------------------------------------------------
    submitted    -> under_review, rejected
    under_review -> accepted, rejected
    accepted     -> (terminal)
    rejected     -> (terminal)

Deliberately does NOT allow submitted -> accepted directly: an application must pass
through at least one review step before acceptance, even if that review is
instantaneous in practice - this is the one transition worth calling out explicitly
since it's the most likely one someone building a UI would try to skip.

Also does not allow moving a terminal accepted/rejected application back to a
pending state. If a decision needs reversing, that should be a new application, not
reopening a closed one - keeps "was this ever accepted" a stable, honest fact rather
than something that can flip back and forth.

ELIGIBILITY - one demo-honest rule, documented limitation
------------------------------------------------------------------
Only checks that grade_applied is among the grades the school actually offers
(derived from real SchoolClass rows for the target academic_year, not a hardcoded
list). A real admissions system would also check age-appropriateness for the grade,
seat availability, sibling priority, etc. - none of that is attempted here; this is
intentionally the single simplest rule that's still genuinely useful (catches "we
don't have a Grade 13" typos/mistakes), not a comprehensive eligibility engine.
"""

from __future__ import annotations

from dataclasses import dataclass

VALID_STATUSES = ("submitted", "under_review", "accepted", "rejected")

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "submitted": frozenset({"under_review", "rejected"}),
    "under_review": frozenset({"accepted", "rejected"}),
    "accepted": frozenset(),
    "rejected": frozenset(),
}


@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    reason: str | None


def check_transition(current_status: str, new_status: str) -> TransitionResult:
    if new_status not in VALID_STATUSES:
        return TransitionResult(allowed=False, reason=f"'{new_status}' is not a valid status")
    if current_status not in LEGAL_TRANSITIONS:
        return TransitionResult(allowed=False, reason=f"'{current_status}' is not a valid current status")
    if new_status == current_status:
        return TransitionResult(allowed=False, reason=f"Application is already '{current_status}'")
    if new_status not in LEGAL_TRANSITIONS[current_status]:
        if current_status == "submitted" and new_status == "accepted":
            reason = "Cannot go directly from 'submitted' to 'accepted' - must pass through 'under_review' first"
        elif current_status in ("accepted", "rejected"):
            reason = f"'{current_status}' is a terminal state and cannot be changed"
        else:
            reason = f"'{current_status}' -> '{new_status}' is not a legal transition"
        return TransitionResult(allowed=False, reason=reason)
    return TransitionResult(allowed=True, reason=None)


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str | None


def check_eligibility(grade_applied: str, offered_grades: set[str]) -> EligibilityResult:
    if grade_applied in offered_grades:
        return EligibilityResult(eligible=True, reason=None)
    return EligibilityResult(
        eligible=False,
        reason=f"Grade {grade_applied!r} is not offered by this school for this academic year (offered: {sorted(offered_grades)})",
    )
