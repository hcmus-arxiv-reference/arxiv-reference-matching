"""Reproduce open crawler defects without network calls.

Strict xfail records an unmet requirement, not a successful correctness check.
When a defect is fixed, remove its marker and keep the regression test.
"""

import io
import tarfile
from pathlib import Path

import pytest

from src.crawl.discovery import Publication, parse_feed
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.manifest import Manifest, TaskRecord
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader, extract_source


def atom(identifier: str) -> bytes:
    """Standard Atom shape: the latest version is part of the identifier."""
    return f'''<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>
        <id>http://arxiv.org/abs/{identifier}</id>
        <published>2025-08-04T00:00:00Z</published>
        <arxiv:journal_ref>Example Journal</arxiv:journal_ref>
        </entry></feed>'''.encode()


def client(response: HttpResponse) -> HttpClient:
    """No network, retries or real sleeps in these probes."""
    return HttpClient("offline-review", min_interval=0, max_retries=0,
                      transport=lambda *_: response)


@pytest.mark.xfail(strict=True, reason="Discovery ignores latest-version suffix")
def test_latest_version_suffix_counts_all_versions() -> None:
    assert parse_feed(atom("2508.02872v4")).versions == 4


@pytest.mark.xfail(strict=True, reason="Discovery drops legacy archive prefix")
def test_legacy_arxiv_identifier_is_preserved() -> None:
    assert parse_feed(atom("hep-th/9901001v4")).arxiv_id == "hep-th/9901001"


@pytest.mark.xfail(strict=True, reason="journal_ref is in the arXiv namespace")
def test_journal_reference_populates_venue() -> None:
    assert parse_feed(atom("2508.02872v1")).venue == "Example Journal"


@pytest.mark.xfail(strict=True, reason="Non-tar payload is blindly named single.tex")
@pytest.mark.parametrize("payload", [b"%PDF-1.7\n", b"<html>Service unavailable</html>"])
def test_non_tex_payload_never_becomes_tex(tmp_path: Path, payload: bytes) -> None:
    try:
        tex, _ = extract_source(payload, tmp_path)
    except ValueError:
        # Rejecting an error page is also valid; recording it as TeX is not.
        return
    assert tex == []
    assert not list(tmp_path.rglob("*.tex"))


@pytest.mark.xfail(strict=True, reason="source.ok loses non_tex state on resume")
def test_empty_source_stays_empty_on_resume(tmp_path: Path) -> None:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz"):
        pass
    downloader = ArxivSourceDownloader(
        client(HttpResponse(200, {}, archive.getvalue())), tmp_path / "raw")
    assert downloader.download("2508.02872", 1).status == "non_tex"
    assert downloader.download("2508.02872", 1).status == "non_tex"


@pytest.mark.xfail(strict=True, reason="Append joins new record to truncated JSON tail")
def test_manifest_recovers_after_truncated_tail(tmp_path: Path) -> None:
    path = tmp_path / "crawl.jsonl"
    path.write_text('{"arxiv_id":', encoding="utf-8")
    manifest = Manifest(path)
    record = TaskRecord("2508.02872", 1, status="success")
    manifest.upsert(record)
    assert Manifest(path).get("2508.02872", 1) == record


@pytest.mark.xfail(strict=True, reason="Exhausted HTTP 503 becomes unavailable")
def test_transient_error_is_not_missing_source(tmp_path: Path) -> None:
    downloader = ArxivSourceDownloader(
        client(HttpResponse(503, {}, b"Service unavailable")), tmp_path / "raw")
    try:
        result = downloader.download("2508.02872", 1)
    except RuntimeError:
        return
    assert result.status not in {"success", "non_tex", "unavailable"}


@pytest.mark.xfail(strict=True, reason="Source exception is recorded as discovery error")
def test_pipeline_records_failure_for_the_version(tmp_path: Path) -> None:
    class Discovery:
        def discover(self, arxiv_id):
            return Publication(arxiv_id, "Title", [], None, [], None, 1)

    class Sources:
        def download(self, arxiv_id, version):
            raise TimeoutError("synthetic timeout")

    pipeline = CrawlPipeline(Discovery(), Sources(), tmp_path)
    pipeline.crawl_ids(["2508.02872"])
    assert pipeline.manifest.get("2508.02872", None, "discovery").status == "success"
    failed = pipeline.manifest.get("2508.02872", 1)
    assert failed is not None and failed.error_reason
