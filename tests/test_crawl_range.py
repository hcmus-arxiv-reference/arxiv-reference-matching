"""Range orchestration: real local checkpoints/Parquet and fake remote services."""
from unittest.mock import Mock

from src.common.schema import read_table
from src.crawl.discovery import Publication
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader
from scripts.crawl_range import inspect_publication, run_range


def make_pipeline(tmp_path, transport=None):
    discovery = Mock()
    discovery.discover.side_effect = lambda identifier: Publication(
        identifier, "Title", [], "2025-08-04", [], None, 1)
    refs = Mock()
    refs.references.return_value = []
    client = HttpClient("offline", max_retries=0, sleeper=lambda _: None,
        transport=transport or (lambda *_: HttpResponse(200, {}, b"\\documentclass{article}")))
    return CrawlPipeline(discovery, ArxivSourceDownloader(client, tmp_path / "raw"), tmp_path, refs)


def test_range_retries_only_incomplete_and_exports_all(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.references.references.side_effect = [[], TimeoutError(), []]
    ids = ["2508.02872", "2508.02873"]
    result = run_range(pipeline, ids, retry_delay=0, min_free_bytes=0)
    assert result["status"] == "complete"
    assert result["pass"] == 2 and result["counts"]["complete"] == 2
    assert pipeline.discovery.discover.call_count == 2
    assert pipeline.references.references.call_count == 3
    assert read_table("papers", tmp_path / "tables/papers.parquet").num_rows == 2
    resumed = run_range(pipeline, ids, retry_delay=0, min_free_bytes=0)
    assert resumed["status"] == "complete" and resumed["visited_this_pass"] == 0
    assert pipeline.references.references.call_count == 3


def test_range_detects_corrupt_source_and_preserves_non_tex(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.crawl_ids(["2508.02872"])
    assert inspect_publication(pipeline, "2508.02872")["complete"]
    (tmp_path / "raw/2508-02872/v1/single.tex").write_text("corrupt")
    assert not inspect_publication(pipeline, "2508.02872")["complete"]
    pipeline.sources.client._transport = lambda *_: HttpResponse(200, {}, b"%PDF-1.7")
    result = run_range(pipeline, ["2508.02872"], min_free_bytes=0)
    assert result["status"] == "complete" and result["counts"]["non_tex_versions"] == 1


def test_range_exhausted_retries_never_reports_complete(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.discovery.discover.side_effect = TimeoutError()
    result = run_range(pipeline, ["2508.02872"], max_passes=2, retry_delay=0, min_free_bytes=0)
    assert result["status"] == "incomplete"
    assert result["pending_ids"] == ["2508.02872"]
    assert result["exported_publications"] == 0


def test_stop_request_preserves_cached_publications(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.crawl_ids(["2508.02872"])
    (tmp_path / "STOP_RANGE").touch()
    result = run_range(pipeline, ["2508.02872", "2508.02873"], min_free_bytes=0)
    assert result["status"] == "stopped" and result["exported_publications"] == 1
    assert pipeline.discovery.discover.call_count == 1
