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


def _many(tmp_path: Path) -> tuple[Path, list[str]]:
    """Corpus ba Publication, bài giữa có Version lỗi (không có file gốc)."""
    corpus, _ = _corpus(tmp_path, {"main.tex": MAIN})
    ids = [ID]
    for number, files in (("2508.02873", {"notes.tex": "no root here"}),
                          ("2508.02874", {"main.tex": MAIN.replace("Intro", "Method")})):
        other, _ = _corpus(tmp_path / number, files)
        key = number.replace(".", "-")
        for sub in ("metadata", "raw"):
            for path in sorted((other / sub).rglob("*")):
                if path.is_file():
                    target = corpus / sub / path.relative_to(other / sub)
                    target = Path(str(target).replace(KEY, key))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(path.read_text(encoding="utf-8").replace(ID, number),
                                      encoding="utf-8")
        ids.append(number)
    # Receipt và metadata của bài sao chép phải khớp ID mới: tính lại receipt.
    for number in ids[1:]:
        directory = corpus / "raw" / number.replace(".", "-") / "v1"
        digests = {p.name: file_digest(p) for p in directory.iterdir()
                   if p.suffix == ".tex"}
        write_json(directory / "source.json", {
            "format": 1, "arxiv_id": number, "version": 1, "status": "success", "files": digests,
            "checksum": hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest(),
        })
    return corpus, ids


def test_parallel_run_writes_the_same_tables_as_sequential(tmp_path: Path) -> None:
    corpus, ids = _many(tmp_path)
    serial = run_batch(corpus, tmp_path / "serial", arxiv_ids=ids, workers=1)
    parallel = run_batch(corpus, tmp_path / "parallel", arxiv_ids=ids, workers=2)

    for name in ("elements", "hierarchy", "bibtex"):
        a = (tmp_path / "serial" / "tables" / f"{name}.parquet").read_bytes()
        b = (tmp_path / "parallel" / "tables" / f"{name}.parquet").read_bytes()
        assert a == b, name
    assert ((tmp_path / "serial" / "log" / "versions.jsonl").read_text()
            == (tmp_path / "parallel" / "log" / "versions.jsonl").read_text())
    assert parallel["workers"] == 2
    assert parallel["publications_failed"] == serial["publications_failed"] == 1
    assert parallel["publications_succeeded"] == 2

    resumed = run_batch(corpus, tmp_path / "parallel", arxiv_ids=ids, workers=2)
    assert resumed["publications_resumed"] == 3


def test_workers_must_be_positive(tmp_path: Path) -> None:
    import pytest

    corpus, _ = _corpus(tmp_path, {"main.tex": MAIN})
    with pytest.raises(ValueError):
        run_batch(corpus, tmp_path / "out", arxiv_ids=[ID], workers=0)


def test_sequential_run_reports_no_child_memory(tmp_path: Path) -> None:
    """Chạy tuần tự không có tiến trình con parse, kể cả khi pipeline gọi `git rev-parse`."""
    corpus, ids = _many(tmp_path)
    serial = run_batch(corpus, tmp_path / "serial", arxiv_ids=ids, workers=1)
    assert serial["peak_rss_children_mb"] == 0.0


def test_cli_rejects_negative_workers(tmp_path: Path) -> None:
    import pytest

    from scripts.parse_range import main

    with pytest.raises(SystemExit) as exc:
        main(["--data-dir", str(tmp_path), "--out-dir", str(tmp_path / "out"), "--workers", "-1"])
    assert exc.value.code == 2


def _add_version(corpus: Path, number: str, version: int, files: dict[str, str]) -> None:
    """Ghi một Version đã xác minh như crawler: file trước, receipt sau."""
    directory = corpus / "raw" / number.replace(".", "-") / f"v{version}"
    for name, text in files.items():
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(text, encoding="utf-8")
    digests = {name: file_digest(directory / name) for name in files}
    write_json(directory / "source.json", {
        "format": 1, "arxiv_id": number, "version": version, "status": "success", "files": digests,
        "checksum": hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest(),
    })


def test_new_version_reparses_only_its_publication_and_keeps_old_ids(tmp_path: Path) -> None:
    """Chạy M2 khi crawl còn dở: Version chưa về là ``missing``; lần sau chỉ parse lại bài đó."""
    corpus, ids = _many(tmp_path)
    meta = corpus / "metadata" / f"{KEY}.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["publication"].update(versions=2, revised_dates=["2025-09-01"])
    write_json(meta, data)

    out = tmp_path / "out"
    first = run_batch(corpus, out, arxiv_ids=ids)
    assert first["versions_missing"] == 1
    old = {row["element_id"] for row in parse_publication(corpus, ID, parse_dir=out).result.elements}

    _add_version(corpus, ID, 2, {"main.tex": MAIN.replace("Intro", "Introduction")})
    second = run_batch(corpus, out, arxiv_ids=ids)
    assert second["versions_missing"] == 0
    assert second["publications_resumed"] == len(ids) - 1, "chỉ bài có Version mới được parse lại"
    new = {row["element_id"] for row in parse_publication(corpus, ID, parse_dir=out).result.elements}
    assert old < new, "Element của v1 giữ nguyên element_id; v2 chỉ thêm Element mới"


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
