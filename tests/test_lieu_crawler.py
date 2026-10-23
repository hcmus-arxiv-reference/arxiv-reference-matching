"""Exercise Lieu scheduling against real receipts/Parquet and fake HTTP."""
from http.client import IncompleteRead
from threading import Event
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock
import json

from scripts.crawl_range import run_range
from src.common.schema import read_table
from src.crawl.discovery import ArxivDiscovery
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.pipeline import CrawlPipeline
from src.crawl.semantic_scholar import SemanticScholarClient
from src.crawl.source import ArxivSourceDownloader
from src.milestone1_crawler import BatchedDiscovery, LieuPipeline
from src.make_ids import build_range
from src.make_stats import load_last_per_id


def atom(identifier, version=1):
    return (f'<entry><id>http://arxiv.org/abs/{identifier}v{version}</id><title>Title</title>'
            f'<published>2025-08-04T00:00:00Z</published><updated>2025-08-0{4+version}T00:00:00Z</updated></entry>')


def setup(tmp_path, versions=None, source=None):
    calls = []
    versions = versions or {}
    def transport(request, _):
        calls.append(request.full_url)
        if '/api/query?' in request.full_url:
            ids = parse_qs(urlsplit(request.full_url).query)['id_list'][0].split(',')
            entries = []
            for identifier in ids:
                base, sep, version = identifier.partition('v')
                entries.append(atom(base, int(version) if sep else versions.get(base, 1)))
            body = '<feed xmlns="http://www.w3.org/2005/Atom">' + ''.join(entries) + '</feed>'
            return HttpResponse(200, {}, body.encode())
        if source:
            return source(request)
        return HttpResponse(200, {}, b'\\documentclass{article}')
    client = HttpClient('offline', transport=transport, sleeper=lambda _: None, max_retries=0)
    refs = Mock(); refs.references.return_value = []
    pipeline = LieuPipeline(BatchedDiscovery(client), ArxivSourceDownloader(client, tmp_path/'raw'), tmp_path, refs)
    return pipeline, calls, refs


def test_range_batches_metadata_and_retains_revision_dates(tmp_path):
    ids = ['2508.02872', '2508.02873']
    pipeline, calls, _ = setup(tmp_path, {ids[0]: 3})
    result = run_range(pipeline, ids, max_passes=1, min_free_bytes=0)
    assert result['status'] == 'complete' and result['engine'] == 'lieu'
    queries = [parse_qs(urlsplit(url).query)['id_list'][0] for url in calls if '/api/query?' in url]
    assert queries == [','.join(ids), '2508.02872v2']
    rows = read_table('papers', tmp_path/'tables/papers.parquet').to_pylist()
    assert rows[0]['revised_dates'] == ['2025-08-06T00:00:00Z', '2025-08-07T00:00:00Z']
    assert len(rows) == 2


def test_resume_existing_main_cache_never_redownloads_valid_sources(tmp_path):
    pipeline, calls, refs = setup(tmp_path)
    old = CrawlPipeline(ArxivDiscovery(pipeline.discovery.client), pipeline.sources, tmp_path, refs)
    old.crawl_ids(['2508.02872'])
    calls.clear(); refs.references.reset_mock()
    assert run_range(pipeline, ['2508.02872'], min_free_bytes=0)['status'] == 'complete'
    assert calls == []
    refs.references.assert_not_called()
    # Checksum failure must invalidate the old receipt even if the directory exists.
    (tmp_path/'raw/2508-02872/v1/single.tex').unlink()
    result = run_range(pipeline, ['2508.02872'], min_free_bytes=0)
    assert result['status'] == 'complete'
    assert len(calls) == 1 and '/src/' in calls[0]


def test_s2_failure_is_pending_and_retry_keeps_source(tmp_path):
    pipeline, calls, refs = setup(tmp_path)
    refs.references.side_effect = [TimeoutError(), []]
    result = run_range(pipeline, ['2508.02872'], max_passes=1, min_free_bytes=0)
    assert result['status'] == 'incomplete'
    assert result['counts']['verified_versions'] == 1
    calls.clear()
    result = run_range(pipeline, ['2508.02872'], max_passes=1, min_free_bytes=0)
    assert result['status'] == 'complete' and calls == []


