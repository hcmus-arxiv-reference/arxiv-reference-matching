import io
import tarfile
from pathlib import Path

from src.crawl.discovery import parse_feed
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.source import extract_source


def test_parse_feed_keeps_versions_and_lists() -> None:
    feed = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry><id>http://arxiv.org/abs/2508.02872</id><title> A title\n</title>
      <author><name>Alice</name></author><author><name>Bob</name></author>
      <published>2025-08-01T00:00:00Z</published><arxiv:journal_ref>Journal</arxiv:journal_ref>
      <arxiv:version version="v1"><arxiv:date>2025-08-01T00:00:00Z</arxiv:date></arxiv:version>
      <arxiv:version version="v2"><arxiv:date>2025-08-03T00:00:00Z</arxiv:date></arxiv:version>
      </entry></feed>'''
    publication = parse_feed(feed)
    assert publication.arxiv_id == "2508.02872"
    assert publication.authors == ["Alice", "Bob"]
    assert publication.versions == 2
    assert publication.revised_dates == ["2025-08-03T00:00:00Z"]


def test_extract_source_only_keeps_tex_and_bib(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for name, content in {
            "main.tex": b"\\documentclass{article}",
            "refs.bib": b"@article{x}",
            "figure.png": b"not text",
            "../escape.tex": b"must not escape",
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    tex, bib = extract_source(payload.getvalue(), tmp_path / "v1")
    assert tex == ["main.tex"]
    assert bib == ["refs.bib"]
    assert not (tmp_path / "escape.tex").exists()


def test_http_client_retries_transient_status_and_paces() -> None:
    responses = [HttpResponse(503, {}, b""), HttpResponse(200, {}, b"ok")]
    sleeps: list[float] = []

    def transport(_request, _timeout):
        return responses.pop(0)

    client = HttpClient("test-agent", min_interval=0, sleeper=sleeps.append, transport=transport)
    response = client.get("https://example.invalid")
    assert response.status == 200
    assert sleeps == [1.0]
