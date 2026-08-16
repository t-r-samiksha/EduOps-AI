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

ELIGIBILITY - grade LEVEL, not section - a real bug fix
------------------------------------------------------------------
Originally checked `grade_applied` against real SchoolClass NAMES (e.g. "Grade 3 - A")
- found live: this asked an applicant/admin to know a specific section's exact name
  in advance, which no real admission process works like ("what grade are you
  applying for" is a grade LEVEL question, not "which section"). Now checks
  `grade_applied` (a stringified `SchoolClass.grade_level`, including LKG/UKG/Nursery's
  negative-int convention - see that column's own docstring) against every grade
  level offered by at least one real ACTIVE section for the target academic year -
  "does this school teach Grade 3 at all", not "does 'Grade 3 - A' exist verbatim".
  Section ASSIGNMENT (which specific section, with room) is a separate concern, only
  resolved at acceptance time - see pick_section() below.

Still a demo-honest, deliberately limited rule: no age-appropriateness check for the
grade, no sibling priority, etc. - this is the single simplest rule that's still
genuinely useful (catches "we don't have a Grade 13" typos/mistakes), not a
comprehensive eligibility engine.
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

GRADE_LEVEL_DISPLAY_OVERRIDES: dict[int, str] = {-3: "Nursery", -2: "LKG", -1: "UKG"}
"""Mirrors SchoolClass.grade_label's own documented convention (free-form display
name for pre-Grade-1 levels) - purely cosmetic, for building human-readable
messages. Every real matching/lookup elsewhere always uses the raw int, never this."""


def grade_level_display(grade_level: int) -> str:
    return GRADE_LEVEL_DISPLAY_OVERRIDES.get(grade_level, f"Grade {grade_level}")


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


def check_reject_reason(new_status: str, decision_justification: str | None) -> str | None:
    """A real reason is required to reject - `decision_justification` already
    exists on the model for exactly this. Returns an error message if missing/
    blank, None if the reject may proceed. Only applies to "rejected"; accepting
    has no such requirement (the auto section-assignment/enrollment succeeding
    IS the affirmative justification)."""
    if new_status != "rejected":
        return None
    if not decision_justification or not decision_justification.strip():
        return "A reason (decision_justification) is required to reject an application"
    return None


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str | None


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def check_eligibility(grade_applied: str, offered_grade_levels: set[str]) -> EligibilityResult:
    if grade_applied in offered_grade_levels:
        return EligibilityResult(eligible=True, reason=None)

    parsed = _parse_int(grade_applied)
    display = grade_level_display(parsed) if parsed is not None else grade_applied
    offered_ints = sorted(g for g in (_parse_int(v) for v in offered_grade_levels) if g is not None)
    offered_display = [grade_level_display(g) for g in offered_ints]
    return EligibilityResult(
        eligible=False,
        reason=f"{display} is not offered by this school for this academic year (offered: {offered_display})",
    )


# --- section assignment (acceptance-time, not submission-time eligibility) ---


@dataclass(frozen=True)
class SectionCandidate:
    class_id: int
    grade_level: int
    current_count: int
    capacity: int


@dataclass(frozen=True)
class SectionAssignmentResult:
    class_id: int | None
    reason: str | None


def pick_section(
    grade_level: int, academic_year: str, candidates: list[SectionCandidate]
) -> SectionAssignmentResult:
    """The real "which section" decision, separate from check_eligibility's "is this
    grade offered at all" - candidates are every real ACTIVE SchoolClass at this
    grade_level/academic_year, each with its real current enrollment count and
    capacity (see routers/admissions.py's _section_candidates for how those are
    computed). Assigns the LEAST-FILLED section with room, never overfills, never
    invents a new section."""
    matching = [c for c in candidates if c.grade_level == grade_level]
    available = [c for c in matching if c.current_count < c.capacity]
    if not available:
        return SectionAssignmentResult(
            class_id=None,
            reason=f"No available seats in {grade_level_display(grade_level)} for {academic_year} - all sections full",
        )
    least_filled = min(available, key=lambda c: c.current_count)
    return SectionAssignmentResult(class_id=least_filled.class_id, reason=None)
