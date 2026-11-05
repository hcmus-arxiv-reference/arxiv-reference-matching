"""Crawl-time Publication state: receipts must agree with the Manifest (data contract 3.2)."""
from dataclasses import replace
from unittest.mock import Mock

from src.crawl.discovery import Publication
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.pipeline import CrawlPipeline
from src.crawl.runner import inspect_publication
from src.crawl.source import ArxivSourceDownloader

PID = "2508.02872"


def crawled(tmp_path, *, references=True):
    discovery = Mock()
    discovery.discover.side_effect = lambda identifier: Publication(
        identifier, "Title", [], "2025-08-04", [], None, 1)
    refs = None
    if references:
        refs = Mock()
        refs.references.return_value = []
    client = HttpClient("offline", max_retries=0, sleeper=lambda _: None,
                        transport=lambda *_: HttpResponse(200, {}, b"\\documentclass{article}"))
    pipeline = CrawlPipeline(discovery, ArxivSourceDownloader(client, tmp_path / "raw"), tmp_path, refs)
    pipeline.crawl_ids([PID])
    return pipeline


def tamper_source_record(pipeline, **fields):
    record = pipeline.manifest.get(PID, 1, "source")
    pipeline.manifest.upsert(replace(record, **fields))


def test_status_carries_manifest_record(tmp_path):
    pipeline = crawled(tmp_path)
    state = pipeline.corpus.status(PID)
    assert state.complete
    (version,) = state.versions
    assert version.verified and version.task.status == "success"
    assert version.task.checksum == version.source.checksum


def test_receipt_and_manifest_status_must_agree(tmp_path):
    pipeline = crawled(tmp_path)
    tamper_source_record(pipeline, status="non_tex")  # same checksum, other status
    state = pipeline.corpus.status(PID)
    assert state.versions[0].source is not None and not state.versions[0].verified
    assert not state.complete
    bundles, _ = pipeline.export([PID])
    assert bundles == []  # Export is as strict as the Runner


def test_manifest_checksum_mismatch_is_not_verified(tmp_path):
    pipeline = crawled(tmp_path)
    tamper_source_record(pipeline, checksum="0" * 64)
    assert not pipeline.corpus.status(PID).sources_complete
    assert inspect_publication(pipeline, PID)["verified_versions"] == 0


def test_sources_only_export_without_references(tmp_path):
    pipeline = crawled(tmp_path, references=False)
    state = pipeline.corpus.status(PID)
    assert state.sources_complete and not state.complete
    assert pipeline.export([PID])[0] == []
    bundles, tables = pipeline.export([PID], require_references=False)
    assert [b["publication"].arxiv_id for b in bundles] == [PID] and "references" not in tables


def test_inspect_publication_keeps_range_run_counts(tmp_path):
    pipeline = crawled(tmp_path)
    assert inspect_publication(pipeline, PID) == {
        "metadata": True, "expected_versions": 1, "verified_versions": 1,
        "non_tex_versions": 0, "references": True, "complete": True}
    (tmp_path / "metadata" / "2508-02872.json").unlink()
    # Without metadata, references are not counted even though their cache is valid.
    assert inspect_publication(pipeline, PID) == {
        "metadata": False, "expected_versions": 0, "verified_versions": 0,
        "non_tex_versions": 0, "references": False, "complete": False}
