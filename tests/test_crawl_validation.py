import json
from pathlib import Path
from unittest.mock import Mock

from src.crawl.discovery import Publication
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader
from src.crawl.validation import validate_crawl


def make_run(tmp_path: Path):
    data = tmp_path / "data"
    identifier = "2508.02872"
    discovery = Mock()
    discovery.discover.return_value = Publication(identifier, "Paper", ["A. Author"],
                                                    "2025-08-04", [], None, 1)
    http = HttpClient("test", transport=lambda *_: HttpResponse(
        200, {}, b"\\documentclass{article}\\begin{document}Text.\\end{document}"))
    references = Mock()
    references.references.return_value = [{"citedPaper": {"paperId": "s2-id",
        "externalIds": {"ArXiv": "1234.56789"}, "title": "Cited", "authors": [{"name": "A"}]}}]
    pipeline = CrawlPipeline(discovery, ArxivSourceDownloader(http, data / "raw"), data, references)
    pipeline.crawl_ids([identifier])
    return data


def benchmark(path: Path, **totals):
    path.write_text(json.dumps({"schema_version": 1, "member": "test",
        "range": {"prefix": "2508", "start": 2872, "end": 2872},
        "ids_attempted": 1, "totals": totals}), encoding="utf-8")


def test_validate_crawl_checks_real_manifest_and_receipts_read_only(tmp_path):
    data = make_run(tmp_path)
    before = (data / "manifests" / "crawl.jsonl").read_bytes()
    report_file = tmp_path / "benchmark.json"
    benchmark(report_file, publications_found=1, publications_complete=1,
              versions_expected=1, versions_ok=1, versions_non_tex=0,
              versions_failed=0, references_total=1, references_with_arxiv_id=1,
              publications_s2_ok=1)

    report = validate_crawl(data, report_file)

    assert report["ok"] is True
    assert report["observed"]["publications_complete"] == 1
    assert report["observed"]["references_with_arxiv_id"] == 1
    assert (data / "manifests" / "crawl.jsonl").read_bytes() == before


def test_validate_crawl_reports_tampered_source_and_counter_mismatch(tmp_path):
    data = make_run(tmp_path)
    (data / "raw" / "2508-02872" / "v1" / "single.tex").write_text("edited", encoding="utf-8")
    report_file = tmp_path / "benchmark.json"
    benchmark(report_file, versions_ok=1, versions_failed=0)

    report = validate_crawl(data, report_file)

    codes = [finding["code"] for finding in report["findings"]]
    assert report["ok"] is False
    assert "counter_mismatch" in codes
    assert report["observed"]["versions_ok"] == 0
    assert report["observed"]["versions_failed"] == 1


def test_validate_crawl_rejects_benchmark_attempt_count_outside_range(tmp_path):
    data = make_run(tmp_path)
    report_file = tmp_path / "benchmark.json"
    benchmark(report_file, publications_complete=1)
    payload = json.loads(report_file.read_text())
    payload["ids_attempted"] = 2
    report_file.write_text(json.dumps(payload))

    report = validate_crawl(data, report_file)

    assert report["ok"] is False
    assert any(item["code"] == "benchmark_ids_attempted" for item in report["findings"])
