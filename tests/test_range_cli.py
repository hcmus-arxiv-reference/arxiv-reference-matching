"""End-to-end Range CLI contract using synthetic HTTP and real Parquet/files."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import crawl_range
from src.common.config import get_settings
from src.common.schema import read_table
from src.crawl.batched import BatchedDiscovery
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.semantic_scholar import SemanticScholarClient
from src.crawl.source import ArxivSourceDownloader
from src.crawl.source import _safe_member


@pytest.mark.parametrize("name", ["C:/escape.tex", "C:escape.tex", "main.tex:stream", "../escape.tex"])
def test_archive_paths_reject_windows_drives_and_streams(name):
    assert not _safe_member(name)


def feed(identifier, version, updated="2024-12-20"):
    return (f'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            f'<id>http://arxiv.org/abs/{identifier}v{version}</id>'
            '<title>Example</title><author><name>Alice</name></author>'
            f'<published>2024-12-10</published><updated>{updated}</updated>'
            '</entry></feed>').encode()


def test_real_files_pagination_resume_and_corrupt_cache(tmp_path):
    calls = []
    def transport(request, timeout):
        url = request.full_url
        calls.append(url)
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        if parts.path == "/api/query":
            return HttpResponse(200, {}, feed("2412.08848", 2))
        if parts.path == "/src/2412.08848v1":
            return HttpResponse(200, {}, b"\\documentclass{article}\nHello.")
        if parts.path == "/src/2412.08848v2":
            return HttpResponse(200, {}, b"%PDF-1.7 synthetic")
        assert parts.path.endswith("/references")
        if query["offset"] == ["0"]:
            data = {"data": [{"citedPaper": {"paperId": "s2-example", "title": "Reference",
                "externalIds": {"ArXiv": "2301.00001v2"}, "authors": [{"name": "Bob"}],
                "publicationDate": "2023-01-01"}}], "next": 100}
        else:
            data = {"data": [{"citedPaper": {"paperId": "no-arxiv", "externalIds": {}}}]}
        return HttpResponse(200, {}, json.dumps(data).encode())
    client = HttpClient("offline", transport=transport, sleeper=lambda _: None)
    pipeline = crawl_range.RangePipeline(BatchedDiscovery(client),
        ArxivSourceDownloader(client, tmp_path / "raw"), tmp_path, SemanticScholarClient(client))
    report = crawl_range.run_range(pipeline, ["2412.08848"], min_free_bytes=0, export_every=1)
    assert report["status"] == "complete"
    assert report["counts"]["verified_versions"] == 2
    assert report["counts"]["non_tex_versions"] == 1
    papers = read_table("papers", tmp_path / "tables/papers.parquet")
    assert papers.to_pylist() == [{"arxiv_id": "2412.08848", "title": "Example",
        "authors": ["Alice"], "submission_date": "2024-12-10",
        "revised_dates": ["2024-12-20"], "venue": None}]
    refs = read_table("references", tmp_path / "tables/references.parquet")
    assert refs.to_pylist() == [{"arxiv_id": "2412.08848", "ref_arxiv_id": "2301.00001",
        "ref_title": "Reference", "ref_authors": ["Bob"], "ref_submission_date": None,
        "ref_s2_id": "s2-example"}]
    for name in ["raw/2412-08848/v1/source.json", "raw/2412-08848/v2/source.json",
                 "metadata/2412-08848.json", "references/2412-08848.json", "manifests/crawl.jsonl"]:
        assert (tmp_path / name).exists()
    calls.clear()
    resumed = crawl_range.run_range(pipeline, ["2412.08848"], min_free_bytes=0)
    assert resumed["visited_this_pass"] == 0
    assert calls == []
    assert read_table("papers", tmp_path / "tables/papers.parquet").equals(papers)
    assert read_table("references", tmp_path / "tables/references.parquet").equals(refs)
    (tmp_path / "raw/2412-08848/v1/single.tex").write_text("corrupt", encoding="utf-8")
    crawl_range.run_range(pipeline, ["2412.08848"], min_free_bytes=0)
    assert len(calls) == 1 and calls[0].endswith("/src/2412.08848v1")
    with pytest.raises(ValueError, match="another Range"):
        crawl_range.run_range(pipeline, ["2412.08849"], min_free_bytes=0)
    assert read_table("papers", tmp_path / "tables/papers.parquet").equals(papers)


def test_cli_range_overrides_env_and_returns_nonzero_when_incomplete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(crawl_range, "get_settings", lambda: get_settings({"CONTACT_EMAIL": "test@example.invalid"}))
    captured = {}
    def run(pipeline, identifiers, **kwargs):
        captured["ids"] = list(identifiers)
        captured["root"] = pipeline.data_dir
        return {"status": "incomplete"}
    monkeypatch.setattr(crawl_range, "run_range", run)
    monkeypatch.setattr(crawl_range.signal, "signal", lambda *args: None)
    assert crawl_range.main(["--start", "2412.08848", "--end", "2412.13847"]) == 1
    assert len(captured["ids"]) == 5000
    assert captured["ids"][0] == "2412.08848" and captured["ids"][-1] == "2412.13847"
    assert captured["root"].name == "crawl-2412-08848-13847"


@pytest.mark.parametrize("first,last", [("2412.08848v1", "2412.13847"),
    ("2412.08848", "2501.00001"), ("2412.13847", "2412.08848")])
def test_invalid_ranges_are_rejected(first, last):
    with pytest.raises(ValueError):
        crawl_range.parse_range(first, last)


def test_batch_requests_all_results_and_falls_back_when_missing():
    calls = []
    def transport(request, timeout):
        query = parse_qs(urlsplit(request.full_url).query)
        calls.append(query)
        identifier = query["id_list"][0]
        if "," in identifier:
            assert query["max_results"] == ["2"]
            return HttpResponse(200, {}, feed("2412.08848", 1))
        assert identifier == "2412.08849"
        return HttpResponse(200, {}, feed(identifier, 1))
    discovery = BatchedDiscovery(HttpClient("test", transport=transport, sleeper=lambda _: None))
    discovery.prefetch(["2412.08848", "2412.08849"])
    assert discovery.discover("2412.08848").versions == 1
    assert discovery.discover("2412.08849").versions == 1
    assert len(calls) == 2
