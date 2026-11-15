"""Log từng request, mô hình thời gian chạy và lệnh kiểm (offline, transport giả)."""
import json
import threading
from urllib.error import URLError

import pytest

from scripts import predict_runtime
from src.common.metrics import JsonlLog
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.runtime_model import (GAP_SECONDS, Link, RangeShape, check_run, describe,
                                     link_from_requests, predict_seconds)


def fake_client(answers, records, *, clock=None, max_retries=2):
    """HttpClient whose transport returns ``answers`` in order (an exception is raised)."""
    def transport(request, _):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    kwargs = {"clock": clock} if clock else {}
    return HttpClient("offline", transport=transport, sleeper=lambda _: None, max_retries=max_retries,
                      jitter=lambda a, b: 1.0, name="s2", on_request=records.append, **kwargs)


def test_every_attempt_and_backoff_is_logged_without_url_or_headers():
    records = []
    http = fake_client([HttpResponse(429, {}, b""), HttpResponse(200, {}, b"0123456789")], records)
    http.get("https://api.semanticscholar.org/graph/v1/paper/ARXIV:2508.02872/references?fields=x")
    assert [(r["event"], r.get("status")) for r in records] == [("request", 429), ("backoff", 429), ("request", 200)]
    assert records[0]["endpoint"] == "graph" and records[2]["bytes"] == 10
    assert records[1]["delay"] == 15.0
    assert all(r["service"] == "s2" for r in records)
    text = json.dumps(records)
    assert "semanticscholar" not in text and "2508" not in text and "fields" not in text


def test_network_errors_are_logged_then_retried():
    records = []
    http = fake_client([URLError("down"), HttpResponse(200, {}, b"ok")], records)
    assert http.get("https://example.org/x").body == b"ok"
    assert records[0]["error"] == "URLError" and records[1] == {
        "service": "s2", "event": "backoff", "status": None, "error": "URLError", "delay": 1.0}
    assert records[2]["status"] == 200


def test_a_failing_log_never_breaks_a_request():
    def broken(_):
        raise OSError("disk full")
    http = HttpClient("offline", transport=lambda r, t: HttpResponse(200, {}, b"ok"),
                      sleeper=lambda _: None, on_request=broken)
    assert http.get("https://example.org/x").body == b"ok"


def test_jsonl_log_keeps_lines_whole_across_threads(tmp_path):
    log = JsonlLog(tmp_path / "requests.jsonl")
    threads = [threading.Thread(target=lambda n=n: [log({"n": n, "pad": "x" * 500}) for _ in range(50)])
               for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = [json.loads(line) for line in (tmp_path / "requests.jsonl").read_text().splitlines()]
    assert len(lines) == 200 and all("at" in line for line in lines)


def test_prediction_is_the_pacing_floor_until_files_outgrow_it():
    link = Link(1_000_000, 0.0, 1, True)
    shape = RangeShape(10, 4, 6)
    assert predict_seconds([100], link, shape) == pytest.approx(10 * GAP_SECONDS)
    assert predict_seconds([10_000_000], link, shape) == pytest.approx(4 * 10 + 6 * GAP_SECONDS)


def source(size, seconds, **extra):
    return {"service": "arxiv", "event": "request", "endpoint": "src", "status": 200,
            "bytes": size, "seconds": seconds, "paced": 0.0, "range": False, **extra}


def test_link_uses_small_files_for_latency_and_large_ones_for_bandwidth():
    link = link_from_requests([source(100_000, 0.4), source(5_000_000, 5.4)])
    assert link.latency_seconds == pytest.approx(0.4) and link.latency_measured
    assert link.bandwidth_bps == pytest.approx(1_000_000)
    assert link_from_requests([]) is None


def run_log(n, *, s2_wait=0.0, overhead=0.0):
    """n Publications, one 5 MB source each at 1 MB/s plus one 0.1 MB file: wall = model + overhead."""
    requests, timings = [], []
    for _ in range(n):
        requests += [source(5_000_000, 5.4, paced=0.0), source(100_000, 0.4, paced=2.7)]
        timings.append({"seconds": 5.4 + 3.1 + s2_wait + overhead, "references_wait_seconds": s2_wait})
    return requests, timings


def test_run_that_matches_the_model_passes():
    requests, timings = run_log(20, overhead=0.2)
    result = check_run(requests, timings, sizes=[5_000_000, 100_000])
    assert result["verdict"] == "ĐẠT", result
    assert result["predicted_from"] == "run_files"
    assert abs(result["deviation"]) < 0.05 and result["explained_share"] > 0.95
    assert "ĐẠT" in describe(result)


def test_run_held_up_by_s2_fails_the_gate():
    requests, timings = run_log(20, s2_wait=2.0)
    result = check_run(requests, timings, sizes=[5_000_000, 100_000])
    assert result["verdict"] == "KHÔNG ĐẠT" and result["s2"]["arxiv_wait_share"] > 0.05


def test_empty_run_is_not_enough_data():
    assert check_run([], [], sizes=[1])["verdict"] == "CHƯA ĐỦ SỐ LIỆU"


def test_check_command_reads_the_manifests(tmp_path, capsys):
    requests, timings = run_log(20)
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "requests.jsonl").write_text("".join(json.dumps(r) + "\n" for r in requests))
    (manifests / "timings.jsonl").write_text("".join(json.dumps(t) + "\n" for t in timings))
    code = predict_runtime.main(["check", "--data-dir", str(tmp_path), "--out", str(tmp_path / "check.json")])
    assert code == 0 and "KẾT LUẬN: ĐẠT" in capsys.readouterr().out
    assert json.loads((tmp_path / "check.json").read_text())["verdict"] == "ĐẠT"


def test_speedtest_measures_the_downloads():
    now = [0.0]

    def transport(request, _):
        now[0] += 8.5        # 8 MB in 8.5 s
        return HttpResponse(200, {}, b"x" * 8_000_000)

    http = HttpClient("offline", transport=transport, sleeper=lambda s: now.__setitem__(0, now[0] + s),
                      clock=lambda: now[0], name="arxiv")
    result = predict_runtime.speedtest(("2508.03249v1",), client=http)
    assert result["link"]["bandwidth_bps"] == pytest.approx(8_000_000 / 8.0)
    assert result["files"] == [{"bytes": 8_000_000, "seconds": 8.5}]
    assert result["range_hours_predicted"] > 7.0


def test_speedtest_reports_a_throttled_discovery_api():
    now, sent = [0.0], []

    def transport(request, _):
        sent.append(request.full_url)
        now[0] += 1.0
        if "/api/query" in request.full_url:
            return HttpResponse(429, {}, b"")
        return HttpResponse(200, {}, b"x" * 8_000_000)

    http = HttpClient("offline", transport=transport, sleeper=lambda s: now.__setitem__(0, now[0] + s),
                      clock=lambda: now[0], name="arxiv")
    result = predict_runtime.speedtest(("2508.03249v1",), client=http)
    assert result["api"] == {"requests": 3, "ok": 0, "status_429": 3, "median_seconds": 1.0, "throttled": True}
    assert sum("/api/query" in u for u in sent) == 3          # no retries while probing
    assert http.max_retries == 4 and http.on_request is not None   # client restored


def test_probe_counts_timeouts_as_throttled():
    def transport(request, _):
        raise TimeoutError("slow")

    http = HttpClient("offline", transport=transport, sleeper=lambda _: None, name="arxiv")
    api = predict_runtime.probe_api(http, ["2508.03249"], probes=2)
    assert api["requests"] == 2 and api["ok"] == 0 and api["throttled"]
