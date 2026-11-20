"""Crawl tasks with per-Version failures, validated caches and resumable exports."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Iterator, Sequence

from filelock import FileLock
from src.common.config import ArxivRange
from src.common.corpus import PublicationState
from .discovery import ArxivDiscovery
from .corpus import CorpusReader
from .export import PublicationBundle, export_publications
from .manifest import Manifest, TaskRecord
from src.common.references import CitationList
from .http_client import RETRY_STATUSES, HttpStatusError
from .semantic_scholar import BATCH_ROW_LIMIT, SemanticScholarClient
from .source import ArxivSourceDownloader
from .storage import require_id
from src.common.json_io import write_json
from src.common.metrics import append_jsonl


class CrawlPipeline:
    """One writer per data directory. Source failures never overwrite discovery.

    Default Stage implementations. Discovery theo lô when the discovery object
    has ``prefetch`` (``BatchedDiscovery``, contributed by Liễu, langtucod0n).
    References theo lô when the S2 client has ``references_batch``: one request
    returns the S2 citation lists of the next Publications, so a Range needs
    about ``n / batch_size`` S2 requests instead of one or more per Publication
    (see ``_prefetch_references``). A Publication the batch did not cover is
    fetched alone in one worker thread while the main thread downloads its
    sources (Liễu's overlapped References). Cache checks, Manifest and cache
    writes stay on the main thread, and a failed S2 request never marks a
    Publication done.

    Locks: ``exclusive()`` holds ``.pipeline.lock`` for a whole run (one Runner
    per data directory). ``corpus_lock()`` holds ``.crawl.lock`` while caches,
    the Manifest or tables change; it is one reentrant instance, so callers may
    nest it around ``crawl_ids``/``export``. The Manifest is reloaded from disk
    when either lock is first acquired, never inside a nested acquisition.

    Timing: every Publication visited by ``crawl_ids`` appends one line to
    ``manifests/timings.jsonl`` (wall seconds for that Publication and the part
    spent in Discovery, including the batch it triggered). The file is a
    measurement log for the M1 report, not part of the Manifest; a Publication
    interrupted and crawled again has one line per visit.
    """
    engine = "main"
    def __init__(self, discovery: ArxivDiscovery, sources: ArxivSourceDownloader,
                 data_dir: str | Path = "data", references: SemanticScholarClient | None = None) -> None:
        self.discovery, self.sources, self.references = discovery, sources, references
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # One instance per path: two FileLock objects on the same file in one
        # process would block each other instead of nesting.
        self._pipeline_lock = FileLock(str(self.data_dir / ".pipeline.lock"), timeout=0)
        self._corpus_lock = FileLock(str(self.data_dir / ".crawl.lock"), timeout=0)
        self._corpus_depth = 0
        self.timings_path = self.data_dir / "manifests" / "timings.jsonl"
        self.clock = time.monotonic
        # IDs already sent in a Discovery batch by this Engine; see _prefetch_window.
        self._batched: set[str] = set()
        # References theo lô: IDs already sent in a batch, and results not yet consumed
        # (rows, None = unknown to S2, or the error that failed the whole batch).
        self._refs_batched: set[str] = set()
        self._refs_ready: dict[str, list[dict] | Exception | None] = {}
        self.manifest: Manifest | None = None
        # Loading may repair a torn final line, so it happens under the lock.
        with self.corpus_lock():
            pass

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold the run lock; fail at once if another run uses this data directory."""
        with self._pipeline_lock:
            with self.corpus_lock():  # reload under the write lock, then release it
                pass
            yield

    @contextmanager
    def corpus_lock(self) -> Iterator[None]:
        """Hold the corpus write lock; reload the Manifest on the outermost entry."""
        with self._corpus_lock:
            self._corpus_depth += 1
            try:
                if self._corpus_depth == 1:
                    path = self.manifest.path if self.manifest else self.data_dir / "manifests" / "crawl.jsonl"
                    self.manifest = Manifest(path)
                yield
            finally:
                self._corpus_depth -= 1

    def status(self, arxiv_id: str) -> PublicationState:
        """Verified state of one Publication; reads files and the Manifest only."""
        return self.corpus.status(arxiv_id)

    def issues(self, arxiv_id: str) -> list[dict]:
        """Unfinished tasks of one Publication, without URLs, headers or payloads."""
        return [
            {"kind": record.kind, "version": record.version, "status": record.status,
             "http_status": record.http_status, "error_reason": record.error_reason}
            for record in self.manifest.records_for(arxiv_id)
            if record.status not in {"success", "non_tex"}
        ]

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
        """IDs per Discovery batch; 1 when the discovery object has no batches."""
        size = getattr(self.discovery, "batch_size", 0)
        return size if isinstance(size, int) and size > 0 else 1

    def _metadata_verified(self, identifier) -> bool:
        try:
            self.corpus.load_publication(identifier)
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _prefetch_window(self, ids, upcoming) -> None:
        """Batch-discover ``ids`` plus the next IDs the caller will crawl.

        A batch starts only when one of ``ids`` was never batched and lacks
        verified metadata, and is filled positionally from ``upcoming`` up to
        ``prefetch_size``. Batch results stay in memory until each Publication
        is crawled, so "already batched" is remembered here; otherwise every
        later ID would look missing and trigger a one-ID request. Walking a
        fresh Range one ID at a time therefore costs about ``ceil(n / size)``
        batch requests; a resumed Range whose metadata is cached costs none.
        An ID whose discovery fails is forgotten, so the next pass batches it again.
        """
        if all(i in self._batched or self._metadata_verified(i) for i in ids):
            return
        extra = [i for i in upcoming if i not in ids][:max(0, self.prefetch_size - len(ids))]
        window = [*ids, *extra]
        self.prefetch(window)
        self._batched.update(window)

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

    def _references_verified(self, identifier) -> bool:
        try:
            self.corpus.load_references(identifier)
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _prefetch_references(self, ids, upcoming) -> None:
        """Batch-fetch S2 citation lists of ``ids`` plus the next IDs the caller will crawl.

        Mirrors ``_prefetch_window``: a batch starts only when one of ``ids`` was
        never batched and lacks a verified references cache, and is filled
        positionally from ``upcoming`` up to the client's ``batch_size``. Results
        stay in memory until each Publication is crawled; nothing is written here.

        A batch that fails with 429/5xx is kept as that error for every ID in
        it: asking for the same Publications one by one would hit the same
        limit and stall the arXiv downloads behind S2's backoff. Those IDs are
        batched again on the next pass. Any other failure (unexpected payload,
        4xx) falls back to one request per Publication.
        """
        # Looked up on the class so a client without the method, or a test double, opts out.
        if self.references is None or not callable(getattr(type(self.references), "references_batch", None)):
            return
        size = getattr(self.references, "batch_size", 0)
        if not isinstance(size, int) or size < 1:
            return
        if all(i in self._refs_batched or self._references_verified(i) for i in ids):
            return
        candidates = [*ids, *[i for i in upcoming if i not in ids]][:max(size, len(ids))]
        window = [i for i in candidates if i not in self._refs_batched and not self._references_verified(i)]
        for start in range(0, len(window), size):
            chunk = window[start:start + size]
            try:
                self._refs_ready.update(self.references.references_batch(chunk))
            except Exception as error:
                throttled = isinstance(error, HttpStatusError) and error.status in RETRY_STATUSES
                print(json.dumps({"event": "batch_references_failed" if throttled else "batch_references_fallback",
                                  "error_type": type(error).__name__,
                                  "http_status": getattr(error, "status", None), "size": len(chunk)}), flush=True)
                if throttled:
                    self._refs_ready.update(dict.fromkeys(chunk, error))
            self._refs_batched.update(chunk)

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
            if arxiv_id in self._refs_ready:
                return self._batched_references(pool, arxiv_id, self._refs_ready.pop(arxiv_id))
        return pool.submit(self._fetch_references, arxiv_id)

    def _batched_references(self, pool, arxiv_id, ready):
        """Future for one Publication of a finished batch."""
        future = Future()
        if isinstance(ready, Exception):
            self._refs_batched.discard(arxiv_id)   # batch it again on the next pass
            future.set_exception(ready)
        elif ready is None:
            # Same record as the single-Publication endpoint answering 404.
            future.set_exception(HttpStatusError(404, "Semantic Scholar"))
        elif len(ready) >= BATCH_ROW_LIMIT:
            return pool.submit(self._fetch_references, arxiv_id)   # possibly truncated: paginate
        else:
            try:
                future.set_result(CitationList.from_raw(arxiv_id, ready))
            except ValueError as error:
                future.set_exception(error)
        return future

    def _fetch_references(self, arxiv_id):
        return CitationList.from_raw(arxiv_id, self.references.references(arxiv_id))

    def crawl_ids(self, ids: list[str], *, refresh: bool = False,
                  upcoming: Sequence[str] = ()) -> dict[str, int]:
        """Cache metadata until refresh=True; validate source files on every run.

        ``upcoming`` lists IDs the caller will crawl next, in order. The Engine
        may discover them early in the same batch; it never downloads their
        sources here. ``refresh=True`` ignores ``upcoming``.
        """
        ids = list(dict.fromkeys(require_id(i) for i in ids))
        upcoming = [require_id(i) for i in upcoming]
        with self.corpus_lock():
            return self._crawl(ids, refresh=refresh, upcoming=upcoming)

    def _crawl(self, ids, *, refresh, upcoming=()):
        stats = {"success": 0, "non_tex": 0, "unavailable": 0, "errors": 0, "skipped": 0,
                 "references_success": 0}
        batch_started = self.clock()
        if refresh and hasattr(self.discovery, "prefetch"):
            self.discovery.prefetch(ids)
        elif not refresh:
            self._prefetch_window(ids, upcoming)
        # The batch serves several IDs but is charged to the first one, the
        # Publication that triggered it, so per-Publication times sum to wall time.
        batch_seconds = self.clock() - batch_started
        # The References batch is timed apart from Discovery (the report states
        # Discovery time on its own) and charged to the same first Publication.
        refs_started = self.clock()
        if not refresh:
            self._prefetch_references(ids, upcoming)
        refs_seconds = self.clock() - refs_started
        with ThreadPoolExecutor(max_workers=1) as pool:
            for index, arxiv_id in enumerate(ids):
                charged = batch_seconds if index == 0 else 0.0
                refs_charged = refs_seconds if index == 0 else 0.0
                timing = {"arxiv_id": arxiv_id,
                          "started_at": datetime.now(timezone.utc).isoformat(),
                          "discovery_seconds": charged, "batch_discovery_seconds": charged,
                          "batch_references_seconds": refs_charged}
                started = self.clock()
                try:
                    self._crawl_publication(pool, arxiv_id, refresh, stats, timing)
                finally:
                    timing["seconds"] = charged + refs_charged + self.clock() - started
                    self._log_timing(timing)
        return stats

    def _crawl_publication(self, pool, arxiv_id, refresh, stats, timing):
        """Discovery, Source fetch and References of one Publication; updates ``stats``."""
        started = self.clock()
        try:
            publication = self._discover_publication(arxiv_id, refresh=refresh)
        except Exception as error:
            self._batched.discard(arxiv_id)
            self._failure(arxiv_id, None, "discovery", error)
            stats["errors"] += 1
            return
        finally:
            timing["discovery_seconds"] += self.clock() - started
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
            return
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

    def _log_timing(self, timing):
        """Append one visit of one Publication to ``manifests/timings.jsonl``."""
        append_jsonl(self.timings_path, {k: round(v, 3) if isinstance(v, float) else v
                                         for k, v in timing.items()})

    def crawl_range(self, arxiv_range: ArxivRange, *, refresh: bool = False) -> dict[str, int]:
        return self.crawl_ids(list(arxiv_range.ids()), refresh=refresh)

    def export(self, ids: list[str], *, require_references: bool = True) -> tuple[list[PublicationBundle], dict[str, Path]]:
        """Export the requested batch under the corpus lock.

        Callers that must keep the lock after export (for example to upload the
        same tables) wrap this call in ``corpus_lock()``.
        """
        with self.corpus_lock():
            return export_publications(self.corpus, self.sources.root, ids,
                                       require_references=require_references)
