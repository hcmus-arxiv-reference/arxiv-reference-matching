"""SQL resume, paginated reference durability, migration and backup tests."""
import json
import sqlite3
import zipfile
import pytest
from src.crawl.store import Store
from src.crawl.crawler import Crawler, save_json
from src.crawl.semantic import crawl_references
from src.crawl.pipeline import snapshot
from test_crawler import Fake


def test_sqlite_source_resume(tmp_path):
    store = Store(tmp_path / 'crawl.sqlite')
    client = Fake()
    crawler = Crawler(tmp_path, client, store)
    assert all(r['status'] == 'success' for r in crawler.publication('2412.08848'))
    before = len(client.calls)
    crawler.publication('2412.08848')
    assert len(client.calls) == before
    assert not list(tmp_path.glob('*/v*/checkpoint.json'))
    store.close()
    archive = tmp_path / 'snapshot.zip'
    snapshot(tmp_path, archive)
    with zipfile.ZipFile(archive) as z:
        assert 'crawl.sqlite' in z.namelist()
        assert '2412.08848/v1/source/main.tex' in z.namelist()


def test_legacy_import_does_not_overwrite(tmp_path):
    legacy = Crawler(tmp_path, Fake())
    legacy.publication('2412.08848')
    store = Store(tmp_path / 'crawl.sqlite')
    store.import_legacy(tmp_path)
    value = store.get_metadata('2412.08848')
    value['title'] = 'SQL is authoritative'
    store.put_metadata('2412.08848', value)
    store.import_legacy(tmp_path)
    assert store.get_metadata('2412.08848')['title'] == 'SQL is authoritative'
    client = Fake()
    Crawler(tmp_path, client, store).publication('2412.08848')
    assert client.calls == []
    store.close()


def test_s2_partial_resume_and_null_dates(tmp_path):
    store = Store(tmp_path / 'crawl.sqlite')
    class S2:
        def __init__(self):
            self.calls = []
            self.fail = True
        def get(self, url):
            self.calls.append(url)
            if 'offset=1' in url:
                if self.fail:
                    raise TimeoutError('network')
                return json.dumps({'data': [{'citedPaper': None}]}).encode()
            return json.dumps({'next': 1, 'data': [{'citedPaper': {'paperId': 's2', 'externalIds': {'ArXiv': 'hep-th/9901001'}, 'title': 'T', 'authors': [{'name': 'A'}], 'publicationDate': '2000-01-01'}}]}).encode()
    client = S2()
    with pytest.raises(TimeoutError):
        crawl_references(store, client, '2412.08848')
    job = store.db.execute('SELECT * FROM reference_jobs').fetchone()
    assert job['status'] == 'error' and job['next_offset'] == 1
    client.fail = False
    assert crawl_references(store, client, '2412.08848') == 'complete'
    assert 'offset=1' in client.calls[-1]
    assert store.db.execute('SELECT COUNT(*) FROM s2_references').fetchone()[0] == 2
    before = len(client.calls)
    crawl_references(store, client, '2412.08848')
    assert len(client.calls) == before
    assert store.db.execute('SELECT ref_arxiv_id FROM s2_references WHERE position=0').fetchone()[0] == 'hep-th/9901001'
    store.close()


def test_invalid_pagination_not_committed(tmp_path):
    class Bad:
        def get(self, url):
            return b'{"data": [], "next": 0}'
    store = Store(tmp_path / 'crawl.sqlite')
    with pytest.raises(ValueError):
        crawl_references(store, Bad(), '2412.08848')
    assert store.db.execute('SELECT status FROM reference_jobs').fetchone()[0] == 'error'
    store.close()
