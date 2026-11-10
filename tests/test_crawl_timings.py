"""Per-Publication timing log (manifests/timings.jsonl) and its make_stats summary.

Every HTTP request advances a fake clock by 3 seconds, so expected times are exact.
"""
import json
from urllib.parse import parse_qs, urlsplit

from src import make_stats
from src.crawl.discovery import BatchedDiscovery
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader

FIRST, SECOND, BROKEN = '2508.02872', '2508.02873', '2508.02874'


def make_pipeline(tmp_path):
    now = [0.0]

    def transport(request, _):
        now[0] += 3
        url = request.full_url
        if '/api/query?' in url:
            ids = parse_qs(urlsplit(url).query)['id_list'][0].split(',')
            entries = ''.join(
                f'<entry><id>http://arxiv.org/abs/{i}v1</id><title>T</title>'
                f'<published>2025-08-04T00:00:00Z</published></entry>'
                for i in ids if i != BROKEN)        # BROKEN is never returned
            return HttpResponse(200, {}, f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode())
        return HttpResponse(200, {}, b'\\documentclass{article}')

    client = HttpClient('offline', transport=transport, sleeper=lambda _: None, max_retries=0)
    pipeline = CrawlPipeline(BatchedDiscovery(client), ArxivSourceDownloader(client, tmp_path / 'raw'),
                             tmp_path)
    pipeline.clock = lambda: now[0]
    return pipeline


def read_timings(tmp_path):
    lines = (tmp_path / 'manifests' / 'timings.jsonl').read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_batch_is_charged_to_the_publication_that_triggered_it(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.crawl_ids([FIRST], upcoming=[SECOND])   # batch request + v1 source
    pipeline.crawl_ids([SECOND])                     # prefetched: v1 source only
    first, second = read_timings(tmp_path)
    assert (first['arxiv_id'], first['seconds'], first['discovery_seconds'],
            first['batch_discovery_seconds']) == (FIRST, 6, 3, 3)
    assert (second['arxiv_id'], second['seconds'], second['discovery_seconds']) == (SECOND, 3, 0)


def test_failed_discovery_is_still_timed(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.crawl_ids([BROKEN])        # batch without BROKEN, then one fallback request
    (record,) = read_timings(tmp_path)
    assert (record['seconds'], record['discovery_seconds']) == (6, 6)


def test_make_stats_sums_visits_and_discovery(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.crawl_ids([FIRST], upcoming=[SECOND])
    pipeline.crawl_ids([SECOND])
    pipeline.crawl_ids([BROKEN])
    pipeline.crawl_ids([BROKEN])        # failed IDs are batched again: 6 more seconds
    rows = {r['id']: r for r in make_stats.collect(tmp_path, [FIRST, SECOND, BROKEN])}
    assert (rows[FIRST]['seconds'], rows[SECOND]['seconds'], rows[BROKEN]['seconds']) == (6, 3, 12)
    summary = make_stats.summarize(list(rows.values()), 3)
    assert summary['papers_timed'] == 3 and summary['total_seconds_timed'] == 21
    assert summary['avg_seconds_per_paper'] == 7 and summary['median_seconds_per_paper'] == 6
    assert summary['max_seconds_per_paper'] == 12 and summary['discovery_seconds_total'] == 15


def test_partial_final_timing_line_is_ignored(tmp_path):
    pipeline = make_pipeline(tmp_path)
    pipeline.crawl_ids([SECOND])
    path = tmp_path / 'manifests' / 'timings.jsonl'
    path.write_text(path.read_text() + '{"arxiv_id": "2508.0')
    assert make_stats.load_timings(path) == {SECOND: (6.0, 3.0)}
