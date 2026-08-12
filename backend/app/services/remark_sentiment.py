"""Sentiment analysis for teacher remarks, feeding the early-warning risk scorer.

LIBRARY CHOICE
---------------
Uses `vaderSentiment` (VADER - Valence Aware Dictionary and sEntiment Reasoner), not
NLTK/spaCy/Hugging Face:
- It ships as a single pure-Python wheel (`py2.py3-none-any`) with the lexicon bundled
  in the package - no compiled C extensions, no per-platform/per-Python-version wheel
  matrix to worry about. After the dlib/face_recognition saga in the attendance-CV
  work (no Windows wheel for the real `dlib` on this Python version, needed a
  prebuilt-binary fork), that was the deciding factor.
- NLTK's own VADER implementation needs `nltk.download('vader_lexicon')` at runtime -
  a network call and a stateful local cache directory. vaderSentiment needs neither.
- spaCy and Hugging Face transformers are both far heavier (compiled extensions
  and/or a multi-hundred-MB model download) for what's a short-informal-text
  classification task - VADER was literally designed for exactly this kind of text
  (originally social media posts; short teacher remarks are a good fit).

WHAT THIS ANALYZES
--------------------
Real remark *text* going into this module is a placeholder concern, not a sentiment-
analysis concern - see app/models/risk.py's RemarkStub docstring. This module itself
has no opinion on where the text comes from; give it seeded RemarkStub rows today,
Person B's real remarks/report-card system tomorrow, no code change needed here.
"""

from __future__ import annotations

from dataclasses import dataclass

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

NEGATIVE_THRESHOLD = -0.05
POSITIVE_THRESHOLD = 0.05

_analyzer = SentimentIntensityAnalyzer()


@dataclass(frozen=True)
class SentimentResult:
    text: str
    compound: float
    """VADER's normalized composite score, -1 (most negative) to +1 (most positive)."""
    label: str
    """One of: negative, neutral, positive."""


def _label_for(compound: float) -> str:
    if compound <= NEGATIVE_THRESHOLD:
        return "negative"
    if compound >= POSITIVE_THRESHOLD:
        return "positive"
    return "neutral"


def analyze_sentiment(text: str) -> SentimentResult:
    if not text or not text.strip():
        raise ValueError("text must be non-empty")
    compound = _analyzer.polarity_scores(text)["compound"]
    return SentimentResult(text=text, compound=compound, label=_label_for(compound))


def analyze_sentiments(texts: list[str]) -> list[SentimentResult]:
    return [analyze_sentiment(t) for t in texts]
