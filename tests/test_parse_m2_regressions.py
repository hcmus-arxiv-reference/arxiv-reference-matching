"""Regressions found by re-running the failed Versions of the 5-Range M2 run (26/11/2026)."""
from pathlib import Path

from src.parse.bibtex import merge_bibtex
from src.parse.export import extract_cite_keys, rewrite_citations
from src.parse.pipeline import _describe
from src.parse.source import assemble_source
from src.parse.structure import build_structure
from src.parse.types import normalize_cite_key, validate_A, validate_B_prime


def _bundle(tmp_path: Path, files: dict[str, str]):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return assemble_source(tmp_path)


def test_info_issue_from_a_resolved_include_passes_validation(tmp_path):
    # \input{Body} resolved to body.tex by case: an "info" issue, not a failure.
    bundle = _bundle(tmp_path, {
        "main.tex": "\\documentclass{article}\n\\begin{document}\n\\input{Body}\n\\end{document}\n",
        "body.tex": "Text.",
    })
    assert bundle.status == "ready"
    assert [i.severity for i in bundle.issues if i.code == "include_case_mismatch"] == ["info"]
    validate_A(bundle)


def test_cite_key_with_inner_space_is_one_key_everywhere(tmp_path):
    bundle = _bundle(tmp_path, {"main.tex": (
        "\\documentclass{article}\n\\begin{document}\n"
        "See \\cite{pavia university, H.\n  Triebel}.\n"
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{pavia university} Pavia University dataset, 2001.\n"
        "\\bibitem{H. Triebel} H. Triebel. Theory of Function Spaces. 1983.\n"
        "\\end{thebibliography}\n\\end{document}\n")})
    _, bib = build_structure(bundle, "2508.00001", 1)
    assert bib.cite_keys_used == ["pavia university", "H. Triebel"]
    validate_B_prime(bib)
    result = merge_bibtex("2508.00001", [bib])
    assert {row["citation_key"] for row in result.entries} == {"pavia university", "H. Triebel"}
    assert result.stats["unresolved"] == 0
    text = rewrite_citations("See \\cite{pavia university, H.\n  Triebel}.", result.key_map["1"])
    assert extract_cite_keys(text) == ["pavia university", "H. Triebel"]


def test_normalize_cite_key_collapses_whitespace():
    assert normalize_cite_key("  Qian et\n\t\tal ") == "Qian et al"


def test_failed_version_reason_names_the_stage_and_message():
    def stage():
        raise ValueError("Missing active document environment\nsecond line")
    try:
        stage()
    except ValueError as exc:
        reason = _describe(exc)
    # Raised outside src/, so the module is unknown; the message keeps its first line.
    assert reason == "unknown: ValueError: Missing active document environment"
