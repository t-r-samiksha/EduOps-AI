from app.services.fee_reminder_engine import REMINDER_TIERS, determine_reminder

# Indices, so these tests survive a future tier being added the way the 1-day notice
# was. TIER_DAY1 was added after the original 7/14/30 set; the assertions below moved
# up one index at that point rather than being rewritten.
TIER_DAY1, TIER_7, TIER_14, TIER_30 = (t[2] for t in REMINDER_TIERS)


def test_not_overdue_never_sends():
    decision = determine_reminder(days_overdue=0, already_sent_reasons=set())
    assert decision.should_send is False


def test_negative_days_overdue_never_sends():
    decision = determine_reminder(days_overdue=-3, already_sent_reasons=set())
    assert decision.should_send is False


def test_one_day_overdue_sends_the_first_notice():
    """The day the due date passes, a record earns a notice - this is what makes the
    engine agree with `fee_records.status`, which calls that same record overdue."""
    decision = determine_reminder(days_overdue=1, already_sent_reasons=set())
    assert decision.should_send is True
    assert decision.cadence_reason == TIER_DAY1
    assert decision.severity == "normal"


def test_between_day_one_and_seven_still_only_the_first_notice():
    """5 days overdue has passed the 1-day tier but not the 7-day one, so the mild
    notice is correct and the 7-day reminder must not fire early."""
    decision = determine_reminder(days_overdue=5, already_sent_reasons=set())
    assert decision.should_send is True
    assert decision.cadence_reason == TIER_DAY1


def test_first_notice_does_not_resend_once_already_sent():
    decision = determine_reminder(days_overdue=5, already_sent_reasons={TIER_DAY1})
    assert decision.should_send is False


def test_seven_days_overdue_sends_the_seven_day_tier():
    """Nothing sent yet at 7 days: both the 1-day and 7-day tiers are reached, and the
    HIGHEST reached wins - it must not send the milder day-1 notice."""
    decision = determine_reminder(days_overdue=7, already_sent_reasons=set())
    assert decision.should_send is True
    assert decision.cadence_reason == TIER_7
    assert decision.severity == "normal"


def test_between_tiers_sends_the_highest_reached_tier_not_already_sent():
    # 20 days overdue: tiers 1, 7 and 14 all reached; with the day-1 notice already
    # sent, the 14-day tier is the correct next reminder (highest reached, not sent).
    decision = determine_reminder(days_overdue=20, already_sent_reasons={TIER_DAY1})
    assert decision.should_send is True
    assert decision.cadence_reason == TIER_14
    assert decision.severity == "normal"


def test_thirty_days_overdue_sends_urgent_tier():
    decision = determine_reminder(days_overdue=30, already_sent_reasons={TIER_DAY1, TIER_7, TIER_14})
    assert decision.should_send is True
    assert decision.cadence_reason == TIER_30
    assert decision.severity == "urgent"


def test_well_past_all_tiers_still_sends_highest_unfired_tier():
    # 90 days overdue but nothing sent yet - highest tier (urgent) fires, not "no
    # reminder because we're past the window".
    decision = determine_reminder(days_overdue=90, already_sent_reasons=set())
    assert decision.should_send is True
    assert decision.cadence_reason == TIER_30
    assert decision.severity == "urgent"


def test_all_tiers_already_sent_does_not_resend():
    all_reasons = {t[2] for t in REMINDER_TIERS}
    decision = determine_reminder(days_overdue=90, already_sent_reasons=all_reasons)
    assert decision.should_send is False
    assert decision.cadence_reason is None
    assert decision.severity is None


def test_jump_straight_to_urgent_when_earlier_tiers_already_sent_out_of_a_gap():
    # 35 days overdue, only the 30-day tier hasn't fired yet (say 1/7/14 fired on
    # earlier runs) - must send exactly the 30-day tier, not re-send a lower one.
    decision = determine_reminder(days_overdue=35, already_sent_reasons={TIER_DAY1, TIER_7, TIER_14})
    assert decision.cadence_reason == TIER_30


def test_skipped_lower_tier_never_fires_after_a_higher_tier_already_sent():
    # Regression: a record first hit the invoicing job at 15 days overdue, which
    # correctly skipped straight to the 14-day ("second reminder") tier without
    # ever sending the lower ones. Running the job again the same day used to
    # still find the lower reasons absent from already_sent and fire them - an
    # escalated reminder followed by a milder one. Must not resend any tier once a
    # higher-index tier has already gone out, even though its own exact reason
    # string was never logged.
    decision = determine_reminder(days_overdue=15, already_sent_reasons={TIER_14})
    assert decision.should_send is False


def test_adding_the_day_one_tier_cannot_retroactively_fire_for_older_records():
    """HISTORY SAFETY for the 1-day tier being added at index 0 after 7/14/30 were
    already in production. A record that had received the 7-day reminder before the
    new tier existed must never receive the day-1 notice afterwards - the
    `i > highest_sent_index` guard is what prevents it."""
    decision = determine_reminder(days_overdue=9, already_sent_reasons={TIER_7})
    assert decision.should_send is False

    # And one already fully escalated stays silent too.
    assert determine_reminder(days_overdue=40, already_sent_reasons={TIER_30}).should_send is False


def test_existing_persisted_reason_strings_still_resolve_to_tiers():
    """GUARD AGAINST RENAMING. `already_sent_reasons` is matched against
    cadence_reason values already stored in fee_reminders rows, so renaming a tier
    would orphan history: the old string would stop resolving to an index,
    highest_sent_index would fall back to -1, and a reminder that already went out
    would fire again. These literals are what is in the database - if this test
    fails because a tier was renamed, the rename needs a data migration, not a test
    update."""
    persisted = {
        "7 days overdue - first reminder",
        "14 days overdue - second reminder",
        "30 days overdue - third reminder, escalated",
    }
    assert persisted <= {t[2] for t in REMINDER_TIERS}

    # A record carrying the oldest persisted string is treated as having reached that
    # tier, not as having received nothing.
    decision = determine_reminder(days_overdue=8, already_sent_reasons={"7 days overdue - first reminder"})
    assert decision.should_send is False
