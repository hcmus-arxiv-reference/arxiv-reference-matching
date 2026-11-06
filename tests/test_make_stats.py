"""make_stats reads the src/crawl Manifest (crawl.jsonl) and its caches."""
import csv
import json
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from src import benchmark, make_stats
from src.crawl.discovery import BatchedDiscovery
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader

DONE, MISSING, S2_FAIL, NEVER = '2508.02872', '2508.02873', '2508.02874', '2508.02875'


def atom(identifier, version):
    return (f'<entry><id>http://arxiv.org/abs/{identifier}v{version}</id><title>T</title>'
            f'<published>2025-08-04T00:00:00Z</published>'
            f'<updated>2025-08-0{4 + version}T00:00:00Z</updated></entry>')


@pytest.fixture
def cache(tmp_path):
    """DONE has v1 TeX + v2 PDF and 2 S2 rows (1 with arXiv ID); MISSING is HTTP 404."""
    def transport(request, _):
        url = request.full_url
        if '/api/query?' in url:
            ids = parse_qs(urlsplit(url).query)['id_list'][0].split(',')
            entries = ''.join(atom(base, int(v) if v else (2 if base == DONE else 1))
                              for base, _, v in (i.partition('v') for i in ids))
            return HttpResponse(200, {}, f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode())
        if MISSING in url:
            return HttpResponse(404, {}, b'')
        return HttpResponse(200, {}, b'%PDF-1.7' if url.endswith('v2') else b'\\documentclass{article}')

    client = HttpClient('offline', transport=transport, sleeper=lambda _: None, max_retries=0)
    rows = {DONE: [{'citedPaper': {'title': 'A', 'externalIds': {'ArXiv': '1706.03762'}}},
                   {'citedPaper': {'title': 'B', 'externalIds': {}}}], MISSING: []}

    def references(identifier):
        if identifier == S2_FAIL:
            raise TimeoutError()
        return rows[identifier]

    refs = Mock()
    refs.references.side_effect = references
    pipeline = CrawlPipeline(BatchedDiscovery(client), ArxivSourceDownloader(client, tmp_path / 'raw'),
                             tmp_path, references=refs)
    pipeline.crawl_ids([DONE, MISSING, S2_FAIL])
    return tmp_path


def test_rows_follow_last_manifest_record(cache):
    rows = {r['id']: r for r in make_stats.collect(cache, [DONE, MISSING, S2_FAIL, NEVER])}
    assert {i: r['status'] for i, r in rows.items()} == {
        DONE: 'done', MISSING: 'unavailable', S2_FAIL: 'error', NEVER: 'not_attempted'}
    done = rows[DONE]
    assert (done['n_versions'], done['versions_with_tex'], done['versions_non_tex']) == (2, 1, 1)
    assert done['bytes_after'] == len(b'\\documentclass{article}')
    assert (done['n_refs'], done['n_refs_with_arxiv_id']) == (2, 1)
    assert rows[MISSING]['versions_unavailable'] == 1 and rows[MISSING]['n_refs'] == 0
    assert rows[S2_FAIL]['n_refs'] is None
    assert rows[NEVER]['n_versions'] is None  # unknown, not zero


def test_cli_writes_summary_and_csv(cache, tmp_path):
    ids = tmp_path / 'ids.txt'
    ids.write_text(f'# range\n{DONE}\n{MISSING}\n{S2_FAIL}\n{NEVER}\n')
    out = tmp_path / 'stats'
    make_stats.main(['--data-dir', str(cache), '--ids-file', str(ids), '--out', str(out)])
    summary = json.loads((out / 'summary.json').read_text())
    assert summary['papers_requested'] == 4 and summary['papers_done'] == 1
    assert summary['paper_success_rate'] == 0.25
    assert (summary['versions_total'], summary['versions_with_tex'], summary['versions_non_tex'],
            summary['versions_unavailable']) == (4, 2, 1, 1)
    # DONE: v1 plain TeX (23 bytes kept), v2 PDF (8 bytes, nothing kept).
    assert summary['avg_bytes_before_per_paper'] == 31 and summary['avg_bytes_after_per_paper'] == 23
    assert summary['avg_bytes_downloaded_per_paper'] == 31 and summary['papers_with_size_before'] == 1
    assert summary['size_reduction_pct'] == 25.81
    assert summary['papers_with_ref_metadata'] == 2
    with (out / 'papers.csv').open() as f:
        assert [r['id'] for r in csv.DictReader(f)] == [DONE, MISSING, S2_FAIL, NEVER]


def test_partial_final_line_is_ignored_without_touching_manifest(cache):
    manifest = cache / 'manifests' / 'crawl.jsonl'
    record = {'arxiv_id': DONE, 'version': None, 'kind': 'references', 'status': 'error'}
    manifest.write_bytes(manifest.read_bytes() + json.dumps(record).encode()[:-5])
    before = manifest.read_bytes()
    assert make_stats.count_done(cache) == 1
    assert manifest.read_bytes() == before


def test_corrupt_inner_line_is_an_error(cache):
    manifest = cache / 'manifests' / 'crawl.jsonl'
    manifest.write_bytes(b'{broken\n' + manifest.read_bytes())
    with pytest.raises(ValueError, match='line 1'):
        make_stats.collect(cache)


def test_benchmark_counts_both_layouts(cache, tmp_path):
    assert benchmark.count_done(cache) == 1
    standalone = tmp_path / 'standalone'
    (standalone / '2508.02872').mkdir(parents=True)
    (standalone / '2508.02872' / 'done.json').write_text('{}')
    assert benchmark.count_done(standalone) == 1


def test_arxiv_count_is_before_deduplication_like_validator(cache):
    # Two raw rows for one arXiv paper: 2 raw rows with an arXiv ID, 1 Reference.
    path = cache / 'references' / '2508-02872.json'
    payload = json.loads(path.read_text())
    payload['rows'] = [{'citedPaper': {'externalIds': {'ArXiv': '1706.03762v1'}}},
                       {'citedPaper': {'externalIds': {'ArXiv': '1706.03762v2'}}},
                       {'citedPaper': {'externalIds': {}}}]
    path.write_text(json.dumps(payload))
    row = {r['id']: r for r in make_stats.collect(cache, [DONE])}[DONE]
    assert (row['n_refs'], row['n_refs_with_arxiv_id'], row['n_references']) == (3, 2, 1)
    summary = make_stats.summarize([row], 1)
    assert summary['avg_refs_with_arxiv_id_per_paper'] == 2 and summary['avg_references_per_paper'] == 1
def test_receipts_without_size_fields_stay_out_of_the_comparison(cache):
    receipt = cache / 'raw' / '2508-02872' / 'v2' / 'source.json'
    payload = json.loads(receipt.read_text())
    del payload['content_bytes']
    receipt.write_text(json.dumps(payload))
    rows = {r['id']: r for r in make_stats.collect(cache, [DONE])}
    assert rows[DONE]['bytes_before'] is None and rows[DONE]['bytes_after'] == 23
    summary = make_stats.summarize(list(rows.values()))
    assert summary['papers_with_size_before'] == 0 and summary['size_reduction_pct'] is None
