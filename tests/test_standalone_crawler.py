"""Standalone checkpoints must describe verified data, not successful loops."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import json

import pytest
import requests
import urllib3

from src import lieu_standalone_crawler as crawler


@pytest.fixture
def standalone(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler, "DATA_DIR", tmp_path)
    monkeypatch.setattr(crawler, "LOG_FILE", tmp_path / "logs/run.jsonl")
    return tmp_path


def test_404_source_remains_retryable(standalone, monkeypatch):
    calls = []
    def fetch(*args, **kwargs):
        calls.append(1)
        return None
    monkeypatch.setattr(crawler, "fetch_bytes", fetch)
    paper = standalone / "2508-02961"
    first = crawler.download_version("2508.02961", 1, paper)
    crawler.download_version("2508.02961", 1, paper)
    assert first["status"] == "unavailable"
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [b"<html>Error</html>", gzip.compress(b"<html>Error</html>"),
                                     gzip.compress(b"\\documentclass{article}")[:-4]])
def test_invalid_response_never_becomes_empty_version(standalone, monkeypatch, payload):
    monkeypatch.setattr(crawler, "fetch_bytes", lambda *a, **k: payload)
    with pytest.raises((ValueError, OSError, EOFError)):
        crawler.download_version("2508.02961", 1, standalone / "2508-02961")
    assert not (standalone / "2508-02961/v1/status.json").exists()


def test_changed_source_invalidates_checkpoint(standalone, monkeypatch):
    calls = []
    def fetch(*a, **k):
        calls.append(1)
        return gzip.compress(b"\\documentclass{article}\n\\begin{document}Text")
    monkeypatch.setattr(crawler, "fetch_bytes", fetch)
    paper = standalone / "2508-02961"
    status = crawler.download_version("2508.02961", 1, paper)
    crawler.download_version("2508.02961", 1, paper)
    assert len(calls) == 1
    (paper / "v1" / status["files"][0]).write_text("changed")
    crawler.download_version("2508.02961", 1, paper)
    assert len(calls) == 2


def test_missing_refs_cannot_create_done_and_later_versions_still_run(standalone, monkeypatch):
    versions = []
    def download(pid, version, directory):
        versions.append(version)
        if version == 1:
            raise OSError("interrupted")
        return {"version": version, "status": "unavailable", "files": [],
                "bytes_downloaded": 0, "bytes_before": 0, "bytes_after": 0}
    monkeypatch.setattr(crawler, "download_version", download)
    monkeypatch.setattr(crawler, "fetch_and_save_refs", lambda *a: (None, None))
    meta = {"2508.02961": {"arxiv_id": "2508.02961", "n_versions": 2}}
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = crawler.process_paper("2508.02961", pool, meta)
    assert result == "incomplete"
    assert versions == [1, 2]
    assert not (standalone / "2508-02961/done.json").exists()


def test_old_false_done_does_not_skip_missing_sources(standalone, monkeypatch):
    paper = standalone / "2508-02961"
    crawler.write_json(paper / "done.json", {"status": "done"})
    crawler.write_json(paper / "meta.json", {"arxiv_id": "2508.02961", "n_versions": 1})
    monkeypatch.setattr(crawler, "fetch_bytes", lambda *a, **k: None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = crawler.process_paper("2508.02961", pool)
    assert result == "incomplete"
    assert not (paper / "done.json").exists()


def test_s2_pagination_and_checksum_resume(standalone, monkeypatch):
    calls = []
    def fetch(url, *a, **k):
        calls.append(url)
        row = {"citedPaper": {"paperId": str(len(calls)), "externalIds": {"ArXiv": "2508.03000"},
                              "authors": [{"name": "A"}], "title": "Test", "publicationDate": "2025-08-01"}}
        return json.dumps({"data": [row], **({"next": 1} if len(calls) == 1 else {})}).encode()
    monkeypatch.setattr(crawler, "fetch_bytes", fetch)
    paper = standalone / "2508-02961"
    assert crawler.fetch_and_save_refs("2508.02961", paper) == (2, 2)
    assert "offset=1" in calls[-1]
    assert crawler.fetch_and_save_refs("2508.02961", paper) == (2, 2)
    assert len(calls) == 2
    (paper / "references.json").write_text("[]")
    crawler.fetch_and_save_refs("2508.02961", paper)
    assert len(calls) == 3


class Response:
    """A streamed response capable of failing after some bytes were received."""
    def __init__(self, code, headers, chunks):
        self.status_code, self.headers, self.chunks = code, headers, chunks
        self.raw, self.closed = self, False

    def stream(self, *args, **kwargs):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


@pytest.mark.parametrize("resume_code", [200, 206])
def test_range_recovers_interruption_or_restarts_if_ignored(monkeypatch, resume_code):
    first = Response(200, {"Content-Length": "6", "Accept-Ranges": "bytes", "ETag": '"one"'},
                     [b"abc", urllib3.exceptions.ProtocolError("interrupted")])
    second = (Response(206, {"Content-Range": "bytes 3-5/6", "ETag": '"one"'}, [b"def"])
              if resume_code == 206 else Response(200, {"Content-Length": "6"}, [b"abcdef"]))
    responses, headers = iter([first, second]), []
    class Session:
        def get(self, url, **kwargs):
            headers.append(kwargs["headers"])
            return next(responses)
    monkeypatch.setattr(crawler, "_session_for", lambda t: Session())
    monkeypatch.setattr(crawler, "_drop_session", lambda t: None)
    monkeypatch.setattr(crawler.time, "sleep", lambda t: None)
    assert crawler.fetch_bytes("https://export.arxiv.org/src/2508.02961v1", crawler.Throttle(0)) == b"abcdef"
    assert headers[1] == {"Range": "bytes=3-", "If-Range": '"one"'}
    assert first.closed and second.closed


def test_unsolicited_partial_response_is_not_accepted(monkeypatch):
    response = Response(206, {"Content-Length": "3", "Content-Range": "bytes 3-5/6"}, [b"def"])
    class Session:
        def get(self, *a, **k):
            return response
    monkeypatch.setattr(crawler, "_session_for", lambda t: Session())
    monkeypatch.setattr(crawler, "_drop_session", lambda t: None)
    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        crawler.fetch_bytes("https://export.arxiv.org/src/2508.02961v1", crawler.Throttle(0), retries=0)
    assert response.closed


def test_404_response_is_closed(monkeypatch):
    response = Response(404, {}, [])
    class Session:
        def get(self, *a, **k):
            return response
    monkeypatch.setattr(crawler, "_session_for", lambda t: Session())
    assert crawler.fetch_bytes("https://export.arxiv.org/src/2508.02961v1", crawler.Throttle(0)) is None
    assert response.closed


def test_complete_publication_resumes_without_network_and_keeps_non_tex(standalone, monkeypatch):
    calls = []
    def fetch(url, *a, **k):
        calls.append(url)
        return b'%PDF-1.7' if '/src/' in url else b'{"data": []}'
    monkeypatch.setattr(crawler, "fetch_bytes", fetch)
    meta = {"2508.02961": {"arxiv_id": "2508.02961", "n_versions": 1}}
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert crawler.process_paper("2508.02961", pool, meta) == "done"
        assert crawler.process_paper("2508.02961", pool, meta) == "skipped"
    assert len(calls) == 2
    assert crawler.verified_status(standalone / "2508-02961/v1")["status"] == "empty"


def test_rejects_integrated_cache_before_network(standalone):
    (standalone / "manifests").mkdir()
    (standalone / "manifests/crawl.jsonl").touch()
    with pytest.raises(SystemExit) as error:
        crawler.main(["--data-dir", str(standalone), "--id", "2508.02961"])
    assert error.value.code == 2


def test_arxiv_library_cannot_override_contact_or_follow_redirects(monkeypatch):
    captured = {}
    def get(self, url, **kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr(requests.Session, "get", get)
    session = crawler.ArxivSession()
    session.get("https://export.arxiv.org/api/query", headers={"user-agent": "arxiv.py"})
    assert captured["headers"]["User-Agent"] == crawler.USER_AGENT
    assert captured["allow_redirects"] is False
    with pytest.raises(ValueError):
        session.get("https://arxiv.org/src/2508.02961v1")
