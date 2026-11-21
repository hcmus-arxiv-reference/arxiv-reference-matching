"""Batched Discovery must ask arXiv for the whole batch, not the default 10 entries."""
from urllib.parse import parse_qs, urlsplit

from src.crawl.discovery import BatchedDiscovery
from src.crawl.http_client import HttpClient, HttpResponse

IDS = [f"2508.{n:05d}" for n in range(2872, 2922)]   # 50 IDs


def arxiv_like(requests):
    """Fake API that, like export.arxiv.org, returns at most max_results (default 10) entries."""
    def transport(request, _):
        query = parse_qs(urlsplit(request.full_url).query)
        requests.append(query)
        ids = query["id_list"][0].split(",")
        limit = int(query.get("max_results", ["10"])[0])
        entries = "".join(f"<entry><id>http://arxiv.org/abs/{i}v1</id><title>T</title>"
                          f"<published>2025-08-04T00:00:00Z</published></entry>" for i in ids[:limit])
        return HttpResponse(200, {}, f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode())
    return transport


def test_one_request_prefetches_the_whole_batch():
    requests = []
    client = HttpClient("offline", transport=arxiv_like(requests), sleeper=lambda _: None, max_retries=0)
    discovery = BatchedDiscovery(client, batch_size=50)
    discovery.prefetch(IDS)
    assert len(requests) == 1 and requests[0]["max_results"] == ["50"]
    assert set(discovery.prefetched) == set(IDS)
    for identifier in IDS:                       # served from the batch, no fallback request
        assert discovery.discover(identifier).arxiv_id == identifier
    assert len(requests) == 1


def throttled_then(ok_after, requests, status=429, batches_only=False):
    """Fake API that throttles the first ``ok_after`` requests, then behaves like arXiv."""
    good = arxiv_like(requests)

    def transport(request, timeout):
        single = "," not in parse_qs(urlsplit(request.full_url).query)["id_list"][0]
        if len(requests) < ok_after and not (batches_only and single):
            requests.append(parse_qs(urlsplit(request.full_url).query))
            return HttpResponse(status, {}, b"")
        return good(request, timeout)
    return transport


def make(transport, log=None):
    pauses = []   # batch pauses only; HttpClient also sleeps ~3 s to space arXiv requests
    client = HttpClient("offline", transport=transport,
                        sleeper=lambda s: pauses.append(s) if s >= 10 else None, max_retries=0,
                        name="arxiv", on_request=(log.append if log is not None else None))
    return BatchedDiscovery(client, batch_size=50), pauses


def test_throttled_batch_is_retried_whole_not_per_id():
    requests, log = [], []
    discovery, pauses = make(throttled_then(3, requests), log)
    discovery.prefetch(IDS)
    assert len(requests) == 4                          # 3 throttled + 1 good, all for the batch
    assert all(q["id_list"][0].count(",") == 49 for q in requests)
    assert pauses == [60.0, 120.0, 240.0]
    assert [r["status"] for r in log if r["event"] == "backoff"] == [429, 429, 429]
    for identifier in IDS:
        assert discovery.discover(identifier).arxiv_id == identifier
    assert len(requests) == 4


def test_batch_still_throttled_fails_ids_without_requests_until_next_pass():
    requests = []
    discovery, pauses = make(throttled_then(10**6, requests, status=503))
    discovery.prefetch(IDS)
    sent = len(requests)
    assert sent == 7 and len(pauses) == 5             # one try per pause, one single ID, then give up
    assert requests[-1]["id_list"] == [IDS[0]]
    try:
        discovery.discover(IDS[0])
    except Exception as error:
        assert getattr(error, "status", None) == 429
    else:
        raise AssertionError("throttled ID must fail")
    assert len(requests) == sent                      # no per-ID request
    discovery.prefetch(IDS[:1])                       # next pass batches again
    assert len(requests) > sent


def test_rejected_batch_still_falls_back_per_id():
    requests = []
    discovery, pauses = make(throttled_then(1, requests, status=400))
    discovery.prefetch(IDS)
    assert len(requests) == 1 and pauses == []
    assert discovery.discover(IDS[0]).arxiv_id == IDS[0]   # one-ID query
    assert len(requests) == 2 and requests[1]["id_list"] == [IDS[0]]


def test_batch_only_failure_falls_back_after_one_single_id_answers():
    requests = []
    discovery, pauses = make(throttled_then(10**6, requests, status=503, batches_only=True))
    discovery.prefetch(IDS)
    assert len(pauses) == 5 and len(requests) == 7     # 6 batch tries + 1 single ID
    assert discovery.discover(IDS[0]).arxiv_id == IDS[0]
    assert len(requests) == 7                          # the single answer was kept
    assert discovery.discover(IDS[1]).arxiv_id == IDS[1]
    assert len(requests) == 8 and requests[-1]["id_list"] == [IDS[1]]
