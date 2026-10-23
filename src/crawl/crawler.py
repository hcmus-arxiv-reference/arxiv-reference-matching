"""Sequential arXiv crawler. Sources: info.arxiv.org/help/api/user-manual.html
and info.arxiv.org/help/api/tou.html. Working JSON is not a published schema.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import time
import tempfile
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

NS = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom'}
LIMIT = 256 * 1024 * 1024
LOG = logging.getLogger(__name__)


def save_json(path, value):
    """Atomically replace a checkpoint after its files have been written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


class Client:
    """One connection; bounded retries with pacing and Retry-After support."""
    def __init__(self, user_agent, attempts=4, *, origin='https://export.arxiv.org', interval=3.1, headers=None):
        self.user_agent, self.attempts = user_agent, attempts
        self.origin, self.interval = origin, interval
        self.headers = {'User-Agent': user_agent, **(headers or {})}
        self.last = None
        self.requests = 0
        self.http_seconds = 0.0
        self.download_bytes = 0

    def get(self, url):
        return self._request(url)

    def download(self, url, path):
        """Stream to a temporary file; each retry truncates the partial body."""
        return self._request(url, Path(path))

    def _request(self, url, path=None):
        if not url.startswith(self.origin + '/'):
            raise ValueError('Unexpected request destination')
        for attempt in range(self.attempts):
            if self.last is not None:
                time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            self.requests += 1
            LOG.info('GET %s (attempt %d/%d)', url, attempt + 1, self.attempts)
            started = time.monotonic()
            try:
                with urlopen(Request(url, headers=self.headers), timeout=90) as response:
                    if not response.url.startswith(self.origin + '/'):
                        raise ValueError('Unexpected redirect destination')
                    if path is None:
                        data = response.read(LIMIT + 1)
                        if len(data) > LIMIT:
                            raise ValueError('Response exceeds safety limit')
                        return data
                    size = 0
                    reported = time.monotonic()
                    with path.open('wb') as target:
                        while chunk := response.read(1024 * 1024):
                            size += len(chunk)
                            if size > LIMIT:
                                raise ValueError('Response exceeds safety limit')
                            target.write(chunk)
                            if time.monotonic() - reported >= 5:
                                LOG.info('Downloaded %.1f MiB', size / 1024**2)
                                reported = time.monotonic()
                    self.download_bytes += size
                    LOG.info('Download complete: %.1f MiB', size / 1024**2)
                    return size
            except (HTTPError, URLError, TimeoutError, OSError) as error:
                delay = min(60, 3 * 2 ** attempt)
                if isinstance(error, HTTPError):
                    if error.code not in (408, 429, 500, 502, 503, 504):
                        raise
                    retry = error.headers.get('Retry-After')
                    if retry:
                        try:
                            delay = max(delay, float(retry))
                        except ValueError:
                            try:
                                delay = max(delay, (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
                            except (TypeError, ValueError, OverflowError):
                                LOG.warning('Invalid Retry-After; using exponential backoff')
                if attempt + 1 == self.attempts:
                    raise
                LOG.warning('Request failed (%s %s); retry in %.1fs', type(error).__name__, getattr(error, 'code', ''), delay)
                time.sleep(delay)
            finally:
                self.http_seconds += time.monotonic() - started


def parse_metadata(data, expected):
    """Read a single Atom entry and verify its versioned identity."""
    root = ET.fromstring(data)
    entries = root.findall('a:entry', NS)
    if len(entries) != 1:
        raise ValueError('Expected exactly one metadata entry')
    entry = entries[0]
    identifier = entry.findtext('a:id', '', NS).split('/abs/')[-1]
    match = re.fullmatch(re.escape(expected) + r'v([1-9]\d*)', identifier)
    if not match:
        raise ValueError('Missing or mismatched versioned arXiv ID')
    def text(name):
        value = entry.findtext(name, None, NS)
        return ' '.join(value.split()) if value else None
    return dict(arxiv_id=expected, version=int(match[1]), title=text('a:title'),
                authors=[e.text for e in entry.findall('a:author/a:name', NS)],
                submission_date=text('a:published'), updated=text('a:updated'),
                venue=text('x:journal_ref'), abstract=text('a:summary'))


def unpack_file(path):
    """Read archive from disk; skip image bodies without holding them in RAM."""
    files = {}
    try:
        archive = tarfile.open(path, mode='r:*')
    except tarfile.ReadError:
        return unpack_sources(Path(path).read_bytes())
    total = 0
    with archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or '\\' in member.name or ':' in member.name:
                raise ValueError('Unsafe archive path')
            if not member.isfile() or name.suffix.lower() not in ('.tex', '.bib'):
                continue
            total += member.size
            if total > LIMIT:
                raise ValueError('Extracted sources exceed safety limit')
            key = str(name)
            if key in files:
                raise ValueError('Duplicate archive path')
            files[key] = archive.extractfile(member).read()
    return files


def unpack_sources(data):
    """Return only regular TeX/Bib files; reject traversal and unknown payloads.

    A valid tar without TeX, or a PDF, is a confirmed empty Version. HTML,
    corrupt gzip and unrecognized text are errors, never successful empties.
    """
    if data.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as source:
            data = source.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError('Expanded source exceeds safety limit')
    files = {}
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode='r:')
    except tarfile.ReadError:
        if data.lstrip().startswith(b'%PDF-'):
            return {}
        if b'\\documentclass' in data or b'\\documentstyle' in data or b'\\begin{document}' in data:
            return {'main.tex': data}
        raise ValueError('Unrecognized source (possibly HTML or invalid archive)')
    total = 0
    with archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or '\\' in member.name or ':' in member.name:
                raise ValueError('Unsafe archive path')
            if not member.isfile() or name.suffix.lower() not in ('.tex', '.bib'):
                continue
            total += member.size
            if total > LIMIT:
                raise ValueError('Extracted sources exceed safety limit')
            key = str(name)
            if key in files:
                raise ValueError('Duplicate archive path')
            files[key] = archive.extractfile(member).read()
    return files


class Crawler:
    """Cache metadata and checkpoint each Version with file integrity hashes."""
    def __init__(self, root, client, store=None):
        self.root, self.client = Path(root), client
        self.store = store

    def cached_metadata(self, identifier):
        if self.store is not None:
            return self.store.get_metadata(identifier)
        path = self.metadata_path(identifier)
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def cache_metadata(self, identifier, value):
        if self.store is not None:
            self.store.put_metadata(identifier, value)
        else:
            save_json(self.metadata_path(identifier), value)

    def prefetch(self, identifiers, batch_size=25):
        """Batch uncached latest/older metadata; never cache missing API entries."""
        pending = [identifier for identifier in identifiers if self.cached_metadata(identifier) is None]
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset:offset + batch_size]
            try:
                data = self.client.get('https://export.arxiv.org/api/query?' + urlencode(
                    {'id_list': ','.join(batch), 'max_results': len(batch)}))
                root = ET.fromstring(data)
                for entry in root.findall('a:entry', NS):
                    versioned = entry.findtext('a:id', '', NS).split('/abs/')[-1]
                    base = re.sub(r'v\d+$', '', versioned)
                    requested = versioned if versioned in batch else base
                    if requested not in batch:
                        continue
                    feed = ET.Element('feed')
                    feed.append(entry)
                    value = parse_metadata(ET.tostring(feed), base)
                    self.cache_metadata(requested, value)
            except (OSError, ValueError, ET.ParseError):
                LOG.exception('Metadata batch failed; individual lookup remains available')

    def metadata_path(self, identifier):
        base = re.sub(r'v\d+$', '', identifier)
        return self.root / base / 'metadata' / (identifier + '.json')

    def metadata(self, identifier, base):
        cached = self.cached_metadata(identifier)
        if cached is not None:
            return cached
        original = re.sub(r'v\d+$', '', identifier)
        data = self.client.get('https://export.arxiv.org/api/query?' + urlencode({'id_list': identifier}))
        value = parse_metadata(data, original)
        suffix = re.search(r'v(\d+)$', identifier)
        if suffix and value['version'] != int(suffix[1]):
            raise ValueError('API returned a different Version')
        self.cache_metadata(identifier, value)
        return value

    def publication(self, identifier):
        if not re.fullmatch(r'\d{4}\.\d{5}', identifier):
            raise ValueError('Expected modern base arXiv ID')
        base = self.root / identifier
        latest = self.metadata(identifier, base / 'metadata')
        # Discovery already returned the latest Version's complete metadata.
        latest_key = f"{identifier}v{latest['version']}"
        if self.cached_metadata(latest_key) is None:
            self.cache_metadata(latest_key, latest)
        results = []
        for version in range(1, latest['version'] + 1):
            folder = base / f'v{version}'
            checkpoint = folder / 'checkpoint.json'
            previous = self.store.get_version(identifier, version) if self.store else (
                json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else None)
            if previous is not None:
                if previous['status'] in ('success', 'empty') and all(
                    (folder / name).is_file() and hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
                    for name, digest in previous['files'].items()
                ):
                    results.append(previous)
                    LOG.info('%sv%d resume: %s', identifier, version, previous['status'])
                    continue
            record = dict(arxiv_id=identifier, version=version, status='error', files={})
            try:
                metadata = self.metadata(f'{identifier}v{version}', base / 'metadata')
                folder.mkdir(parents=True, exist_ok=True)
                if self.store is None:
                    save_json(folder / 'metadata.json', metadata)
                started = time.monotonic()
                with tempfile.TemporaryDirectory(dir=folder) as temporary:
                    archive_path = Path(temporary) / 'source.download'
                    size = self.client.download(f'https://export.arxiv.org/src/{identifier}v{version}', archive_path)
                    record['download_seconds'] = time.monotonic() - started
                    started = time.monotonic()
                    files = unpack_file(archive_path)
                for name, content in files.items():
                    target = folder / 'source' / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                    record['files']['source/' + name] = hashlib.sha256(content).hexdigest()
                record['status'] = 'success' if any(n.lower().endswith('.tex') for n in files) else 'empty'
                record['extract_seconds'] = time.monotonic() - started
                record['download_bytes'] = size
                record['kept_bytes'] = sum(map(len, files.values()))
            except (OSError, ValueError, ET.ParseError, EOFError, tarfile.TarError) as error:
                record['error'] = f'{type(error).__name__}: {error}'
            if self.store is not None:
                self.store.put_version(record)
            else:
                save_json(checkpoint, record)
            results.append(record)
        return results
