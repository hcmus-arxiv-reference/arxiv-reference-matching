"""A Version arXiv answers 404/410 for is a real Version with an empty record (C11).

Instructor, Q&A question 23.2 (read 19/11/2026): mark such a Version "not
downloadable, 404" and still keep an empty record like a PDF-only Version; do
not look for another source. Seen on Range Bảo: 48 Versions of 44 Publications,
all marked "(withdrawn)" in the arXiv submission history, e.g. 2508.03014 v2.
"""
import csv
import json
from unittest.mock import Mock

import pyarrow.parquet as pq

from src import make_stats
from src.common.corpus import FileCorpus, verified_source
from src.crawl.discovery import Publication
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader
from src.crawl.validation import validate_crawl
from src.parse.source import assemble_source
from src.reporting.m1 import snapshot

PARTLY, WITHDRAWN = "2508.03014", "2508.02961"   # v2 gone; every Version gone
TEX = b"\\documentclass{article}\\begin{document}Text.\\end{document}"


def crawl(tmp_path):
    """PARTLY: v1 TeX, v2 404. WITHDRAWN: v1 and v2 404. S2 knows both (one row)."""
    discovery, refs = Mock(), Mock()
    discovery.discover.side_effect = lambda pid: Publication(
        pid, "T", ["A. Author"], "2025-08-04", ["2025-10-11"], None, 2)
    refs.references.return_value = [{"citedPaper": {"paperId": "s2", "externalIds": {"ArXiv": "1706.03762"},
                                                    "title": "Cited", "authors": [{"name": "A"}]}}]
    requested = []

    def transport(request, _timeout):
        url = request.full_url
        requested.append(url)
        if url.endswith(f"{PARTLY}v1"):
            return HttpResponse(200, {}, TEX)
        return HttpResponse(404, {"Content-Type": "text/html"}, b"<html>404</html>")
    http = HttpClient("offline", min_interval=0, transport=transport, sleeper=lambda _: None)
    pipeline = CrawlPipeline(discovery, ArxivSourceDownloader(http, tmp_path / "raw"), tmp_path, refs)
    stats = pipeline.crawl_ids([PARTLY, WITHDRAWN])
    return pipeline, stats, requested


def test_404_writes_an_empty_receipt_and_the_publication_is_complete(tmp_path):
    pipeline, stats, _ = crawl(tmp_path)
    assert stats["errors"] == 0 and stats["unavailable"] == 3 and stats["success"] == 1
    receipt = json.loads((tmp_path / "raw" / "2508-03014" / "v2" / "source.json").read_text())
    assert receipt["status"] == "unavailable" and receipt["http_status"] == 404 and receipt["files"] == {}
    task = pipeline.manifest.get(PARTLY, 2, "source")
    assert (task.status, task.http_status) == ("unavailable", 404)
    for pid in (PARTLY, WITHDRAWN):
        state = pipeline.status(pid)
        assert state.complete, pid
    assert pipeline.status(PARTLY).unavailable_versions == 1
    assert pipeline.status(WITHDRAWN).unavailable_versions == 2
    _, tables = pipeline.export([PARTLY, WITHDRAWN])
    papers = pq.read_table(tables["papers"]).to_pylist()
    assert sorted(p["arxiv_id"] for p in papers) == [WITHDRAWN, PARTLY]
    assert all(p["revised_dates"] == ["2025-10-11"] for p in papers)
    # Files alone (ADR 0002) give the same answer.
    assert FileCorpus(tmp_path).publication(WITHDRAWN).sources_complete


def test_a_404_version_is_not_asked_again(tmp_path):
    pipeline, _, requested = crawl(tmp_path)
    before = len(requested)
    pipeline.crawl_ids([PARTLY, WITHDRAWN])
    assert len(requested) == before


def test_empty_receipt_with_stray_tex_is_rejected(tmp_path):
    crawl(tmp_path)
    version = tmp_path / "raw" / "2508-03014" / "v2"
    assert verified_source(version).status == "unavailable"
    (version / "main.tex").write_bytes(TEX)
    assert verified_source(version) is None


def test_reports_count_unavailable_versions_and_keep_the_publication(tmp_path):
    crawl(tmp_path)
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(json.dumps({"schema_version": 1, "member": "test",
                                     "range": {"prefix": "2508", "start": 2961, "end": 3014},
                                     "totals": {}}))
    observed = validate_crawl(tmp_path, benchmark)["observed"]
    assert observed["publications_complete"] == 2

    report = snapshot(tmp_path, [PARTLY, WITHDRAWN])
    assert report["counts"]["complete"] == 2 and report["counts"]["unavailable"] == 3

    ids = tmp_path / "ids.txt"
    ids.write_text(f"{PARTLY}\n{WITHDRAWN}\n")
    out = tmp_path / "stats"
    make_stats.main(["--data-dir", str(tmp_path), "--ids-file", str(ids), "--out", str(out)])
    rows = {r["id"]: r for r in csv.DictReader((out / "papers.csv").open())}
    assert rows[PARTLY]["status"] == rows[WITHDRAWN]["status"] == "done"
    assert rows[PARTLY]["versions_unavailable"] == "1" and rows[WITHDRAWN]["versions_unavailable"] == "2"


def test_parser_logs_an_unavailable_version_as_an_empty_record(tmp_path):
    crawl(tmp_path)
    result = assemble_source(tmp_path / "raw" / "2508-03014" / "v2", require_receipt=True)
    assert result.status == "empty_unavailable"
