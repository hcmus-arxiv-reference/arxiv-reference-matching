"""Crawl tasks with per-Version failures, validated caches and resumable exports."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
from typing import Iterator, Sequence

from filelock import FileLock
from src.common.config import ArxivRange
from src.common.corpus import SOURCE_OK, PublicationState
from .discovery import ArxivDiscovery
from .corpus import CorpusReader
from .export import PublicationBundle, export_publications
from .manifest import Manifest, TaskRecord
from src.common.references import S2_NOT_FOUND, CitationList
from .http_client import RETRY_STATUSES, HttpStatusError
from .semantic_scholar import BATCH_ROW_LIMIT, SemanticScholarClient
from .source import ArxivSourceDownloader
from .storage import require_id
from src.common.json_io import write_json
from src.common.metrics import append_jsonl

# References theo lô (see CrawlPipeline): how long the arXiv thread may wait for a
# batch after a Publication's own downloads before leaving it for later, how long
# the S2 thread keeps retrying a throttled batch, and its pause between retries.
REFERENCES_WAIT = 10.0
REFERENCES_PATIENCE = 1800.0
THROTTLE_PAUSE = 60.0


class _Batched:
    """A Publication whose citation list the S2 thread is fetching (Future of a CitationList)."""
    __slots__ = ("batch",)

    def __init__(self, batch: Future) -> None:
        self.batch = batch


class CrawlPipeline:
    """One writer per data directory. Source failures never overwrite discovery.

    Default Stage implementations. Discovery theo lô when the discovery object
    has ``prefetch`` (``BatchedDiscovery``, contributed by Liễu, langtucod0n).
    References theo lô when the S2 client has ``references_batch``: one request
    returns the S2 citation lists of the next Publications, so a Range needs
    about ``n / batch_size`` S2 requests instead of one or more per Publication
    (see ``_prefetch_references``). Batches run one after another in a single
    background S2 thread, and the next one is queued while half of the current
    batch is still ahead. After a Publication's downloads the arXiv thread
    waits at most ``references_wait`` seconds for its batch (not at all while
    an earlier Publication is still waiting for S2); a batch still
    pending (S2 429 backoff) is left for later and recorded by
    ``settle_references``, which the Runner calls between Publications and
    before each Export. A throttled batch is retried in the S2 thread for up to
    ``references_patience`` seconds. A Publication the batch did not cover is
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
        # References theo lô: IDs sent in a batch and not recorded yet, and one
        # Future per ID (its CitationList, or the error to record). Only the main
        # thread reads or changes these; the S2 thread only fills the Futures.
        self._refs_batched: set[str] = set()
        self._refs_futures: dict[str, Future] = {}
        # Publications whose downloads finished before their batch: recorded later.
        self._refs_deferred: dict[str, Future] = {}
        # IDs recorded by settle_references since the Runner last read this list.
        self.settled_ids: list[str] = []
        self.references_wait = REFERENCES_WAIT
        self.references_patience = REFERENCES_PATIENCE
        self._refs_queue: queue.SimpleQueue | None = None
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
            if record.status not in SOURCE_OK
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
        """Start S2 batches for ``ids`` and the next IDs the caller will crawl.

        Mirrors ``_prefetch_window`` with two differences:

        - A batch runs in a background thread (``_start_references_batch``);
          nothing is written there, and the main thread waits only when it
          needs a Publication whose batch has not answered yet.
        - Look-ahead: a new batch also starts when an ID among the next
          ``batch_size // 2`` upcoming ones is not covered yet, so the batch
          after the current one is usually ready before the crawl reaches it.

        A batch is filled positionally with IDs that were never batched and
        lack a verified references cache. A batch that fails with 429/5xx keeps
        that error for every ID in it (asking one by one would hit the same
        limit); those IDs are batched again on the next pass. Any other batch
        failure falls back to one request per Publication.
        """
        # Looked up on the class so a client without the method, or a test double, opts out.
        if self.references is None or not callable(getattr(type(self.references), "references_batch", None)):
            return
        size = getattr(self.references, "batch_size", 0)
        if not isinstance(size, int) or size < 1:
            return

        def needed(identifier):
            return identifier not in self._refs_batched and not self._references_verified(identifier)

        ahead = list(upcoming[:max(1, size // 2)])
        if not any(needed(i) for i in ids) and not any(needed(i) for i in ahead):
            return
        limit = max(size, len(ids))
        window: list[str] = []
        # Bounded scan: a resumed Range may have many verified caches in a row.
        for identifier in [*ids, *[i for i in upcoming[:4 * limit] if i not in ids]]:
            if needed(identifier):
                window.append(identifier)
                if len(window) >= limit:
                    break
        for start in range(0, len(window), size):
            chunk = window[start:start + size]
            self._refs_futures.update(self._start_references_batch(chunk))
            self._refs_batched.update(chunk)

    def _start_references_batch(self, chunk) -> dict[str, Future]:
        """Queue one S2 batch for the S2 thread; one Future per Publication."""
        futures = {identifier: Future() for identifier in chunk}
        if self._refs_queue is None:
            self._refs_queue = queue.SimpleQueue()
            # Daemon: a batch still in 429 backoff when the run stops must not hold
            # the process open; its results were only in memory.
            threading.Thread(target=self._references_worker, args=(self._refs_queue,),
                             name="s2-batch", daemon=True).start()
        self._refs_queue.put(futures)
        return futures

    def _references_worker(self, jobs: queue.SimpleQueue) -> None:
        """S2 thread: answer queued batches in order. Only HTTP happens here.

        - A throttled batch (429/5xx) is retried after ``THROTTLE_PAUSE`` while
          ``references_patience`` lasts, then fails every Publication in it
          (asking one by one would hit the same limit).
        - A batch that fails another way falls back to one paginated request per
          Publication, still in this thread, so it overlaps arXiv downloads.
        - A list of ``BATCH_ROW_LIMIT`` rows or more may be truncated and is
          fetched again with pagination.
        """
        while True:
            futures = jobs.get()
            chunk = list(futures)
            started = time.monotonic()
            while True:
                try:
                    ready = self.references.references_batch(chunk)
                except BaseException as error:
                    throttled = isinstance(error, HttpStatusError) and error.status in RETRY_STATUSES
                    if throttled and time.monotonic() - started + THROTTLE_PAUSE <= self.references_patience:
                        print(json.dumps({"event": "batch_references_throttled", "http_status": error.status,
                                          "size": len(chunk), "pause": THROTTLE_PAUSE}), flush=True)
                        time.sleep(THROTTLE_PAUSE)
                        continue
                    print(json.dumps({"event": "batch_references_failed" if throttled else "batch_references_fallback",
                                      "error_type": type(error).__name__,
                                      "http_status": getattr(error, "status", None), "size": len(chunk)}),
                          flush=True)
                    for identifier, future in futures.items():
                        if throttled:
                            future.set_exception(error)
                        else:
                            self._settle_future(future, self._fetch_references, identifier)
                    break
                for identifier, future in futures.items():
                    rows = ready.get(identifier)
                    if rows is None:
                        # Same record as the single-Publication endpoint answering 404.
                        future.set_exception(HttpStatusError(404, "Semantic Scholar"))
                    elif len(rows) >= BATCH_ROW_LIMIT:
                        self._settle_future(future, self._fetch_references, identifier)
                    else:
                        self._settle_future(future, CitationList.from_raw, identifier, rows)
                break

    @staticmethod
    def _settle_future(future: Future, function, *args) -> None:
        try:
            future.set_result(function(*args))
        except BaseException as error:
            future.set_exception(error)

    def _submit_references(self, pool, arxiv_id, refresh):
        """How the citation list of ``arxiv_id`` arrives; None without S2.

        A Future (verified cache: result None; or one paginated request in the
        worker), or ``_Batched`` when the S2 thread holds it.
        """
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
            batch = self._refs_futures.pop(arxiv_id, None) or self._refs_deferred.pop(arxiv_id, None)
            if batch is not None:
                return _Batched(batch)
        return pool.submit(self._fetch_references, arxiv_id)

    def references_pending(self) -> int:
        """Publications whose downloads are done but whose batch has not been recorded."""
        return len(self._refs_deferred)

    def settle_references(self, timeout: float = 0.0) -> list[str]:
        """Record deferred Publications whose batch has answered, waiting up to ``timeout`` s.

        Returns the recorded IDs (also appended to ``settled_ids``).
        """
        settled: list[str] = []
        if not self._refs_deferred:
            return settled
        deadline = time.monotonic() + max(0.0, timeout)
        stats = {"errors": 0, "references_success": 0}
        with self.corpus_lock():
            for arxiv_id, batch in list(self._refs_deferred.items()):
                if not batch.done():
                    wait([batch], timeout=max(0.0, deadline - time.monotonic()))
                if not batch.done():
                    continue
                del self._refs_deferred[arxiv_id]
                # Recorded: on success the cache is verified, on failure the next pass batches it again.
                self._refs_batched.discard(arxiv_id)
                self._record_references(arxiv_id, batch, stats)
                settled.append(arxiv_id)
        self.settled_ids.extend(settled)
        return settled

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
                 "references_success": 0, "references_s2_not_found": 0}
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
        self.settle_references(0.0)   # record batches that answered meanwhile
        with ThreadPoolExecutor(max_workers=1) as pool:
            for index, arxiv_id in enumerate(ids):
                charged = batch_seconds if index == 0 else 0.0
                refs_charged = refs_seconds if index == 0 else 0.0
                timing = {"arxiv_id": arxiv_id,
                          "started_at": datetime.now(timezone.utc).isoformat(),
                          "discovery_seconds": charged, "batch_discovery_seconds": charged,
                          "batch_references_seconds": refs_charged,
                          "references_wait_seconds": 0.0}
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
        if isinstance(refs, _Batched):
            # Time the arXiv thread is held up by S2 after its own downloads.
            waited = self.clock()
            if not refs.batch.done() and not self._refs_deferred:
                # Wait only while S2 looks healthy: once a batch is overdue, every
                # Publication behind it would add the full wait.
                wait([refs.batch], timeout=self.references_wait)
            timing["references_wait_seconds"] = self.clock() - waited
            if not refs.batch.done():
                self._refs_deferred[arxiv_id] = refs.batch   # settle_references records it
                return
            self._refs_batched.discard(arxiv_id)
            refs = refs.batch
        self._record_references(arxiv_id, refs, stats)

    def _record_references(self, arxiv_id, refs: Future, stats) -> None:
        """Write the citation cache and Manifest record of one Publication (main thread)."""
        try:
            citations = refs.result()
            if citations is not None:
                path = self._references_path(arxiv_id)
                write_json(path, {"format": 1, "arxiv_id": arxiv_id, "rows": list(citations.raw)})
                self._record(arxiv_id, None, "references", "success", local_path=str(path),
                             checksum=hashlib.sha256(path.read_bytes()).hexdigest())
            stats["references_success"] += 1
        except HttpStatusError as error:
            if error.status != 404:
                self._failure(arxiv_id, None, "references", error)
                stats["errors"] += 1
                return
            # S2 has no record of this Publication: a real S2-side gap, not a crawl
            # failure. Asking again gives the same 404, so record it and move on
            # (docs/data-contract.md 3.3; seen on 2508.03220, 15/11/2026).
            path = self._references_path(arxiv_id)
            write_json(path, {"format": 1, "arxiv_id": arxiv_id, "rows": [], "s2_status": S2_NOT_FOUND})
            self._record(arxiv_id, None, "references", "unavailable", local_path=str(path),
                         http_status=404, checksum=hashlib.sha256(path.read_bytes()).hexdigest())
            stats["references_s2_not_found"] = stats.get("references_s2_not_found", 0) + 1
        except Exception as error:
            self._failure(arxiv_id, None, "references", error)
            stats["errors"] += 1

    def _log_timing(self, timing):
        """Append one visit of one Publication to ``manifests/timings.jsonl``."""
        append_jsonl(self.timings_path, {k: round(v, 3) if isinstance(v, float) else v
                                         for k, v in timing.items()})

    def crawl_range(self, arxiv_range: ArxivRange, *, refresh: bool = False) -> dict[str, int]:
        return self.crawl_ids(list(arxiv_range.ids()), refresh=refresh)

    def export(self, ids: list[str], *, require_references: bool = True,
               include_incomplete: bool = False) -> tuple[list[PublicationBundle], dict[str, Path]]:
        """Export the requested batch under the corpus lock.

        Callers that must keep the lock after export (for example to upload the
        same tables) wrap this call in ``corpus_lock()``.
        """
        with self.corpus_lock():
            return export_publications(self.corpus, self.sources.root, ids,
                                       require_references=require_references,
                                       include_incomplete=include_incomplete)
