"""Golden and semantic-boundary cases for M2.4a."""
import json
from pathlib import Path

import pytest

from src.parse.normalize import normalize


GOLDEN = Path(__file__).parent / "fixtures/m2/lists-figures-math/normalize.json"


@pytest.mark.parametrize("case", json.loads(GOLDEN.read_text(encoding="utf-8")))
def test_normalize_golden(case):
    for raw in case["inputs"]:
        actual = normalize(case["kind"], raw)
        assert actual == case["expected"]
        assert normalize(case["kind"], actual) == actual


def test_preserves_citation_arguments_literals_and_non_placement_brackets():
    citation = r"\citep[see][p. 3]{oldKey, otherKey}"
    literal = r"\verb|\small  \(x\) % text|"
    url = r"\url{https://example.test/a%20b?q=$x$}"
    raw = rf"\noindent [htbp] {citation} {literal} {url}"
    expected = f"[htbp] {citation} {literal} {url}"
    assert normalize("sentence", raw) == expected
    assert normalize("sentence", expected) == expected


def test_multiline_formula_keeps_alignment_and_line_breaks():
    raw = r"\begin{align*}a&=b\\ c&=d\end{align*}"
    expected = r"\begin{equation}\begin{aligned}a&=b\\ c&=d\end{aligned}\end{equation}"
    assert normalize("formula", raw) == expected
    assert normalize("formula", expected) == expected


def test_cleanup_keeps_command_boundaries_and_table_content():
    assert normalize("sentence", r"$\alpha\hspace{1em}x$") == r"$\alpha x$"
    raw = r"\begin{table}[t]\toprule[1pt]A & B\\\midrule 3 & 4\\\bottomrule\end{table}"
    assert normalize("figure", raw) == r"\begin{table}A & B\\ 3 & 4\\\end{table}"


def test_math_environment_with_spaced_control_word_is_idempotent():
    assert normalize("section", r"Model \begin {math} y \end {math}") == "Model $y$"
