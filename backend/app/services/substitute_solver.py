"""Finds and ranks substitute-teacher candidates for a single timetable slot whose
usual teacher is on leave.

Decoupled from the ORM, like timetable_solver.py: callers (the API layer, tests) build
plain dataclasses describing each candidate's qualification/availability and get back
a ranked list of suggestions - no DB access here, so this is testable standalone.

Hard filters (a candidate that fails any of these is not a substitute, period):
- qualified for the subject being covered (TeacherSubject)
- not the original teacher
- not already teaching another class in that exact day/period (their own timetable)
- not marked unavailable for that day/period (TeacherUnavailability)
- not themselves on approved leave that day
- not already CONFIRMED as someone else's substitute for a different class at that
  exact day/period (a real double-booking gap found live: nothing here or in
  routers/staffing.py's confirm endpoint checked the Substitution table itself, so
  a teacher with nothing on their own real timetable at 2pm Wednesday could be
  confirmed as substitute for two different classes both at 2pm Wednesday)

Soft ranking, applied only among candidates that pass every hard filter: workload
balance - a candidate teaching fewer periods/week currently scores higher, so
substitutions spread out rather than piling onto whoever happens to be qualified and
sits at the top of a list. Qualification itself isn't a scoring dimension since it's
already a hard filter (a candidate is either eligible or excluded, not partially so).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

BASE_SCORE = 0.7
"""Every eligible (hard-filter-passing) candidate starts here."""
MAX_WORKLOAD_BONUS = 0.3
"""Added on a sliding scale, full bonus going to the least-loaded eligible candidate."""


@dataclass(frozen=True)
class SubstituteCandidate:
    teacher_id: int
    qualified_subject_ids: frozenset[int]
    already_busy: bool
    """Has another timetable slot at this exact day/period."""
    unavailable: bool
    """Has a TeacherUnavailability row for this day/period/academic_year."""
    on_leave: bool
    """Has an approved LeaveRequest covering this date."""
    current_workload: int
    """Periods/week currently assigned - lower is preferred as a tiebreak."""
    already_substituting: bool = False
    """Already CONFIRMED as substitute for a DIFFERENT class at this exact
    day/period/academic_year - distinct from already_busy, which only looks at
    this teacher's own real TimetableSlot rows, not their Substitution
    commitments. Defaults to False so existing callers/tests that predate this
    check are unaffected unless they opt in."""


@dataclass(frozen=True)
class SubstituteSuggestion:
    teacher_id: int
    score: float
    reason: str
    qualified: bool = True
    """False only for find_fallback_substitutes()'s output - a real teacher
    surfaced automatically as supervision-only cover because nobody qualified
    was available at all. Callers must render this distinctly (a clear warning),
    never silently mix it in as if it were a normal qualified suggestion."""


def _rank_by_workload(
    eligible: list[SubstituteCandidate], *, reason_for: Callable[[SubstituteCandidate], str], qualified: bool, max_results: int
) -> list[SubstituteSuggestion]:
    if not eligible:
        return []
    max_workload = max(c.current_workload for c in eligible)
    suggestions = []
    for c in eligible:
        workload_ratio = (c.current_workload / max_workload) if max_workload else 0.0
        workload_bonus = MAX_WORKLOAD_BONUS * (1.0 - workload_ratio)
        score = round(BASE_SCORE + workload_bonus, 3)
        suggestions.append(
            SubstituteSuggestion(teacher_id=c.teacher_id, score=score, reason=reason_for(c), qualified=qualified)
        )
    suggestions.sort(key=lambda s: -s.score)
    return suggestions[:max_results]


def find_substitutes(
    *,
    subject_id: int,
    original_teacher_id: int,
    candidates: list[SubstituteCandidate],
    max_results: int = 3,
) -> list[SubstituteSuggestion]:
    eligible = [
        c
        for c in candidates
        if c.teacher_id != original_teacher_id
        and subject_id in c.qualified_subject_ids
        and not c.already_busy
        and not c.unavailable
        and not c.on_leave
        and not c.already_substituting
    ]
    return _rank_by_workload(
        eligible,
        reason_for=lambda c: f"qualified for subject, current workload {c.current_workload} periods/week",
        qualified=True,
        max_results=max_results,
    )


def find_fallback_substitutes(
    *,
    original_teacher_id: int,
    candidates: list[SubstituteCandidate],
    max_results: int = 3,
) -> list[SubstituteSuggestion]:
    """Only meaningful to call when find_substitutes() returned nothing - the
    real-world escalation for "no qualified substitute exists at all": every
    OTHER teacher who is free at this exact day/period, regardless of subject
    qualification (a genuine supervision-only cover, not someone who can
    actually teach the material). Deliberately does NOT filter by subject
    qualification - that's the one dimension this tier exists to waive - but
    every other hard filter (busy/unavailable/on_leave/already_substituting)
    still applies unchanged, since those are real scheduling/physical
    impossibilities regardless of which tier is being searched."""
    eligible = [
        c
        for c in candidates
        if c.teacher_id != original_teacher_id
        and not c.already_busy
        and not c.unavailable
        and not c.on_leave
        and not c.already_substituting
    ]
    return _rank_by_workload(
        eligible,
        reason_for=lambda c: f"NOT qualified for this subject - workload {c.current_workload} periods/week (supervision only)",
        qualified=False,
        max_results=max_results,
    )
