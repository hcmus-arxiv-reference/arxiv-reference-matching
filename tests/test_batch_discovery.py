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
