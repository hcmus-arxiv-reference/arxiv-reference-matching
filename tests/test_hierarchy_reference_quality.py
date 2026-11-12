"""Semantic acceptance fixtures for the optional independently built Agy annotator.

The generated annotation tool is an ignored local evaluation artifact. These
fixtures contain no production predictions and run only when that tool exists.
"""

import hashlib
import importlib.util
from pathlib import Path

import pytest

from src.parse.Hierarchy.compare_reference import DEFAULT_REFERENCES, validate_reference


@pytest.fixture(scope="module")
def annotator_module():
    path = DEFAULT_REFERENCES / "annotate_reference.py"
    if not path.is_file():
        pytest.skip("Agy annotation artifact is not available")
    spec = importlib.util.spec_from_file_location("independent_reference_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def annotate(module, tmp_path, body, *, preamble=""):
    path = tmp_path / "source.tex"
    path.write_text(preamble + r"\begin{document}" + body + r"\end{document}", encoding="utf-8")
    data = module.ReferenceAnnotator(str(path), "2508-02872/v1", hashlib.sha256(path.read_bytes()).hexdigest()).parse()
    assert validate_reference(data, path.read_bytes(), "2508-02872/v1") == []
    return data["nodes"]


def test_comment_heading_does_not_discard_preceding_prose(annotator_module, tmp_path):
    nodes = annotate(annotator_module, tmp_path, r"\section{Intro}Keep this. % \section{Fake}" + "\nNext sentence.")
    assert [node["content"] for node in nodes if node["kind"] == "section"] == ["Intro"]
    assert [node["content"] for node in nodes if node["kind"] == "sentence"] == ["Keep this.", "Next sentence."]


@pytest.mark.parametrize("prefix", [
    r"\begin{verbatim}\section{Fake}\end{verbatim}",
    r"\verb|\section{Fake}|",
    r"\newcommand{\example}{\section{Fake}}",
    r"\def\example#1{\section{Fake}}",
])
def test_literal_and_definition_headings_are_not_active(annotator_module, tmp_path, prefix):
    nodes = annotate(annotator_module, tmp_path, prefix + r"\section{Real}Body.")
    assert [node["content"] for node in nodes if node["kind"] == "section"] == ["Real"]


def test_reference_word_is_not_bibliography_section(annotator_module, tmp_path):
    nodes = annotate(annotator_module, tmp_path,
                     r"\section{Reference implementation}Keep.\section{References}Remove."
                     r"\section*{Acknowledgements}Thanks.\appendix\section{Appendix}More.")
    assert [node["content"] for node in nodes if node["kind"] == "section"] == [
        "Reference implementation", "Acknowledgements", "Appendix"]
    assert "Remove." not in [node["content"] for node in nodes]


@pytest.mark.parametrize("environment", ["displaymath", "eqnarray", "align"])
def test_entire_display_environment_is_one_formula(annotator_module, tmp_path, environment):
    nodes = annotate(annotator_module, tmp_path,
                     "\\begin{" + environment + r"}a=b.\\c=d.\end{" + environment + "} Next.")
    formulas = [node for node in nodes if node["kind"] == "formula"]
    assert len(formulas) == 1
    assert r"\begin{equation}" in formulas[0]["content"]
    assert [node["content"] for node in nodes if node["kind"] == "sentence"] == ["Next."]


def test_commented_document_start_does_not_expose_preamble(annotator_module, tmp_path):
    nodes = annotate(annotator_module, tmp_path, r"\section{Real}Body.",
                     preamble="% \\begin{document}\n\\newcommand{\\example}{\\section{Fake}}\n")
    assert [node["content"] for node in nodes if node["kind"] == "section"] == ["Real"]
    assert [node["content"] for node in nodes if node["kind"] == "sentence"] == ["Body."]


def test_escaped_backslash_before_percent_does_not_escape_comment(annotator_module, tmp_path):
    nodes = annotate(annotator_module, tmp_path,
                     r"\section{Real}Keep \% text. \\% \section{Fake}" + "\nNext.")
    assert [node["content"] for node in nodes if node["kind"] == "section"] == ["Real"]


@pytest.mark.parametrize("math", [r"$a. b$", r"\(a. b\)"])
def test_sentence_protection_for_math_commands_and_abbreviations(annotator_module, tmp_path, math):
    nodes = annotate(annotator_module, tmp_path,
                     r"\section{Intro}First i.e. useful. See Fig. 1. Value 3.14. "
                     r"Smith et al. agree. Math " + math + r" works \cite{a. b.}. Next.")
    sentences = [node["content"] for node in nodes if node["kind"] == "sentence"]
    assert len(sentences) == 6
    assert r"$a. b$" in sentences[-2] and r"\cite{a. b.}" in sentences[-2]
