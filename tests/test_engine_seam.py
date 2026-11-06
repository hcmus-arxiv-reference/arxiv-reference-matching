"""CrawlPipeline as the Engine: locks, Manifest index and Discovery batching."""
import math
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from filelock import Timeout
import pytest

from src.crawl.discovery import BatchedDiscovery
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.manifest import Manifest, TaskRecord
from src.crawl.pipeline import CrawlPipeline
from src.crawl.runner import publication_issues, run_range
from src.crawl.source import ArxivSourceDownloader


def build_range(prefix, first, last):
    return [f'{prefix}.{n:05d}' for n in range(first, last + 1)]


def atom(identifier):
    return (f'<entry><id>http://arxiv.org/abs/{identifier}v1</id><title>Title</title>'
            '<published>2025-08-04T00:00:00Z</published>'
            '<updated>2025-08-04T00:00:00Z</updated></entry>')


def make_pipeline(tmp_path, batch_size=50):
    calls = []

    def transport(request, _):
        calls.append(request.full_url)
        if '/api/query?' in request.full_url:
            ids = parse_qs(urlsplit(request.full_url).query)['id_list'][0].split(',')
            body = '<feed xmlns="http://www.w3.org/2005/Atom">' + ''.join(map(atom, ids)) + '</feed>'
            return HttpResponse(200, {}, body.encode())
        return HttpResponse(200, {}, b'\\documentclass{article}')

    client = HttpClient('offline', transport=transport, sleeper=lambda _: None, max_retries=0)
    refs = Mock()
    refs.references.return_value = []
    pipeline = CrawlPipeline(BatchedDiscovery(client, batch_size),
                             ArxivSourceDownloader(client, tmp_path / 'raw'), tmp_path, refs)
    return pipeline, calls


def queries(calls):
    return [url for url in calls if '/api/query?' in url]


def test_walking_a_range_costs_one_discovery_batch_per_window(tmp_path):
    pipeline, calls = make_pipeline(tmp_path)
    ids = build_range('2508', 2872, 2872 + 119)
    result = run_range(pipeline, ids, max_passes=1, min_free_bytes=0)
    assert result['status'] == 'complete'
    assert len(queries(calls)) <= math.ceil(len(ids) / 50) == 3

    calls.clear()
    assert run_range(pipeline, ids, max_passes=1, min_free_bytes=0)['status'] == 'complete'
    assert calls == []  # resumed: verified metadata and sources, no request


def test_cached_ids_never_start_a_batch(tmp_path):
    pipeline, calls = make_pipeline(tmp_path)
    ids = build_range('2508', 2872, 2874)
    pipeline.crawl_ids(ids[:1])
    calls.clear()
    pipeline.crawl_ids(ids[:1], upcoming=ids[1:])
    assert queries(calls) == []


def test_corpus_lock_nests_and_reloads_only_on_outermost_entry(tmp_path):
    pipeline, _ = make_pipeline(tmp_path)
    ids = build_range('2508', 2872, 2872)
    pipeline.crawl_ids(ids)
    with pipeline.corpus_lock():
        manifest = pipeline.manifest
        bundles, _ = pipeline.export(ids)  # nested: no Timeout, no reload
        pipeline.crawl_ids(ids)
        assert pipeline.manifest is manifest and len(bundles) == 1
    pipeline.export(ids)
    assert pipeline.manifest is not manifest


def test_exclusive_rejects_a_second_engine_on_the_same_directory(tmp_path):
    first, _ = make_pipeline(tmp_path)
    second, _ = make_pipeline(tmp_path)
    with first.exclusive():
        with pytest.raises(Timeout):
            with second.exclusive():
                pass
    with second.exclusive():
        pass


def test_exclusive_reloads_checkpoints_written_by_another_process(tmp_path):
    pipeline, _ = make_pipeline(tmp_path)
    Manifest(pipeline.manifest.path).upsert(TaskRecord('2508.02872', None, 'references', 'error'))
    with pipeline.exclusive():
        assert pipeline.issues('2508.02872')[0]['status'] == 'error'


def test_records_for_returns_latest_task_records_of_one_publication(tmp_path):
    manifest = Manifest(tmp_path / 'crawl.jsonl')
    manifest.upsert(TaskRecord('2508.02872', 1, 'source', 'error'))
    manifest.upsert(TaskRecord('2508.02872', 1, 'source', 'success'))
    manifest.upsert(TaskRecord('2508.02872', None, 'references', 'error'))
    manifest.upsert(TaskRecord('2508.02873', 1, 'source', 'error'))
    for view in (manifest, Manifest(tmp_path / 'crawl.jsonl')):
        assert {(r.kind, r.status) for r in view.records_for('2508.02872')} == {
            ('source', 'success'), ('references', 'error')}
        assert view.records_for('2508.09999') == []
    assert [i['kind'] for i in publication_issues(manifest, '2508.02872')] == ['references']
