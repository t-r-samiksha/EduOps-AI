import pytest

from app.services.remark_sentiment import analyze_sentiment, analyze_sentiments


def test_negative_remark_scores_negative():
    result = analyze_sentiment("Seems withdrawn and disengaged in class lately, struggling to keep up.")
    assert result.compound < 0
    assert result.label == "negative"


def test_positive_remark_scores_positive():
    result = analyze_sentiment("Consistently engaged and participates well in class discussions, great improvement!")
    assert result.compound > 0
    assert result.label == "positive"


def test_neutral_remark_scores_near_zero():
    result = analyze_sentiment("Submitted the assignment on time.")
    assert -0.05 < result.compound < 0.05
    assert result.label == "neutral"


def test_analyze_sentiments_preserves_order():
    texts = ["Great work today!", "Missed homework again.", "Submitted on time."]
    results = analyze_sentiments(texts)
    assert [r.text for r in results] == texts
    assert results[0].label == "positive"
    assert results[1].label == "negative"


def test_empty_text_raises():
    with pytest.raises(ValueError):
        analyze_sentiment("")


def test_whitespace_only_text_raises():
    with pytest.raises(ValueError):
        analyze_sentiment("   ")
