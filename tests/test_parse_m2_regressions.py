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



def test_assembler_crash_on_an_empty_version_records_the_reason(tmp_path):
    import json
    from scripts import m2_sample
    from src.parse.pipeline import run_batch
    corpus = tmp_path / "corpus"
    m2_sample.make_mock(corpus, size=5, seed=20261112)
    arxiv_id = next(p.name.replace("-", ".") for p in sorted((corpus / "raw").iterdir())
                    if any((v / "main.tex").exists() or list(v.glob("*.tex")) for v in p.glob("v*")))
    vdir = corpus / "raw" / arxiv_id.replace(".", "-") / "v1"
    for f in list(vdir.iterdir()):
        if f.name != "source.json":
            f.unlink()
    (vdir / "source.json").write_text(json.dumps({
        "format": 1, "arxiv_id": arxiv_id, "version": 1, "status": "unavailable",
        "http_status": 404, "checksum": "", "files": {}}), encoding="utf-8")

    def crashing(path):
        if path == vdir:
            raise OSError("disk read failed")
        return assemble_source(path)

    run_batch(corpus, tmp_path / "out", arxiv_ids=[arxiv_id], assemble_fn=crashing)
    rows = [json.loads(line) for line in
            (tmp_path / "out" / "log" / "versions.jsonl").read_text(encoding="utf-8").splitlines()]
    row = next(r for r in rows if r["arxiv_id"] == arxiv_id and r["version"] == 1)
    assert row["status"] == "failed"
    assert row["error"].endswith("OSError: disk read failed")
