"""Heuristic engine to determine fee reminder cadence, per the playbook: "Heuristic
engine to determine optimal fee reminder cadence per family." The playbook's own
word is "heuristic" - this is a deliberately simple days-overdue tiered ruleset, not
a real ML model, and doesn't try to be more than that.

TIERS - round numbers, not calibrated against real payment-behavior data
------------------------------------------------------------------------------
Escalating cadence: each tier represents the HIGHEST threshold reached that hasn't
already had a reminder sent for it, not a narrow day-of-week window - a job that
misses a day (weekends, a skipped run) still catches up correctly on the next run,
rather than needing to run on the exact day N to ever fire that tier.

  7 days overdue:  first reminder,  normal severity - a friendly nudge.
  14 days overdue: second reminder, normal severity - escalating language.
  30 days overdue: third reminder,  urgent severity - genuinely admin-attention-
                    worthy, matches alert_aggregator.py's two-tier severity scheme.

Once every tier a record has reached has already fired, determine_reminder()
correctly returns should_send=False - already at maximum escalation, nothing new to
send. This is intentional, not a gap: it's a decision to stop generating reminders,
not a signal that stops being tracked (the FeeRecord itself stays "overdue" and
still shows up as a Command Center alert via alert_aggregator.py's fee_overdue
source)."""

from __future__ import annotations

from dataclasses import dataclass

REMINDER_TIERS: tuple[tuple[int, str, str], ...] = (
    (7, "normal", "7 days overdue - first reminder"),
    (14, "normal", "14 days overdue - second reminder"),
    (30, "urgent", "30 days overdue - third reminder, escalated"),
)


@dataclass(frozen=True)
class ReminderDecision:
    should_send: bool
    cadence_reason: str | None
    severity: str | None
    """One of "normal"/"urgent" (matches alert_aggregator.SEVERITY_LEVELS), or None
    when should_send is False."""


def determine_reminder(days_overdue: int, already_sent_reasons: set[str]) -> ReminderDecision:
    """`already_sent_reasons` is the set of `cadence_reason` strings already logged
    as FeeReminders for this FeeRecord, so a tier that already fired doesn't fire
    again on every subsequent run."""
    if days_overdue <= 0:
        return ReminderDecision(should_send=False, cadence_reason=None, severity=None)

    eligible = [
        (threshold, severity, reason)
        for threshold, severity, reason in REMINDER_TIERS
        if days_overdue >= threshold and reason not in already_sent_reasons
    ]
    if not eligible:
        return ReminderDecision(should_send=False, cadence_reason=None, severity=None)

    # REMINDER_TIERS is defined in ascending threshold order, so the last eligible
    # entry is the highest tier reached that hasn't fired yet.
    _threshold, severity, reason = eligible[-1]
    return ReminderDecision(should_send=True, cadence_reason=reason, severity=severity)
