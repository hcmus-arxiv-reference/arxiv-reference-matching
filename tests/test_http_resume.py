"""Resumable downloads, time budget and wait table (Q12); offline fake transports only."""
import json

import pytest

from src.crawl.http_client import HttpClient, HttpResponse, HttpStatusError, PartialBody
from src.crawl.manifest import Manifest
from src.crawl.source import ArxivSourceDownloader

URL = "https://export.arxiv.org/src/2508.02872v1"
PAYLOAD = b"\\documentclass{article}\\begin{document}resumed body\\end{document}"


class FakeServer:
    """Replays scripted answers and records request headers and start times."""
    def __init__(self, *answers, clock=None):
        self.answers, self.requests, self.starts, self.clock = list(answers), [], [], clock

    def __call__(self, request, _timeout):
        self.requests.append({k.lower(): v for k, v in request.header_items()})
        if self.clock:
            self.starts.append(self.clock[0])
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def cut(body, *, etag='"strong"', ranges=True):
    """A 200 answer that delivers only `body` of the full PAYLOAD."""
    headers = {"Content-Length": str(len(PAYLOAD))}
    if ranges:
        headers["Accept-Ranges"] = "bytes"
    if etag:
        headers["ETag"] = etag
    return PartialBody(200, headers, body, len(PAYLOAD) - len(body))


def rest(offset, total=len(PAYLOAD)):
    return HttpResponse(206, {"Content-Range": f"bytes {offset}-{total - 1}/{total}"}, PAYLOAD[offset:])


def client(server, events=None, now=None, **options):
    now = now if now is not None else [0.0]
    sleeps = []

    def sleeper(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    http = HttpClient("offline", transport=server, sleeper=sleeper, clock=lambda: now[0],
                      jitter=lambda low, high: 1.0, **options)
    return http, sleeps


def test_truncated_body_resumes_with_range_and_strong_if_range():
    server, events = FakeServer(cut(PAYLOAD[:10]), rest(10)), []
    http, _ = client(server)
    response = http.get(URL, resume=True, on_event=events.append)
    assert response.status == 200 and response.body == PAYLOAD
    assert "range" not in server.requests[0]
    assert server.requests[1]["range"] == "bytes=10-"
    assert server.requests[1]["if-range"] == '"strong"'
    assert {"event": "resume", "offset": 10, "total": len(PAYLOAD)} in events


def test_weak_etag_is_never_sent_as_if_range():
    server = FakeServer(cut(PAYLOAD[:10], etag='W/"weak"'), rest(10))
    http, _ = client(server)
    assert http.get(URL, resume=True).body == PAYLOAD
    assert server.requests[1]["range"] == "bytes=10-"
    assert "if-range" not in server.requests[1]


def test_server_ignoring_range_restarts_from_zero():
    server, events = FakeServer(cut(PAYLOAD[:10]), HttpResponse(200, {}, PAYLOAD)), []
    http, _ = client(server)
    assert http.get(URL, resume=True, on_event=events.append).body == PAYLOAD
    assert {"event": "restart", "reason": "server_ignored_range"} in events


def test_mismatched_content_range_drops_kept_bytes():
    wrong = HttpResponse(206, {"Content-Range": f"bytes 5-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"}, PAYLOAD[5:])
    server = FakeServer(cut(PAYLOAD[:10]), wrong, HttpResponse(200, {}, PAYLOAD))
    http, _ = client(server)
    assert http.get(URL, resume=True).body == PAYLOAD
    assert "range" not in server.requests[2]


def test_no_resume_without_accept_ranges():
    server = FakeServer(cut(PAYLOAD[:10], ranges=False), HttpResponse(200, {}, PAYLOAD))
    http, _ = client(server)
    assert http.get(URL, resume=True).body == PAYLOAD
    assert "range" not in server.requests[1]


def test_progressing_attempts_do_not_exhaust_retries():
    chunks = [cut(PAYLOAD[:5])] + [PartialBody(206, {"Content-Range": f"bytes {i}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"},
                                               PAYLOAD[i:i + 5]) for i in range(5, 30, 5)]
    server = FakeServer(*chunks, rest(30))
    http, _ = client(server, max_retries=1)
    assert http.get(URL, resume=True).body == PAYLOAD


def test_total_time_budget_stops_slow_download():
    now = [0.0]
    stalled = [cut(PAYLOAD[:10])] + [PartialBody(206, {"Content-Range": f"bytes 10-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"},
                                                 b"") for _ in range(10)]
    server, events = FakeServer(*stalled), []

    def slow(request, timeout):
        now[0] += 400  # every attempt takes 400 s; the budget for a small file is 600 s
        return server(request, timeout)

    http, _ = client(slow, now=now, max_retries=10)
    with pytest.raises(TimeoutError, match="budget"):
        http.get(URL, resume=True, on_event=events.append)
    assert events[-1]["event"] == "gave_up" and events[-1]["reason"] == "time_budget"


def test_retry_after_up_to_900_seconds_is_honored_exactly():
    server = FakeServer(HttpResponse(503, {"Retry-After": "900"}, b""), HttpResponse(200, {}, PAYLOAD))
    http, sleeps = client(server)
    assert http.get(URL, resume=True).body == PAYLOAD
    assert 900 in sleeps


@pytest.mark.parametrize("resume", [True, False])
def test_retry_after_above_900_seconds_is_persisted_as_failure(resume):
    server = FakeServer(HttpResponse(429, {"Retry-After": "901"}, b""))
    http, _ = client(server)
    with pytest.raises(HttpStatusError, match="Retry-After"):
        http.get(URL, resume=resume)


def test_wait_table_without_retry_after():
    server = FakeServer(HttpResponse(429, {}, b""), HttpResponse(503, {}, b""), HttpResponse(200, {}, PAYLOAD))
    http, sleeps = client(server, min_interval=0)
    http.get("https://api.example.invalid/x")
    assert sleeps == [15.0, 30.0]


def test_wait_table_jitter_stays_within_twenty_percent():
    server = FakeServer(HttpResponse(503, {}, b""), HttpResponse(200, {}, b"ok"))
    sleeps = []
    http = HttpClient("offline", transport=server, sleeper=sleeps.append, min_interval=0)
    http.get("https://api.example.invalid/x")
    assert 12.0 <= sleeps[0] <= 18.0


def test_arxiv_pacing_is_kept_while_resuming():
    now = [0.0]
    server = FakeServer(cut(PAYLOAD[:10]), rest(10), clock=now)
    http, _ = client(server, now=now, min_interval=0)
    http.get(URL, resume=True)
    assert server.starts[1] - server.starts[0] >= 3.0


def test_downloader_writes_events_outside_the_manifest(tmp_path):
    server = FakeServer(cut(PAYLOAD[:10]), rest(10))
    http, _ = client(server)
    result = ArxivSourceDownloader(http, tmp_path / "raw").download("2508.02872", 1)
    assert result.status == "success"
    lines = [json.loads(line) for line in (tmp_path / "manifests/http-events.jsonl").read_text().splitlines()]
    assert lines and all(e["arxiv_id"] == "2508.02872" and e["version"] == 1 for e in lines)
    assert {"partial", "resume"} <= {e["event"] for e in lines}
    assert not (tmp_path / "manifests/crawl.jsonl").exists()
    Manifest(tmp_path / "manifests/crawl.jsonl")  # Manifest contract untouched
