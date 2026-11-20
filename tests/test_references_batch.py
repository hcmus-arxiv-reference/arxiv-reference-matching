"""References theo lô: the S2 batch call and how CrawlPipeline uses it.

All HTTP is an in-memory transport; S2 requests are recorded as (method, IDs).
"""
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from src.crawl import pipeline as pipeline_module
from src.crawl.discovery import BatchedDiscovery
from src.crawl.http_client import HttpClient, HttpResponse, HttpStatusError
from src.crawl.pipeline import CrawlPipeline
from src.crawl.semantic_scholar import SemanticScholarClient
from src.crawl.source import ArxivSourceDownloader

A, B, C = '2508.02872', '2508.02873', '2508.02874'


def paper(n):
    """A citedPaper object as S2 returns it."""
    return {'paperId': f'p{n}', 'externalIds': {'ArXiv': f'2401.{n:05d}'}, 'title': f'T{n}',
            'authors': [{'authorId': '1', 'name': 'An'}], 'publicationDate': '2024-01-02'}


def client(transport):
    return HttpClient('offline', transport=transport, sleeper=lambda _: None, max_retries=0)


def make(tmp_path, batch, single=None, now=None):
    """Pipeline whose S2 transport answers POST /paper/batch with ``batch(ids)``.

    ``batch`` returns the JSON payload or an HTTP status; ``single(arxiv_id)``
    returns the rows of the paginated endpoint. ``now`` is a fake clock that
    every request advances by 3 seconds.
    """
    calls = []

    def tick():
        if now is not None:
            now[0] += 3

    def arxiv(request, _):
        tick()
        if '/api/query?' in request.full_url:
            ids = parse_qs(urlsplit(request.full_url).query)['id_list'][0].split(',')
            entries = ''.join(f'<entry><id>http://arxiv.org/abs/{i}v1</id><title>T</title>'
                              f'<published>2025-08-04T00:00:00Z</published></entry>' for i in ids)
            return HttpResponse(200, {}, f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode())
        return HttpResponse(200, {}, b'\\documentclass{article}')

    def s2(request, _):
        tick()
        if request.get_method() == 'POST':
            ids = [i.removeprefix('ARXIV:') for i in json.loads(request.data)['ids']]
            calls.append(('POST', ids))
            answer = batch(ids)
            if isinstance(answer, int):
                return HttpResponse(answer, {}, b'')
            return HttpResponse(200, {}, json.dumps(answer).encode())
        arxiv_id = urlsplit(request.full_url).path.split('ARXIV:')[1].split('/')[0]
        calls.append(('GET', [arxiv_id]))
        return HttpResponse(200, {}, json.dumps({'data': single(arxiv_id)}).encode())

    engine = CrawlPipeline(BatchedDiscovery(client(arxiv)), ArxivSourceDownloader(client(arxiv), tmp_path / 'raw'),
                           tmp_path, references=SemanticScholarClient(client(s2)))
    if now is not None:
        engine.clock = lambda: now[0]
    return engine, calls


def cached_rows(tmp_path, arxiv_id):
    return json.loads((tmp_path / 'references' / f"{arxiv_id.replace('.', '-')}.json").read_text())['rows']


def reference_task(engine, arxiv_id):
    return engine.manifest.get(arxiv_id, None, 'references')


def test_client_posts_ids_and_returns_rows_in_the_paginated_shape():
    seen = {}

    def transport(request, _):
        seen.update(method=request.get_method(), url=request.full_url, body=json.loads(request.data),
                    content_type=request.get_header('Content-type'))
        return HttpResponse(200, {}, json.dumps([{'paperId': 'x', 'references': [paper(1), None]}, None]).encode())

    result = SemanticScholarClient(client(transport)).references_batch([A, B])
    assert seen['method'] == 'POST' and seen['body'] == {'ids': [f'ARXIV:{A}', f'ARXIV:{B}']}
    assert seen['content_type'] == 'application/json'
    assert urlsplit(seen['url']).path.endswith('/paper/batch')
    assert parse_qs(urlsplit(seen['url']).query)['fields'] == [
        'references.paperId,references.externalIds,references.title,references.authors,references.publicationDate']
    assert result == {A: [{'citedPaper': paper(1)}, {'citedPaper': None}], B: None}


@pytest.mark.parametrize('payload', [{'data': []}, [{'references': []}], [{'references': 'x'}, None]])
def test_client_rejects_a_batch_it_cannot_map_to_the_ids(payload):
    transport = lambda request, _: HttpResponse(200, {}, json.dumps(payload).encode())
    with pytest.raises(ValueError):
        SemanticScholarClient(client(transport)).references_batch([A, B])


