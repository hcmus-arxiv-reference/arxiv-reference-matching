"""Default Stage implementations of CrawlPipeline (batched Discovery, overlapped S2)."""
from threading import Event
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from src.crawl.discovery import BatchedDiscovery
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.lieu_pipeline import LieuPipeline
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader


def atom(identifier):
    return (f'<entry><id>http://arxiv.org/abs/{identifier}v1</id><title>Title</title>'
            f'<published>2025-08-04T00:00:00Z</published></entry>')


def make(tmp_path, source=None):
    queries = []

    def transport(request, _):
        if '/api/query?' in request.full_url:
            ids = parse_qs(urlsplit(request.full_url).query)['id_list'][0].split(',')
            queries.append(ids)
            body = '<feed xmlns="http://www.w3.org/2005/Atom">' + ''.join(map(atom, ids)) + '</feed>'
            return HttpResponse(200, {}, body.encode())
        return source(request) if source else HttpResponse(200, {}, b'\\documentclass{article}')

    client = HttpClient('offline', transport=transport, sleeper=lambda _: None, max_retries=0)
    refs = Mock()
    refs.references.return_value = []
    pipeline = CrawlPipeline(BatchedDiscovery(client), ArxivSourceDownloader(client, tmp_path / 'raw'),
                             tmp_path, references=refs)
    return pipeline, queries, refs


def test_crawl_ids_batches_discovery_by_default(tmp_path):
    pipeline, queries, _ = make(tmp_path)
    stats = pipeline.crawl_ids(['2508.02872', '2508.02873'])
    assert queries == [['2508.02872', '2508.02873']]
    assert stats['success'] == 2 and stats['references_success'] == 2
    queries.clear()
    assert pipeline.crawl_ids(['2508.02872', '2508.02873'])['skipped'] == 2
    assert queries == []  # verified metadata is not prefetched again


def test_references_overlap_source_download(tmp_path):
    refs_started, source_started = Event(), Event()

    def source(_request):
        source_started.set()
        assert refs_started.wait(2), 'S2 did not overlap the source download'
        return HttpResponse(200, {}, b'\\documentclass{article}')

    pipeline, _, refs = make(tmp_path, source)

    def references(_identifier):
        refs_started.set()
        assert source_started.wait(2), 'source did not overlap S2'
        return []

    refs.references.side_effect = references
    stats = pipeline.crawl_ids(['2508.02872'])
    assert stats['errors'] == 0 and stats['references_success'] == 1


def test_s2_failure_is_recorded_without_marking_references_done(tmp_path):
    pipeline, _, refs = make(tmp_path)
    refs.references.side_effect = TimeoutError()
    stats = pipeline.crawl_ids(['2508.02872'])
    assert stats['success'] == 1 and stats['errors'] == 1
    assert pipeline.manifest.get('2508.02872', None, 'references').status == 'error'


def test_lieu_pipeline_is_only_an_alias(tmp_path):
    assert {name for name in vars(LieuPipeline) if not name.startswith('__')} == {'engine', 's2'}
    pipeline, _, refs = make(tmp_path)
    alias = LieuPipeline(pipeline.discovery, pipeline.sources, tmp_path / 'other', refs)
    assert alias.s2 is refs
