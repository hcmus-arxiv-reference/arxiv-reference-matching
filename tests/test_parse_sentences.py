
"""Tests for deterministic sentence splitting."""

import json
from pathlib import Path

import pytest

from src.parse.sentences import split_sentences


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "m2"
    / "hard-sentences"
    / "cases.json"
)

CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=[case["id"] for case in CASES],
)
def test_hard_sentence_splitting(case):
    actual = split_sentences(case["input"])
    assert actual == case["expected"]


def test_empty_input():
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_single_sentence_without_final_punctuation():
    text = "This is a sentence without punctuation"
    assert split_sentences(text) == [text]


def test_original_sentence_content_is_preserved():
    text = "The value is 3.14. We use it."
    result = split_sentences(text)

    assert result == [
        "The value is 3.14.",
        "We use it.",
    ]


# ------------------------------------------------------------
# LeafTree conversion tests
# ------------------------------------------------------------


def test_sentence_split_protects_math_environment():
    text = (
        r"Use \begin{math}x=1.2\end{math} here. "
        r"Next sentence."
    )

    assert split_sentences(text) == [
        r"Use \begin{math}x=1.2\end{math} here.",
        "Next sentence.",
    ]
