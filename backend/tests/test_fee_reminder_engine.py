from app.services.fee_reminder_engine import REMINDER_TIERS, determine_reminder


def test_not_overdue_never_sends():
    decision = determine_reminder(days_overdue=0, already_sent_reasons=set())
    assert decision.should_send is False


def test_negative_days_overdue_never_sends():
    decision = determine_reminder(days_overdue=-3, already_sent_reasons=set())
    assert decision.should_send is False


def test_below_first_tier_does_not_send():
    decision = determine_reminder(days_overdue=5, already_sent_reasons=set())
    assert decision.should_send is False


def test_seven_days_overdue_sends_first_tier():
    decision = determine_reminder(days_overdue=7, already_sent_reasons=set())
    assert decision.should_send is True
    assert decision.cadence_reason == REMINDER_TIERS[0][2]
    assert decision.severity == "normal"


def test_between_tiers_sends_the_highest_reached_tier_not_already_sent():
    # 20 days overdue: tiers 7 and 14 both reached; if 7-day already sent, the
    # 14-day tier is the correct next reminder (highest reached, not yet sent).
    decision = determine_reminder(days_overdue=20, already_sent_reasons={REMINDER_TIERS[0][2]})
    assert decision.should_send is True
    assert decision.cadence_reason == REMINDER_TIERS[1][2]
    assert decision.severity == "normal"


def test_thirty_days_overdue_sends_urgent_tier():
    decision = determine_reminder(days_overdue=30, already_sent_reasons={REMINDER_TIERS[0][2], REMINDER_TIERS[1][2]})
    assert decision.should_send is True
    assert decision.cadence_reason == REMINDER_TIERS[2][2]
    assert decision.severity == "urgent"


def test_well_past_all_tiers_still_sends_highest_unfired_tier():
    # 90 days overdue but nothing sent yet - highest tier (urgent) fires, not "no
    # reminder because we're past the window".
    decision = determine_reminder(days_overdue=90, already_sent_reasons=set())
    assert decision.should_send is True
    assert decision.cadence_reason == REMINDER_TIERS[2][2]
    assert decision.severity == "urgent"


def test_all_tiers_already_sent_does_not_resend():
    all_reasons = {t[2] for t in REMINDER_TIERS}
    decision = determine_reminder(days_overdue=90, already_sent_reasons=all_reasons)
    assert decision.should_send is False
    assert decision.cadence_reason is None
    assert decision.severity is None


def test_jump_straight_to_urgent_when_earlier_tiers_already_sent_out_of_a_gap():
    # 35 days overdue, only the 30-day tier hasn't fired yet (say 7/14 fired on
    # earlier runs) - must send exactly the 30-day tier, not re-send 7 or 14.
    decision = determine_reminder(days_overdue=35, already_sent_reasons={REMINDER_TIERS[0][2], REMINDER_TIERS[1][2]})
    assert decision.cadence_reason == REMINDER_TIERS[2][2]