def test_pdf_is_empty_but_http_404_remains_unavailable(tmp_path):
    def source(req):
        if '02873' in req.full_url:
            return HttpResponse(404, {}, b'')
        return HttpResponse(200, {}, b'%PDF-1.7')
    pipeline, _, _ = setup(tmp_path, source=source)
    result = run_range(pipeline, ['2508.02872', '2508.02873'], max_passes=1, min_free_bytes=0)
    assert result['counts']['complete'] == 1
    assert result['counts']['non_tex_versions'] == 1
    assert pipeline.manifest.get('2508.02873', 1).status == 'unavailable'
    assert result['status'] == 'incomplete'


def test_s2_overlaps_source_and_follows_pagination(tmp_path):
    refs_started, source_started = Event(), Event()
    def source(req):
        source_started.set()
        assert refs_started.wait(2), 'S2 did not overlap the source download'
        return HttpResponse(200, {}, b'\\documentclass{article}')
    pipeline, _, _ = setup(tmp_path, source=source)
    offsets = []
    def s2_transport(req, _):
        offsets.append(parse_qs(urlsplit(req.full_url).query)['offset'][0])
        refs_started.set()
        assert source_started.wait(2), 'source did not overlap S2'
        payload = {'data': [], 'next': 100} if len(offsets) == 1 else {'data': []}
        return HttpResponse(200, {}, json.dumps(payload).encode())
    pipeline.s2 = SemanticScholarClient(HttpClient('offline', transport=s2_transport,
        sleeper=lambda _: None, max_retries=0))
    result = run_range(pipeline, ['2508.02872'], max_passes=1, min_free_bytes=0)
    assert result['status'] == 'complete' and offsets == ['0', '100']


def test_failed_batch_falls_back_to_single_discovery(tmp_path):
    pipeline, calls, _ = setup(tmp_path)
    original = pipeline.discovery.client._transport
    def transport(req, timeout):
        ids = parse_qs(urlsplit(req.full_url).query).get('id_list', [''])[0]
        return HttpResponse(503, {}, b'') if ',' in ids else original(req, timeout)
    pipeline.discovery.client._transport = transport
    result = run_range(pipeline, ['2508.02872', '2508.02873'], max_passes=1, min_free_bytes=0)
    assert result['status'] == 'complete'


def test_truncated_batch_falls_back_without_aborting_range(tmp_path):
    pipeline, _, _ = setup(tmp_path)
    original = pipeline.discovery.client._transport
    def transport(req, timeout):
        if ',' in parse_qs(urlsplit(req.full_url).query).get('id_list', [''])[0]:
            raise IncompleteRead(b'', 10)
        return original(req, timeout)
    pipeline.discovery.client._transport = transport
    result = run_range(pipeline, ['2508.02872', '2508.02873'], max_passes=1, min_free_bytes=0)
    assert result['status'] == 'complete'


def test_imported_id_and_log_utilities(tmp_path):
    assert len(build_range('2508.02872', '2508.07871')) == 5000
    path = tmp_path/'log.jsonl'
    path.write_text('{"id":"2508.02872","status":"error"}\n{"id":"2508.02872","status":"done"}\n')
    assert load_last_per_id(path)['2508.02872']['status'] == 'done'


def test_imported_benchmark_preserves_input_and_child_exit(tmp_path):
    import subprocess
    import sys
    data = tmp_path/'data'; data.mkdir()
    (data/'keep.txt').write_text('keep')
    result = subprocess.run([sys.executable, '-m', 'src.benchmark', '--data-dir', str(data),
        '--out', str(tmp_path/'stats'), '--interval', '0.01', '--disk-interval', '0.01',
        '--', sys.executable, '-c', 'raise SystemExit(3)'], capture_output=True, text=True)
    assert result.returncode == 3
    assert (data/'keep.txt').read_text() == 'keep'
    assert json.loads((tmp_path/'stats/benchmark.json').read_text())['return_code'] == 3
