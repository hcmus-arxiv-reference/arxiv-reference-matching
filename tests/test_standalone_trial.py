"""The trial selects only verified missing tasks and cannot report cached success."""
import json
from unittest.mock import Mock

from scripts.trial_standalone import build_plan
from src.crawl.discovery import Publication
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader


def test_plan_rechecks_files_and_references_without_network(tmp_path):
    discovery, refs = Mock(), Mock()
    discovery.discover.return_value = Publication("2508.02961", "Test", [], "2025-08-04", [], None, 1)
    refs.references.side_effect = TimeoutError()
    http = HttpClient("offline", transport=lambda *_: HttpResponse(200, {}, b"\\documentclass{article}"))
    pipeline = CrawlPipeline(discovery, ArxivSourceDownloader(http, tmp_path / "raw"), tmp_path, refs)
    pipeline.crawl_ids(["2508.02961"])
    (tmp_path / "manifests/range-run.json").write_text(json.dumps({"pending_ids": ["2508.02961"]}))
    plan, _ = build_plan(tmp_path)
    assert plan[0]["source_versions"] == []
    assert plan[0]["references_missing"]
    (tmp_path / "raw/2508-02961/v1/single.tex").write_text("corrupt")
    plan, _ = build_plan(tmp_path)
    assert plan[0]["source_versions"] == [1]
    assert discovery.discover.call_count == refs.references.call_count == 1
