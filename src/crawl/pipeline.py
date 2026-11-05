"""Crawl tasks with per-Version failures, validated caches and resumable exports."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from filelock import FileLock
from src.common.config import ArxivRange
from .discovery import ArxivDiscovery
from .corpus import CorpusReader
from .export import PublicationBundle, export_publications
from .manifest import Manifest, TaskRecord
from src.common.references import CitationList
from .semantic_scholar import SemanticScholarClient
from .source import ArxivSourceDownloader
from .storage import require_id
from src.common.json_io import write_json


class CrawlPipeline:
    """One writer per data directory. Source failures never overwrite discovery.

    Default Stage implementations, both contributed by Liễu (langtucod0n):
    batched Discovery when the discovery object has ``prefetch``
    (``BatchedDiscovery``), and References fetched in one worker thread while
    the main thread downloads that Publication's sources. Only the S2 network
    call runs in the worker; cache checks, Manifest and cache writes stay on
    the main thread, and a failed S2 request never marks a Publication done.
    """
    engine = "main"
    def __init__(self, discovery: ArxivDiscovery, sources: ArxivSourceDownloader,
                 data_dir: str | Path = "data", references: SemanticScholarClient | None = None) -> None:
        self.discovery, self.sources, self.references = discovery, sources, references
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.data_dir / ".crawl.lock"), timeout=0):
            self.manifest = Manifest(self.data_dir / "manifests" / "crawl.jsonl")

    def _metadata_path(self, arxiv_id: str) -> Path:
        return self.corpus.metadata_path(arxiv_id)

    def _references_path(self, arxiv_id: str) -> Path:
        return self.corpus.references_path(arxiv_id)

    def _record(self, arxiv_id, version, kind, status, *, attempted=True, **fields):
        prior = self.manifest.get(arxiv_id, version, kind)
        attempts = (prior.attempts if prior else 0) + int(attempted)
        self.manifest.upsert(TaskRecord(arxiv_id, version, kind, status, attempts,
                                       updated_at=datetime.now(timezone.utc).isoformat(), **fields))

    def _failure(self, arxiv_id, version, kind, error):
        # Exception messages from remote SDKs may include response bodies/headers.
        self._record(arxiv_id, version, kind, "error",
                     http_status=getattr(error, "status", None), error_reason=type(error).__name__)

    @property
    def corpus(self) -> CorpusReader:
        """Use the current Manifest, including after a runner reloads it."""
        # Source fetch fakes may lack ``root``; the reader then uses data_dir/raw.
        return CorpusReader(self.data_dir, self.manifest, getattr(self.sources, "root", None))

    # Compatibility for earlier callers; new code uses the public reader.
    def _load_publication(self, arxiv_id):
        return self.corpus.load_publication(arxiv_id)

    def _load_references(self, arxiv_id):
        return self.corpus.load_references(arxiv_id)

    _validate_publication = staticmethod(CorpusReader.validate_publication)

    def _discover_publication(self, arxiv_id, *, refresh=False):
        """Resolve and persist metadata from the verified cache or Discovery."""
        try:
            if refresh:
                raise ValueError("refresh")
            return self.corpus.load_publication(arxiv_id)
        except (OSError, ValueError, KeyError, TypeError):
            publication = self.discovery.discover(arxiv_id)
            self._validate_publication(publication, arxiv_id)
            path = self._metadata_path(arxiv_id)
            write_json(path, {"format": 1, "publication": asdict(publication)})
            self._record(arxiv_id, None, "discovery", "success",
                         checksum=hashlib.sha256(path.read_bytes()).hexdigest())
            return publication

    @property
    def prefetch_size(self) -> int:
        """IDs per prefetch call; the Runner uses it to schedule batches."""
        size = getattr(self.discovery, "batch_size", 0)
        return size if isinstance(size, int) and size > 0 else 1

    def prefetch(self, identifiers) -> None:
        """Batch-discover Publications whose metadata cache is not verified."""
        batch = getattr(self.discovery, "prefetch", None)
        if batch is None:
            return
        missing = []
        for identifier in identifiers:
            try:
                self.corpus.load_publication(identifier)
            except (OSError, ValueError, KeyError, TypeError):
                missing.append(identifier)
        batch(missing)

    def _submit_references(self, pool, arxiv_id, refresh):
        """Future of new S2 rows (None result for a verified cache); None without S2."""
        if self.references is None:
            return None
        if not refresh:
            try:
                self.corpus.load_references(arxiv_id)
                cached = Future()
                cached.set_result(None)
                return cached
            except (OSError, ValueError, TypeError, KeyError):
                pass
        return pool.submit(self._fetch_references, arxiv_id)

    def _fetch_references(self, arxiv_id):
        return CitationList.from_raw(arxiv_id, self.references.references(arxiv_id))

    def crawl_ids(self, ids: list[str], *, refresh: bool = False) -> dict[str, int]:
        """Cache metadata until refresh=True; validate source files on every run."""
        ids = list(dict.fromkeys(require_id(i) for i in ids))
        with FileLock(str(self.data_dir / ".crawl.lock"), timeout=0):
            self.manifest = Manifest(self.manifest.path)
            return self._crawl(ids, refresh=refresh)

    def _crawl(self, ids, *, refresh):
        stats = {"success": 0, "non_tex": 0, "unavailable": 0, "errors": 0, "skipped": 0,
                 "references_success": 0}
        if refresh and hasattr(self.discovery, "prefetch"):
            self.discovery.prefetch(ids)
        elif not refresh:
            self.prefetch(ids)
        with ThreadPoolExecutor(max_workers=1) as pool:
            for arxiv_id in ids:
                try:
                    publication = self._discover_publication(arxiv_id, refresh=refresh)
                except Exception as error:
                    self._failure(arxiv_id, None, "discovery", error)
                    stats["errors"] += 1
                    continue
                # One S2 task overlaps this Publication's serial arXiv downloads.
                refs = self._submit_references(pool, arxiv_id, refresh)
                for version in range(1, publication.versions + 1):
                    try:
                        result = self.sources.download(arxiv_id, version)
                        self._record(arxiv_id, version, "source", result.status,
                                     attempted=not result.cached, http_status=result.http_status,
                                     local_path=str(result.path), checksum=result.checksum)
                        stats["skipped" if result.cached else result.status] += 1
                    except Exception as error:
                        self._failure(arxiv_id, version, "source", error)
                        stats["errors"] += 1
                if refs is None:
                    continue
                try:
                    citations = refs.result()
                    if citations is not None:
                        path = self._references_path(arxiv_id)
                        write_json(path, {"format": 1, "arxiv_id": arxiv_id, "rows": list(citations.raw)})
                        self._record(arxiv_id, None, "references", "success", local_path=str(path),
                                     checksum=hashlib.sha256(path.read_bytes()).hexdigest())
                    stats["references_success"] += 1
                except Exception as error:
                    self._failure(arxiv_id, None, "references", error)
                    stats["errors"] += 1
        return stats

    def crawl_range(self, arxiv_range: ArxivRange, *, refresh: bool = False) -> dict[str, int]:
        return self.crawl_ids(list(arxiv_range.ids()), refresh=refresh)

    def export(self, ids: list[str], *, require_references: bool = True) -> tuple[list[PublicationBundle], dict[str, Path]]:
        """Export the requested batch while the caller holds the corpus lock."""
        return export_publications(self.corpus, self.sources.root, ids,
                                   require_references=require_references)
