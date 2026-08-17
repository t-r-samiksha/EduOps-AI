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

  1 day overdue:   first notice,    normal severity - the due date has passed.
  7 days overdue:  reminder,        normal severity - a friendly nudge.
  14 days overdue: reminder,        normal severity - escalating language.
  30 days overdue: final reminder,  urgent severity - genuinely admin-attention-
                    worthy, matches alert_aggregator.py's two-tier severity scheme.

WHY THE 1-DAY TIER EXISTS (added after the 7/14/30 original)
------------------------------------------------------------------------------
Without it, `fee_records.status` and this engine disagreed about the word
"overdue". The invoicing job flips a record to "overdue" the moment its due_date
passes, so the admin's fee list showed ten red overdue cards while triggering
reminders produced zero - correct on both sides, and indistinguishable from a
broken button. A school that marks a fee overdue on day 1 and then says nothing
for a week is also just odd; real ones send an immediate past-due notice and
escalate from there. Now anything the UI calls overdue earns at least one notice.

THE EXISTING TIERS' `cadence_reason` STRINGS ARE UNCHANGED, DELIBERATELY
------------------------------------------------------------------------------
Note the labels below read "7 days overdue - first reminder" even though the
1-day notice now precedes it. That inconsistency is on purpose and must stay:
`already_sent_reasons` is matched against `cadence_reason` values already
PERSISTED in fee_reminders rows. Renaming a tier would orphan every historical
row carrying the old string - it would no longer resolve to a tier index, so
`highest_sent_index` would fall back to -1 and a reminder that already went out
would fire again. Tidier names are not worth re-sending a fee reminder to a
parent. Add new tiers; never rename an existing one without a data migration.

Adding the tier at index 0 is safe for history for the same reason the
skipped-lower-tier regression test exists: eligibility requires
`i > highest_sent_index`, so a record that already received the 7-day tier can
never fire the day-1 notice retroactively.

Once every tier a record has reached has already fired, determine_reminder()
correctly returns should_send=False - already at maximum escalation, nothing new to
send. This is intentional, not a gap: it's a decision to stop generating reminders,
not a signal that stops being tracked (the FeeRecord itself stays "overdue" and
still shows up as a Command Center alert via alert_aggregator.py's fee_overdue
source)."""

from __future__ import annotations

from dataclasses import dataclass

REMINDER_TIERS: tuple[tuple[int, str, str], ...] = (
    (1, "normal", "due date passed - first notice"),
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
    again on every subsequent run.

    Tracked by TIER INDEX, not just exact reason membership: escalation only ever
    moves forward. Skipping a tier (e.g. first reached at 20 days overdue, jumping
    straight to the 14-day reminder) is intentional - see this module's docstring -
    but that skipped lower tier must never fire on a later run just because its
    exact reason string was never logged. Without this, calling the invoicing job
    (or its on-demand endpoint) twice on the same day could send the mild "first
    reminder" right after the escalated "second reminder" had already gone out."""
    if days_overdue <= 0:
        return ReminderDecision(should_send=False, cadence_reason=None, severity=None)

    reason_index = {reason: i for i, (_, _, reason) in enumerate(REMINDER_TIERS)}
    highest_sent_index = max((reason_index[r] for r in already_sent_reasons if r in reason_index), default=-1)

    eligible = [
        (i, severity, reason)
        for i, (threshold, severity, reason) in enumerate(REMINDER_TIERS)
        if days_overdue >= threshold and i > highest_sent_index
    ]
    if not eligible:
        return ReminderDecision(should_send=False, cadence_reason=None, severity=None)

    # REMINDER_TIERS is defined in ascending threshold order, so the last eligible
    # entry is the highest tier reached that hasn't fired yet.
    _index, severity, reason = eligible[-1]
    return ReminderDecision(should_send=True, cadence_reason=reason, severity=severity)
