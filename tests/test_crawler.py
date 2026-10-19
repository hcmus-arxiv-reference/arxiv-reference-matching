"""Crawler behavior tests using synthetic archives and an offline client."""
import gzip
import io
import tarfile
from urllib.error import HTTPError
import pytest
from src.crawl.crawler import Client, Crawler, unpack_sources, parse_metadata


def archive(items):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as tar:
        for name, content in items.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            tar.addfile(entry, io.BytesIO(content))
    return output.getvalue()


def test_extract_filter_and_original_content():
    content = b'\\documentclass{article}\\includegraphics{fig.png}'
    assert unpack_sources(archive({'sub/main.tex': content, 'refs.bib': b'@book{}', 'fig.png': b'image'})) == {
        'sub/main.tex': content, 'refs.bib': b'@book{}'}


def test_single_gzip_and_empty():
    assert unpack_sources(gzip.compress(b'\\documentclass{article}')) == {'main.tex': b'\\documentclass{article}'}
    assert unpack_sources(b'%PDF-1.5') == {}
    assert unpack_sources(archive({'image.png': b'png'})) == {}


@pytest.mark.parametrize('data', [b'<html>blocked</html>', b'unknown', b'\x1f\x8bBAD'])
def test_bad_payload_is_not_empty(data):
    with pytest.raises((ValueError, OSError, EOFError)):
        unpack_sources(data)


def test_traversal():
    with pytest.raises(ValueError, match='Unsafe'):
        unpack_sources(archive({'../escape.tex': b'bad'}))


class Fake:
    def __init__(self):
        self.calls = []
    def download(self, url, path):
        data = self.get(url)
        path.write_bytes(data)
        return len(data)
    def get(self, url):
        self.calls.append(url)
        if '/src/' in url:
            return archive({'main.tex': b'\\documentclass{article}'})
        version = 1 if 'v1' in url else 2
        return f'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>http://arxiv.org/abs/2412.08848v{version}</id><title> Test </title>
        <author><name>A</name></author><published>2024-12-01T00:00:00Z</published>
        <updated>2025-01-01T00:00:00Z</updated></entry></feed>'''.encode()


def test_versions_resume_and_corruption(tmp_path):
    client = Fake()
    crawler = Crawler(tmp_path, client)
    assert len(crawler.publication('2412.08848')) == 2
    count = len(client.calls)
    crawler.publication('2412.08848')
    assert len(client.calls) == count
    (tmp_path / '2412.08848/v1/source/main.tex').write_bytes(b'corrupted')
    crawler.publication('2412.08848')
    assert len(client.calls) == count + 1


def test_metadata_rejects_wrong_id():
    with pytest.raises(ValueError):
        parse_metadata(Fake().get('metadata'), '2412.09999')


def test_retry_and_pacing(monkeypatch):
    import src.crawl.crawler as module
    clock = [0.0]
    sleeps = []
    def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay
    monkeypatch.setattr(module.time, 'sleep', sleep)
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(clock[0])
        raise HTTPError('url', 429, 'rate limit', {'Retry-After': '5'}, None)
    monkeypatch.setattr(module, 'urlopen', fail)
    with pytest.raises(HTTPError):
        Client('test', attempts=3).get('https://export.arxiv.org/test')
    assert len(attempts) == 3
    assert all(b - a >= 3 for a, b in zip(attempts, attempts[1:]))
    assert 5 in sleeps


def test_batch_and_latest_reuse(tmp_path):
    """One discovery batch replaces a latest-version lookup; order is irrelevant."""
    from urllib.parse import urlparse, parse_qs
    class BatchFake(Fake):
        def get(self, url):
            if '/src/' in url:
                return super().get(url)
            self.calls.append(url)
            ids = parse_qs(urlparse(url).query)['id_list'][0].split(',')
            entries = []
            for identifier in reversed(ids):
                versioned = identifier if 'v' in identifier else identifier + 'v1'
                entries.append(f'<entry><id>http://arxiv.org/abs/{versioned}</id><title>T</title></entry>')
            return ('<feed xmlns="http://www.w3.org/2005/Atom">' + ''.join(entries) + '</feed>').encode()
    client = BatchFake()
    crawler = Crawler(tmp_path, client)
    ids = ['2412.08848', '2412.08849']
    crawler.prefetch(ids)
    for identifier in ids:
        assert crawler.publication(identifier)[0]['status'] == 'success'
    assert len(client.calls) == 3  # one metadata query, two source downloads
    crawler.prefetch(ids)
    assert len(client.calls) == 3


def test_disk_archive(tmp_path):
    from src.crawl.crawler import unpack_file
    path = tmp_path / 'archive'
    path.write_bytes(archive({'a/main.tex': b'text', 'figure.png': b'png'}))
    assert unpack_file(path) == {'a/main.tex': b'text'}
    path.write_bytes(archive({'../bad.tex': b'bad'}))
    with pytest.raises(ValueError):
        unpack_file(path)


def test_stream_download_retries_partial_body(tmp_path, monkeypatch):
    import src.crawl.crawler as module
    class Response:
        url = 'https://export.arxiv.org/src/test'
        def __init__(self, fail):
            self.fail = fail
            self.reads = 0
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            assert size == 1024 * 1024
            self.reads += 1
            if self.reads == 1:
                return b'partial' if self.fail else b'complete'
            if self.fail:
                raise TimeoutError('interrupted body')
            return b''
    responses = iter([Response(True), Response(False)])
    monkeypatch.setattr(module, 'urlopen', lambda *a, **k: next(responses))
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: None)
    path = tmp_path / 'download'
    client = Client('test')
    assert client.download(Response.url, path) == 8
    assert path.read_bytes() == b'complete'
    assert client.requests == 2
