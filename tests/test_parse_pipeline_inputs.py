"""Pipeline M2 dùng sidecar bibliography và file gốc đã review (data-contract mục 4.2).

Sidecar do ``scripts/recover_bibtex_sources.py`` tạo khôi phục ``.bib/.bbl`` mà M1 lọc mất;
root đã review chọn file gốc cho Version ``ambiguous_root``. Hai đầu vào này phải đi qua
``parse_publication``/``run_batch`` và đổi khóa checkpoint.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.common.corpus import file_digest
from src.common.json_io import write_json
from src.parse.pipeline import parse_publication, run_batch

ID = "2508.02872"
KEY = "2508-02872"


def _corpus(tmp_path: Path, files: dict[str, str]) -> tuple[Path, Path]:
    """Corpus M1 tối thiểu: một Publication, một Version có receipt hợp lệ."""
    corpus = tmp_path / "corpus"
    metadata = {"format": 1, "publication": {
        "arxiv_id": ID, "title": "Fixture", "authors": ["A. Doe"], "submission_date": "2025-08-04",
        "revised_dates": [], "venue": None, "versions": 1,
    }}
    write_json(corpus / "metadata" / f"{KEY}.json", metadata)
    directory = corpus / "raw" / KEY / "v1"
    digests = {}
    for name, text in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        digests[name] = file_digest(path)
    write_json(directory / "source.json", {
        "format": 1, "arxiv_id": ID, "version": 1, "status": "success", "files": digests,
        "checksum": hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest(),
    })
    write_json(directory / "metadata.json", metadata)
    return corpus, directory


def _supplement(tmp_path: Path, directory: Path, files: dict[str, str]) -> Path:
    """Sidecar cùng định dạng ``recover_bibtex_sources.prepare_sidecar`` ghi ra."""
    root = tmp_path / "supplement"
    target = root / KEY / "v1"
    for name, text in files.items():
        path = target / "files" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    write_json(target / "manifest.json", {
        "format": 1, "arxiv_id": ID, "version": 1,
        "receipt_sha256": file_digest(directory / "source.json"), "archive_sha256": "a" * 64,
        "files": {name: file_digest(target / "files" / name) for name in files},
    })
    return root


MAIN = (r"\documentclass{article}\begin{document}\section{Intro}"
        "\nWe follow prior work \\cite{doe20}.\n\\bibliography{refs}\\end{document}\n")


def test_sidecar_restores_bibliography_and_changes_checkpoint_key(tmp_path: Path) -> None:
    corpus, directory = _corpus(tmp_path, {"main.tex": MAIN})
    out = tmp_path / "out"

    plain = parse_publication(corpus, ID, parse_dir=out).result
    assert plain.bibtex == []
    assert plain.unresolved_keys == frozenset({"doe20"})

    supplement = _supplement(tmp_path, directory, {
        "refs.bib": "@article{doe20, title={A Title}, author={Doe, A.}, year={2020}}",
    })
    outcome = parse_publication(corpus, ID, parse_dir=out, supplement_dir=supplement)
    assert outcome.resumed is False, "checkpoint không có sidecar không được dùng lại"
    recovered = outcome.result
    assert [row["citation_key"] for row in recovered.bibtex] == ["doe20"]
    assert recovered.unresolved_keys == frozenset()
    assert "bibliography_recovered" in recovered.version_logs[0]["issues"]

    again = parse_publication(corpus, ID, parse_dir=out, supplement_dir=supplement)
    assert again.resumed is True
    assert [row["citation_key"] for row in again.result.bibtex] == ["doe20"]


def test_run_batch_counts_recovered_versions(tmp_path: Path) -> None:
    corpus, directory = _corpus(tmp_path, {"main.tex": MAIN})
    supplement = _supplement(tmp_path, directory, {
        "main.bbl": r"\begin{thebibliography}{1}\bibitem{doe20} A. Doe. A Title. 2020.\end{thebibliography}",
    })
    metrics = run_batch(corpus, tmp_path / "out", arxiv_ids=[ID], supplement_dir=supplement)
    assert metrics["bibliography_supplement"] is True
    assert metrics["versions_bibliography_recovered"] == 1
    assert metrics["bibtex_unresolved_keys"] == 0
    assert metrics["publications_succeeded"] == 1


def _two_roots(tmp_path: Path) -> tuple[Path, Path]:
    body = r"\documentclass{article}\begin{document}\section{S}Text %s.\end{document}"
    return _corpus(tmp_path, {"paper.tex": body % "paper", "draft.tex": body % "draft"})


def test_reviewed_root_resolves_ambiguous_root(tmp_path: Path) -> None:
    corpus, directory = _two_roots(tmp_path)
    plain = parse_publication(corpus, ID, parse_dir=tmp_path / "plain").result
    assert plain.version_logs[0]["status"] == "failed"
    assert "ambiguous_root" in plain.version_logs[0]["issues"]

    review = {"arxiv_id": ID, "version": 1, "root_file": "paper.tex", "reason": "fixture",
              "receipt_sha256": file_digest(directory / "source.json"),
              "root_sha256": file_digest(directory / "paper.tex")}
    reviewed = parse_publication(corpus, ID, parse_dir=tmp_path / "reviewed",
                                 root_reviews={(ID, 1): review}).result
    assert reviewed.version_logs[0]["status"] == "parsed"
    assert any("Text paper." in row["content"] for row in reviewed.elements)


def test_stale_root_review_fails_the_version_instead_of_guessing(tmp_path: Path) -> None:
    corpus, directory = _two_roots(tmp_path)
    review = {"arxiv_id": ID, "version": 1, "root_file": "paper.tex", "reason": "fixture",
              "receipt_sha256": "0" * 64, "root_sha256": file_digest(directory / "paper.tex")}
    result = parse_publication(corpus, ID, parse_dir=tmp_path / "out",
                               root_reviews={(ID, 1): review}).result
    assert result.version_logs[0]["status"] == "failed"


def test_metadata_title_selects_root_and_is_logged(tmp_path: Path) -> None:
    """ADR 0005: the metadata title picks the root; the rule is recorded in the Version log."""
    body = r"\documentclass{article}\title{%s}\begin{document}\section{S}Text %s.\end{document}"
    corpus, _ = _corpus(tmp_path, {"paper.tex": body % ("Fixture", "paper"),
                                   "draft.tex": body % ("Old draft", "draft")})
    result = parse_publication(corpus, ID, parse_dir=tmp_path / "out").result
    log = result.version_logs[0]
    assert log["status"] == "parsed"
    assert "root_selected_by_title" in log["issues"]
    assert any("Text paper." in row["content"] for row in result.elements)
    assert not any("Text draft." in row["content"] for row in result.elements)
