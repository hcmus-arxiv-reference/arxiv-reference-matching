"""Semantic Scholar 404 ("S2 has no record of the Publication") end to end.

Seen on Range Bảo, 15/11/2026: 2508.03220 (PDF only) answers
``Paper with id arXiv:2508.03220 not found``. The Engine records it as a
real S2-side gap (docs/data-contract.md 3.3), not as a crawl error.
"""
import csv
import json
from unittest.mock import Mock

import pytest

from src import make_stats
from src.common.corpus import FileCorpus
from src.crawl.discovery import Publication
from src.crawl.http_client import HttpClient, HttpResponse, HttpStatusError
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader
from src.crawl.validation import validate_crawl
from src.reporting.m1 import snapshot

FOUND, NOT_FOUND = "2508.02872", "2508.03220"


def crawl(tmp_path):
    """Two one-Version Publications; S2 knows FOUND (one row) and answers 404 for NOT_FOUND."""
    discovery, refs = Mock(), Mock()
    discovery.discover.side_effect = lambda pid: Publication(pid, "T", ["A. Author"], "2025-08-04", [], None, 1)

    def references(pid):
        if pid == NOT_FOUND:
            raise HttpStatusError(404, "Semantic Scholar")
        return [{"citedPaper": {"paperId": "s2", "externalIds": {"ArXiv": "1706.03762"},
                                "title": "Cited", "authors": [{"name": "A"}]}}]
    refs.references.side_effect = references
    http = HttpClient("offline", min_interval=0, transport=lambda *_: HttpResponse(
        200, {}, b"\\documentclass{article}\\begin{document}Text.\\end{document}"))
    pipeline = CrawlPipeline(discovery, ArxivSourceDownloader(http, tmp_path / "raw"), tmp_path, refs)
    stats = pipeline.crawl_ids([FOUND, NOT_FOUND])
    return pipeline, refs, stats


def test_engine_records_s2_not_found_and_exports_the_paper(tmp_path):
    pipeline, refs, stats = crawl(tmp_path)
    assert stats["errors"] == 0 and stats["references_success"] == 1
    assert stats["references_s2_not_found"] == 1
    task = pipeline.manifest.get(NOT_FOUND, None, "references")
    assert (task.status, task.http_status, task.error_reason) == ("unavailable", 404, None)
    assert pipeline.status(NOT_FOUND).complete
    bundles, tables = pipeline.export([FOUND, NOT_FOUND])
    assert {b["publication"].arxiv_id for b in bundles} == {FOUND, NOT_FOUND}
    import pyarrow.parquet as pq
    assert sorted(pq.read_table(tables["papers"])["arxiv_id"].to_pylist()) == [FOUND, NOT_FOUND]
    assert pq.read_table(tables["references"])["arxiv_id"].to_pylist() == [FOUND]
    pipeline.crawl_ids([NOT_FOUND])           # not asked again
    assert [c.args[0] for c in refs.references.call_args_list].count(NOT_FOUND) == 1


def test_other_s2_errors_stay_errors(tmp_path):
    pipeline, refs, _ = crawl(tmp_path)
    refs.references.side_effect = HttpStatusError(500, "Semantic Scholar")
    pipeline.crawl_ids(["2508.02873"])
    task = pipeline.manifest.get("2508.02873", None, "references")
    assert (task.status, task.http_status) == ("error", 500)


@pytest.mark.parametrize("payload", [
    {"format": 1, "arxiv_id": NOT_FOUND, "rows": [{"citedPaper": {}}], "s2_status": "not_found"},
    {"format": 1, "arxiv_id": NOT_FOUND, "rows": [], "s2_status": "maybe"},
])
def test_file_corpus_rejects_bad_not_found_files(tmp_path, payload):
    path = tmp_path / "references" / "2508-03220.json"
    path.parent.mkdir()
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        FileCorpus(tmp_path).read_references(NOT_FOUND)


def test_manifest_must_say_unavailable_for_a_not_found_file(tmp_path):
    pipeline, _, _ = crawl(tmp_path)
    task = pipeline.manifest.get(NOT_FOUND, None, "references")
    pipeline._record(NOT_FOUND, None, "references", "success", local_path=task.local_path,
                     checksum=task.checksum)
    assert not pipeline.status(NOT_FOUND).references_ok


def test_reports_count_s2_not_found_apart(tmp_path):
    pipeline, _, _ = crawl(tmp_path)
    data = tmp_path
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(json.dumps({"schema_version": 1, "member": "test",
                                     "range": {"prefix": "2508", "start": 2872, "end": 3220},
                                     "totals": {}}))
    observed = validate_crawl(data, benchmark)
    assert observed["observed"]["publications_s2_not_found"] == 1
    assert observed["observed"]["publications_complete"] == 2
    assert not [f for f in observed["findings"] if f["code"] == "references_invalid"]

    report = snapshot(data, [FOUND, NOT_FOUND])
    assert report["counts"]["s2_not_found"] == 1 and report["counts"]["references_success"] == 1
    assert report["counts"]["complete"] == 2

    ids = tmp_path / "ids.txt"
    ids.write_text(f"{FOUND}\n{NOT_FOUND}\n")
    out = tmp_path / "stats"
    make_stats.main(["--data-dir", str(data), "--ids-file", str(ids), "--out", str(out)])
    rows = {r["id"]: r for r in csv.DictReader((out / "papers.csv").open())}
    assert rows[NOT_FOUND]["status"] == "done" and rows[NOT_FOUND]["s2_status"] == "not_found"
    assert rows[NOT_FOUND]["n_refs"] == "" and rows[FOUND]["s2_status"] == "found"