def test_client_reports_http_status_and_bounds_the_batch():
    s2 = SemanticScholarClient(client(lambda request, _: HttpResponse(429, {}, b'')), batch_size=2)
    with pytest.raises(HttpStatusError) as error:
        s2.references_batch([A])
    assert error.value.status == 429
    for ids in ([], [A, B, C], [A, A]):
        with pytest.raises(ValueError):
            s2.references_batch(ids)


def test_post_is_retried_like_get():
    answers = [HttpResponse(429, {}, b''), HttpResponse(200, {}, b'ok')]
    waits = []
    http = HttpClient('offline', transport=lambda request, _: answers.pop(0), sleeper=waits.append,
                      max_retries=1, min_interval=0, jitter=lambda low, high: 1.0)
    assert http.post('https://api.semanticscholar.org/x', b'{}').body == b'ok'
    assert waits == [15.0]


def test_one_batch_serves_the_publication_and_the_upcoming_ones(tmp_path):
    engine, calls = make(tmp_path, lambda ids: [{'references': [paper(n)]} for n, _ in enumerate(ids)])
    assert engine.crawl_ids([A], upcoming=[B])['references_success'] == 1
    assert engine.crawl_ids([B])['references_success'] == 1
    assert calls == [('POST', [A, B])]
    assert cached_rows(tmp_path, A) == [{'citedPaper': paper(0)}]
    assert cached_rows(tmp_path, B) == [{'citedPaper': paper(1)}]
    assert engine.status(A).complete and engine.status(B).complete
    engine.crawl_ids([A, B])                 # verified caches are not requested again
    assert calls == [('POST', [A, B])]


def test_throttled_batch_is_not_repeated_one_by_one_and_is_batched_again_next_pass(tmp_path):
    answers = [429, None]
    engine, calls = make(tmp_path, lambda ids: answers.pop(0) or [{'references': []} for _ in ids])
    stats = engine.crawl_ids([A], upcoming=[B])
    stats_b = engine.crawl_ids([B])
    assert calls == [('POST', [A, B])]       # no GET per Publication behind the 429
    assert stats['errors'] == 1 and stats_b['errors'] == 1
    assert (reference_task(engine, A).status, reference_task(engine, A).http_status) == ('error', 429)
    assert engine.status(A).sources_complete and not engine.status(A).complete
    engine.crawl_ids([A], upcoming=[B])      # next pass
    engine.crawl_ids([B])
    assert calls == [('POST', [A, B]), ('POST', [A, B])]
    assert engine.status(A).complete and engine.status(B).complete


def test_publication_unknown_to_s2_is_recorded_as_404(tmp_path):
    engine, calls = make(tmp_path, lambda ids: [None for _ in ids])
    assert engine.crawl_ids([A])['errors'] == 1
    assert calls == [('POST', [A])]
    assert (reference_task(engine, A).status, reference_task(engine, A).http_status) == ('error', 404)


def test_possibly_truncated_list_is_paginated(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_module, 'BATCH_ROW_LIMIT', 2)
    full = [{'citedPaper': paper(n)} for n in range(3)]
    engine, calls = make(tmp_path, lambda ids: [{'references': [paper(0), paper(1)]}], single=lambda _: full)
    assert engine.crawl_ids([A])['references_success'] == 1
    assert calls == [('POST', [A]), ('GET', [A])]
    assert cached_rows(tmp_path, A) == full


def test_unusable_batch_falls_back_to_one_request_per_publication(tmp_path):
    engine, calls = make(tmp_path, lambda ids: 400, single=lambda _: [{'citedPaper': paper(7)}])
    engine.crawl_ids([A], upcoming=[B])
    engine.crawl_ids([B])
    assert calls == [('POST', [A, B]), ('GET', [A]), ('GET', [B])]
    assert engine.status(A).complete and engine.status(B).complete


def test_batch_time_is_charged_to_the_first_publication_apart_from_discovery(tmp_path):
    now = [0.0]
    engine, _ = make(tmp_path, lambda ids: [{'references': []} for _ in ids], now=now)
    engine.crawl_ids([A], upcoming=[B])      # Discovery batch + References batch + v1 source
    engine.crawl_ids([B])                    # v1 source only
    first, second = [json.loads(line) for line in
                     (tmp_path / 'manifests' / 'timings.jsonl').read_text().splitlines()]
    assert (first['seconds'], first['discovery_seconds'], first['batch_references_seconds']) == (9, 3, 3)
    assert (second['seconds'], second['discovery_seconds'], second['batch_references_seconds']) == (3, 0, 0)
