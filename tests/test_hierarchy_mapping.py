"""Keep hierarchy configuration aligned with the shared Element contract."""

import json
from pathlib import Path
import re

import pytest

from src.common.schema import ELEMENT_KINDS


MAPPING_PATH = Path(__file__).resolve().parents[1] / "src/parse/Hierarchy/mapping.json"


def load_mapping():
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, f"Duplicate mapping key: {key}"
            result[key] = value
        return result

    return json.loads(MAPPING_PATH.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)


def test_mapping_kinds_match_shared_schema():
    mapping = load_mapping()
    grouped = [kind for kinds in mapping["groups"].values() for kind in kinds]
    assert len(grouped) == len(set(grouped))
    assert set(grouped) == set(ELEMENT_KINDS)

    def check_kinds(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"kind", "parent_kind"}:
                    assert item in ELEMENT_KINDS
                check_kinds(item)
        elif isinstance(value, list):
            for item in value:
                check_kinds(item)

    check_kinds(mapping)


def test_starred_headings_keep_kind_and_order():
    commands = load_mapping()["commands"]
    kinds = ["chapter", "section", "subsection", "subsubsection", "paragraph"]
    for level, kind in enumerate(kinds, 1):
        rule = commands["\\" + kind]
        assert rule == commands["\\" + kind + "*"]
        assert rule["kind"] == kind
        assert rule["level"] == level


def test_figures_tables_and_block_math_remain_atomic():
    mapping = load_mapping()
    for name in ("figure", "figure*", "table", "table*"):
        assert mapping["environments"][name]["kind"] == "figure"
        assert mapping["environments"][name]["atomic"] is True
    for name in ("equation", "equation*", "displaymath"):
        assert mapping["environments"][name]["kind"] == "formula"
        assert mapping["environments"][name]["atomic"] is True
    for rule in mapping["math_delimiters"]["inline"]:
        assert "kind" not in rule
        assert rule["action"] == "preserve_in_sentence"


def test_sentences_lists_and_reference_exclusion_follow_contract():
    mapping = load_mapping()
    assert mapping["sentence"]["requires_latex_tag"] is False
    assert mapping["commands"][r"\item"]["parent_kind"] == "itemize"
    assert mapping["environments"]["itemize"]["children"] == "items"
    assert "thebibliography" in mapping["exclusions"]["environments"]
    assert "References" in mapping["exclusions"]["heading_titles"]
    assert "Acknowledgements" in mapping["required_inclusions"]["heading_titles"]
    assert "Appendices" in mapping["required_inclusions"]["heading_titles"]


def test_pending_rules_are_not_silently_active():
    mapping = load_mapping()
    for decision in mapping["pending_decisions"]:
        for tag in decision["tags"]:
            assert tag not in mapping["commands"]
            if decision.get("decision") == "multiline_formula_segmentation":
                assert mapping["environments"][tag]["kind"] == "formula"
                assert mapping["environments"][tag]["segmentation"] == "pending"
                assert "atomic" not in mapping["environments"][tag]
            else:
                assert tag not in mapping["environments"]


@pytest.mark.parametrize("name", [
    "align", "align*", "gather", "gather*", "multline", "multline*", "eqnarray", "eqnarray*",
])
def test_multiline_math_is_one_normalized_formula(name):
    rule = load_mapping()["environments"][name]
    assert rule["kind"] == "formula"
    assert rule["content"] == "whole_environment"
    assert rule["segmentation"] == "whole_environment"
    assert rule["atomic"] is True
    assert rule["normalize_to"] == "equation"


@pytest.mark.parametrize("text,expected", [
    ("See Fig. 1.", "Fig."),
    ("See Fig. 2.", "Fig."),
    ("See Fig. 10.", "Fig."),
    ("See Figs. 2 and 3.", "Figs."),
    ("See fig.~12.", "fig."),
    ("See Fig.\u00a02.", "Fig."),
    ("See Fig.\n2.", "Fig."),
    (r"See Fig.\ref{fig:overview}.", "Fig."),
    (r"See Fig.~\autoref{fig:overview}.", "Fig."),
    (r"See Fig. \cref{fig:overview}.", "Fig."),
    ("A fig. grows here.", None),
    ("Figure 2.", None),
    ("The result follows. Another sentence.", None),
])
def test_figure_reference_pattern_only_protects_abbreviation_period(text, expected):
    rules = load_mapping()["sentence"]["protected_patterns"]
    rule = next(rule for rule in rules if rule["name"] == "figure_reference")
    match = re.search(rule["pattern"], text)
    assert (match.group() if match else None) == expected
    if match:
        assert match.end() < len(text)
        assert text.endswith(".")


def test_all_configured_patterns_compile_and_literal_abbreviations_are_separate():
    sentence = load_mapping()["sentence"]
    assert {"inline_math", "block_math"} <= set(sentence["protected_regions"])
    assert {"i.e.", "et al."} <= set(sentence["abbreviations"])
    assert "Fig. 1" not in sentence["abbreviations"]
    for rule in sentence["protected_patterns"]:
        re.compile(rule["pattern"])


def test_actions_and_unique_configuration_entries():
    mapping = load_mapping()
    for rules in (mapping["commands"], mapping["environments"]):
        assert all("action" in rule for rule in rules.values())
    patterns = mapping["sentence"]["protected_patterns"]
    assert len({rule["name"] for rule in patterns}) == len(patterns)
    for key in ("commands", "environments", "heading_titles"):
        entries = mapping["exclusions"][key]
        assert len(entries) == len(set(entries))
    assert mapping["commands"][r"\textbf"]["contexts"] == ["prose", "heading", "figure"]
    for name in ("verbatim", "lstlisting", "minted"):
        assert mapping["environments"][name]["whitespace"] == "preserve_exact_body"
