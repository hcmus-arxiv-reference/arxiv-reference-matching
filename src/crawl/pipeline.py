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
from src.common.schema import from_records, write_table
from .discovery import ArxivDiscovery, Publication
from .manifest import Manifest, TaskRecord
from .semantic_scholar import SemanticScholarClient, reference_rows
from .source import ArxivSourceDownloader, verified_source
from .storage import key, require_id, write_json


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
        return self.data_dir / "metadata" / f"{key(arxiv_id)}.json"

    def _references_path(self, arxiv_id: str) -> Path:
        return self.data_dir / "references" / f"{key(arxiv_id)}.json"

    def _record(self, arxiv_id, version, kind, status, *, attempted=True, **fields):
        prior = self.manifest.get(arxiv_id, version, kind)
        attempts = (prior.attempts if prior else 0) + int(attempted)
        self.manifest.upsert(TaskRecord(arxiv_id, version, kind, status, attempts,
                                       updated_at=datetime.now(timezone.utc).isoformat(), **fields))

    def _failure(self, arxiv_id, version, kind, error):
        # Exception messages from remote SDKs may include response bodies/headers.
        self._record(arxiv_id, version, kind, "error",
                     http_status=getattr(error, "status", None), error_reason=type(error).__name__)

    def _load_publication(self, arxiv_id: str) -> Publication:
        body = self._metadata_path(arxiv_id).read_bytes()
        record = self.manifest.get(arxiv_id, None, "discovery")
        if not record or record.status != "success" or hashlib.sha256(body).hexdigest() != record.checksum:
            raise ValueError("Unverified discovery cache")
        payload = json.loads(body)
        if payload["format"] != 1:
            raise ValueError("Old discovery cache must be refreshed")
        publication = Publication(**payload["publication"])
        self._validate_publication(publication, arxiv_id)
        return publication

    @staticmethod
    def _validate_publication(publication: Publication, arxiv_id: str) -> None:
        if publication.arxiv_id != arxiv_id or type(publication.versions) is not int or publication.versions < 1:
            raise ValueError("Invalid discovery identity/version count")
        if len(publication.revised_dates) != publication.versions - 1:
            raise ValueError("Incomplete revision dates")
        row = asdict(publication)
        row.pop("versions")
        from_records([row], "papers")

    def _load_references(self, arxiv_id: str) -> list[dict]:
        record = self.manifest.get(arxiv_id, None, "references")
        path = self._references_path(arxiv_id)
        body = path.read_bytes()
        if not record or record.status != "success" or hashlib.sha256(body).hexdigest() != record.checksum:
            raise ValueError("Unverified references cache")
        payload = json.loads(body)
        if payload["format"] != 1 or payload["arxiv_id"] != arxiv_id:
            raise ValueError("Wrong references cache")
        reference_rows(arxiv_id, payload["rows"])
        return payload["rows"]

    def _discover_publication(self, arxiv_id, *, refresh=False):
        """Resolve and persist metadata from the verified cache or Discovery."""
        try:
            if refresh:
                raise ValueError("refresh")
            return self._load_publication(arxiv_id)
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
                self._load_publication(identifier)
            except (OSError, ValueError, KeyError, TypeError):
                missing.append(identifier)
        batch(missing)

    def _submit_references(self, pool, arxiv_id, refresh):
        """Future of new S2 rows (None result for a verified cache); None without S2."""
        if self.references is None:
            return None
        if not refresh:
            try:
                self._load_references(arxiv_id)
                cached = Future()
                cached.set_result(None)
                return cached
            except (OSError, ValueError, TypeError, KeyError):
                pass
        return pool.submit(self._fetch_references, arxiv_id)

    def _fetch_references(self, arxiv_id):
        rows = self.references.references(arxiv_id)
        reference_rows(arxiv_id, rows)
        return rows

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
                    rows = refs.result()
                    if rows is not None:
                        path = self._references_path(arxiv_id)
                        write_json(path, {"format": 1, "arxiv_id": arxiv_id, "rows": rows})
                        self._record(arxiv_id, None, "references", "success", local_path=str(path),
                                     checksum=hashlib.sha256(path.read_bytes()).hexdigest())
                    stats["references_success"] += 1
                except Exception as error:
                    self._failure(arxiv_id, None, "references", error)
                    stats["errors"] += 1
        return stats

    def crawl_range(self, arxiv_range: ArxivRange, *, refresh: bool = False) -> dict[str, int]:
        return self.crawl_ids(list(arxiv_range.ids()), refresh=refresh)

    def export(self, ids: list[str], *, require_references: bool = True) -> tuple[list[dict], dict[str, Path]]:
        """Export only complete Publications; failed ones remain in the manifest.

        Returned bundles enumerate exact files for publication, never entire
        data directories. The caller holds .crawl.lock while exporting/uploading.
        """
        bundles, papers, references = [], [], []
        for arxiv_id in dict.fromkeys(ids):
            try:
                record = self.manifest.get(arxiv_id, None, "discovery")
                if not record or record.status != "success":
                    continue
                publication = self._load_publication(arxiv_id)
                sources = []
                for version in range(1, publication.versions + 1):
                    task = self.manifest.get(arxiv_id, version)
                    if not task or task.status not in {"success", "non_tex"}:
                        raise ValueError("Incomplete source coverage")
                    source = verified_source(self.sources.root / key(arxiv_id) / f"v{version}")
                    if not source or source.checksum != task.checksum:
                        raise ValueError("Source checksum mismatch")
                    sources.append(source)
                raw_refs = self._load_references(arxiv_id) if require_references else None
                row = asdict(publication)
                row.pop("versions")
                papers.append(row)
                if raw_refs is not None:
                    references.extend(reference_rows(arxiv_id, raw_refs))
                bundles.append({"publication": publication, "sources": sources,
                                "metadata": self._metadata_path(arxiv_id),
                                "references": self._references_path(arxiv_id) if raw_refs is not None else None})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        paths = {}
        for name, rows in (("papers", papers), ("references", references)):
            if name == "references" and not require_references:
                continue
            path = self.data_dir / "tables" / f"{name}.parquet"
            write_table(from_records(rows, name), name, path)
            paths[name] = path
        return bundles, paths
