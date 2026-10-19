"""Offline integration tests for discovery, sources, S2, checkpoints and CLI."""
import gzip
import io
import json
from pathlib import Path
import tarfile
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest

from src.crawl.discovery import ArxivDiscovery, Publication
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.manifest import Manifest, TaskRecord
from src.crawl.pipeline import CrawlPipeline
from src.crawl.semantic_scholar import SemanticScholarClient, reference_rows
from src.crawl.source import ArxivSourceDownloader, extract_source
from src.common.schema import read_table
from scripts.crawl import main


def response(body, status=200):
    return HttpResponse(status, {}, body)


def transport_client(transport):
    return HttpClient("offline", transport=transport, sleeper=lambda _: None, max_retries=0)


def feed(version=3, identifier="2508.02872"):
    return f'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <id>http://arxiv.org/abs/{identifier}v{version}</id><title>Title</title>
    <published>2025-08-04T00:00:00Z</published><updated>2025-08-{4+version:02d}T00:00:00Z</updated>
    </entry></feed>'''.encode()


def test_discovery_fills_revision_dates_and_uses_expected_versions():
    requested = []
    def transport(request, _):
        identifier = parse_qs(urlsplit(request.full_url).query)["id_list"][0]
        requested.append(identifier)
        return response(feed(2 if identifier.endswith("v2") else 3))
    pub = ArxivDiscovery(transport_client(transport)).discover("2508.02872")
    assert pub.versions == 3
    assert pub.revised_dates == ["2025-08-06T00:00:00Z", "2025-08-07T00:00:00Z"]
    assert requested == ["2508.02872", "2508.02872v2"]


def test_discovery_rejects_response_for_other_publication():
    discovery = ArxivDiscovery(transport_client(lambda *_: response(feed(identifier="2508.02873"))))
    with pytest.raises(ValueError, match="different publication"):
        discovery.discover("2508.02872")


def test_arxiv_pacing_even_with_zero_configuration():
    now, starts = [0.0], []
    def transport(*_):
        starts.append(now[0])
        return response(b"ok")
    client = HttpClient("offline", transport=transport, min_interval=0,
                        sleeper=lambda dt: now.__setitem__(0, now[0]+dt), clock=lambda: now[0])
    client.get("https://export.arxiv.org/api/query")
    client.get("https://export.arxiv.org/src/2508.02872v1")
    assert starts == [0, 3]
    with pytest.raises(ValueError):
        client.get("https://arxiv.org/src/2508.02872v1")


def test_lowercase_retry_after_is_honored():
    assert HttpClient._retry_after({"retry-after": "7"}, 1) == 7


@pytest.mark.parametrize("identifier", ["../paper", "2508.02872v2", "https://example.org", "a?x=1"])
def test_invalid_ids_never_reach_transport(tmp_path, identifier):
    transport = Mock()
    downloader = ArxivSourceDownloader(transport_client(transport), tmp_path)
    with pytest.raises(ValueError):
        downloader.download(identifier, 1)
    transport.assert_not_called()


def test_gzip_single_tex_preserves_bytes(tmp_path):
    content = b"% latin-1 \xe9\n\\documentclass{article}\n"
    assert extract_source(gzip.compress(content), tmp_path) == (["single.tex"], [])
    assert (tmp_path / "single.tex").read_bytes() == content


def test_archive_skips_links_and_preserves_nested_paths(tmp_path):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        info = tarfile.TarInfo("nested/body.tex"); info.size = 3
        archive.addfile(info, io.BytesIO(b"tex"))
        link = tarfile.TarInfo("evil.tex"); link.type = tarfile.SYMTYPE; link.linkname = "/etc/passwd"
        archive.addfile(link)
    assert extract_source(data.getvalue(), tmp_path) == (["nested/body.tex"], [])
    assert not (tmp_path / "evil.tex").exists()


def test_expansion_limit_and_unknown_content(tmp_path, monkeypatch):
    monkeypatch.setattr("src.crawl.source.MAX_EXTRACT_BYTES", 16)
    with pytest.raises(ValueError, match="limit"):
        extract_source(gzip.compress(b"x"*100), tmp_path)
    with pytest.raises(ValueError, match="Unsupported"):
        extract_source(b"gateway error", tmp_path)


def test_source_missing_file_is_redownloaded(tmp_path):
    transport = Mock(return_value=response(b"\\documentclass{article}"))
    downloader = ArxivSourceDownloader(transport_client(transport), tmp_path / "raw")
    first = downloader.download("2508.02872", 1)
    assert downloader.download("2508.02872", 1).cached
    (first.path / "single.tex").unlink()
    assert not downloader.download("2508.02872", 1).cached
    assert transport.call_count == 2


def test_pdf_has_persistent_empty_receipt(tmp_path):
    transport = Mock(return_value=response(b"%PDF-1.7\n"))
    downloader = ArxivSourceDownloader(transport_client(transport), tmp_path / "raw")
    result = downloader.download("2508.02872", 1)
    assert result.status == "non_tex" and result.path.joinpath("source.json").exists()
    assert downloader.download("2508.02872", 1).status == "non_tex"
    transport.assert_called_once()


def test_manifest_preserves_complete_final_line_without_newline(tmp_path):
    path = tmp_path / "m.jsonl"
    path.write_text(json.dumps({"arxiv_id": "2508.02872", "version": 1}))
    manifest = Manifest(path)
    manifest.upsert(TaskRecord("2508.02873", 1))
    assert len(Manifest(path).records) == 2


def test_manifest_rejects_corruption_in_middle(tmp_path):
    path = tmp_path / "m.jsonl"
    path.write_text('bad\n{"arxiv_id":"2508.02872"}\n')
    with pytest.raises(ValueError, match="Corrupt"):
        Manifest(path)


def test_s2_follows_next_even_after_short_page_and_keeps_non_arxiv():
    urls = []
    def transport(request, _):
        urls.append(request.full_url)
        body = {"data": [{"citedPaper": None}], "next": 17} if len(urls) == 1 else {"data": []}
        return response(json.dumps(body).encode())
    assert SemanticScholarClient(transport_client(transport)).references("hep-th/9901001") == [{"citedPaper": None}]
    assert "offset=17" in urls[1] and "hep-th%2F9901001" in urls[0]


def test_s2_rejects_nonadvancing_page():
    client = transport_client(lambda *_: response(b'{"data":[],"next":0}'))
    with pytest.raises(ValueError, match="Non-advancing"):
        SemanticScholarClient(client).references("2508.02872")


def test_s2_mapping_keeps_submission_unknown_and_deduplicates():
    raw = [{"citedPaper": {"externalIds": {"ArXiv": "hep-th/9901001v2"},
            "authors": [{"name": "Alice"}], "publicationDate": "1999-01-01", "title": "Title"}}]
    rows = reference_rows("2508.02872", raw + raw + [{"citedPaper": None}])
    assert len(rows) == 1 and rows[0]["ref_arxiv_id"] == "hep-th/9901001"
    assert rows[0]["ref_submission_date"] is None and rows[0]["ref_authors"] == ["Alice"]


def test_pipeline_continues_versions_then_resumes_and_exports(tmp_path):
    discovery = Mock()
    discovery.discover.return_value = Publication("2508.02872", "Title", [], "2025-08-04", ["2025-08-05"], None, 2)
    failing = [True]
    def transport(request, _):
        if request.full_url.endswith("v1") and failing[0]:
            raise TimeoutError("synthetic")
        return response(b"\\documentclass{article}")
    sources = ArxivSourceDownloader(transport_client(transport), tmp_path / "raw")
    references = Mock(); references.references.return_value = []
    pipeline = CrawlPipeline(discovery, sources, tmp_path, references)
    assert pipeline.crawl_ids(["2508.02872"])["errors"] == 1
    assert pipeline.manifest.get("2508.02872", 2).status == "success"
    assert pipeline.export(["2508.02872"])[0] == []
    failing[0] = False
    assert pipeline.crawl_ids(["2508.02872"])["skipped"] == 1
    bundles, tables = pipeline.export(["2508.02872"])
    assert len(bundles) == 1 and read_table("papers", tables["papers"]).num_rows == 1
    assert read_table("references", tables["references"]).num_rows == 0
    assert pipeline.manifest.get("2508.02872", 1).attempts == 2
    discovery.discover.assert_called_once()
    references.references.assert_called_once()


def test_cli_rejects_bad_range_without_network():
    assert main(["--start", "0"]) == 2
    assert main(["--min-interval", "0"]) == 2


def test_http_detects_truncated_response_before_extraction(monkeypatch):
    from http.client import IncompleteRead
    from unittest.mock import MagicMock
    stream = MagicMock()
    stream.status = 200
    stream.headers = {"Content-Length": "10"}
    stream.read.side_effect = [b"12345", b""]
    stream.__enter__.return_value = stream
    opener = Mock(); opener.open.return_value = stream
    monkeypatch.setattr("src.crawl.http_client.build_opener", lambda *_: opener)
    with pytest.raises(IncompleteRead):
        HttpClient("test")._urlopen(Mock(), 1)


def test_http_retries_incomplete_download():
    from http.client import IncompleteRead
    responses = iter([IncompleteRead(b"", 5), response(b"complete")])
    def transport(*_):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result
    client = HttpClient("test", transport=transport, sleeper=lambda _: None)
    assert client.get("https://example.invalid/source").body == b"complete"


def test_html_content_type_is_not_accepted_as_tex(tmp_path):
    client = transport_client(lambda *_: HttpResponse(200, {"content-type": "text/html"}, b"\\documentclass{article}"))
    with pytest.raises(ValueError, match="error document"):
        ArxivSourceDownloader(client, tmp_path / "raw").download("2508.02872", 1)


def test_discovery_cache_corruption_triggers_refresh(tmp_path):
    discovery = Mock()
    discovery.discover.return_value = Publication("2508.02872", "Title", [], "2025-08-04", [], None, 1)
    pipeline = CrawlPipeline(discovery, ArxivSourceDownloader(
        transport_client(lambda *_: response(b"\\documentclass{article}")), tmp_path / "raw"), tmp_path)
    pipeline.crawl_ids(["2508.02872"])
    metadata = tmp_path / "metadata/2508-02872.json"
    metadata.write_text(metadata.read_text().replace('"Title"', '"Other title"'))
    pipeline.crawl_ids(["2508.02872"])
    assert discovery.discover.call_count == 2
    assert '"Title"' in metadata.read_text()
