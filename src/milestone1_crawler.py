"""Lieu's batched discovery + overlapped S2/source crawler, integrated with main.

Run: python -m src.milestone1_crawler --data-dir data/crawl-smoke
The original implementation is preserved in merge parent 0d19257. This adapter
keeps its batch-discovery and one-S2-worker design while using the shared
schema, bounded HTTP, full S2 pagination and checksum-verified checkpoints.
It resumes the existing main cache without renaming or copying raw files.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import signal
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

from src.common.config import get_settings
from src.crawl.discovery import ATOM, ArxivDiscovery, parse_feed
from src.crawl.http_client import HttpClient, HttpStatusError
from src.crawl.pipeline import CrawlPipeline
from src.crawl.semantic_scholar import SemanticScholarClient, reference_rows
from src.crawl.source import ArxivSourceDownloader
from src.crawl.storage import require_id, write_json


class BatchedDiscovery(ArxivDiscovery):
    """Prefetch base-ID Atom entries; the shared parser fills all revision dates.

    Missing or failed batch entries fall back to individual queries. A missing
    batch result is never sufficient evidence that a Publication does not exist.
    All arXiv requests, including revision lookups/source downloads, share one
    client and the process-wide rate limiter.
    """

    def __init__(self, client, batch_size=50):
        super().__init__(client)
        if not 0 <= batch_size <= 100:
            raise ValueError("discover_batch must be between 0 and 100")
        self.batch_size = batch_size
        self.prefetched = {}

    def prefetch(self, identifiers):
        ids = list(dict.fromkeys(require_id(i) for i in identifiers))
        ids = [i for i in ids if i not in self.prefetched]
        if not self.batch_size:
            return
        for start in range(0, len(ids), self.batch_size):
            chunk = ids[start:start + self.batch_size]
            try:
                response = self.client.get(f"{self.endpoint}?{urlencode({'id_list': ','.join(chunk)})}")
                if response.status != 200:
                    raise HttpStatusError(response.status, "arXiv batch metadata")
                root = ET.fromstring(response.body)
                found = {}
                for entry in root.findall(f"{{{ATOM}}}entry"):
                    feed = ET.Element(f"{{{ATOM}}}feed")
                    feed.append(entry)
                    body = ET.tostring(feed, encoding="utf-8")
                    pub = parse_feed(body)
                    if pub.arxiv_id not in chunk or pub.arxiv_id in found:
                        raise ValueError("Unexpected or duplicate batch publication")
                    found[pub.arxiv_id] = body
                self.prefetched.update(found)
            except Exception as error:
                print(json.dumps({"event": "batch_discovery_fallback",
                                  "error_type": type(error).__name__, "size": len(chunk)}), flush=True)

    def _fetch(self, identifier):
        if identifier in self.prefetched:
            return self.prefetched.pop(identifier)
        return super()._fetch(identifier)


class LieuPipeline(CrawlPipeline):
    """Lieu orchestration with existing main receipts and single-threaded commits.

    Only network work for S2 runs in the extra thread. Manifest and cache writes
    stay on the main thread, and a failed S2 request never marks a paper done.
    """
    engine = "lieu"

    def __init__(self, discovery, sources, data_dir, references):
        super().__init__(discovery, sources, data_dir, references=None)
        self.s2 = references
        self.prefetch_size = discovery.batch_size or 1

    def prefetch(self, identifiers):
        missing = []
        for identifier in identifiers:
            try:
                self._load_publication(identifier)
            except (OSError, ValueError, KeyError, TypeError):
                missing.append(identifier)
        self.discovery.prefetch(missing)

    def _reference_result(self, identifier, refresh):
        if not refresh:
            try:
                self._load_references(identifier)
                return None  # already verified, no mutation in the worker
            except (OSError, ValueError, KeyError, TypeError):
                pass
        rows = self.s2.references(identifier)
        reference_rows(identifier, rows)
        return rows

    def _crawl(self, ids, *, refresh):
        if refresh:
            self.discovery.prefetch(ids)
        else:
            self.prefetch(ids)
        counts = Counter()
        with ThreadPoolExecutor(max_workers=1) as pool:
            for identifier in ids:
                try:
                    self._discover_publication(identifier, refresh=refresh)
                except Exception as error:
                    self._failure(identifier, None, "discovery", error)
                    counts["errors"] += 1
                    continue
                # Same scheduling as Lieu: one S2 task while the main thread
                # downloads this Publication's sources serially from arXiv.
                refs = pool.submit(self._reference_result, identifier, refresh)
                counts.update(super()._crawl([identifier], refresh=False))
                try:
                    rows = refs.result()
                    if rows is not None:
                        path = self._references_path(identifier)
                        write_json(path, {"format": 1, "arxiv_id": identifier, "rows": rows})
                        self._record(identifier, None, "references", "success", local_path=str(path),
                                     checksum=hashlib.sha256(path.read_bytes()).hexdigest())
                    counts["references_success"] += 1
                except Exception as error:
                    self._failure(identifier, None, "references", error)
                    counts["errors"] += 1
        return dict(counts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", action="append", dest="ids")
    parser.add_argument("--ids-file", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--discover-batch", type=int, default=50)
    parser.add_argument("--max-passes", type=int, default=3)
    parser.add_argument("--retry-delay", type=int, default=1800)
    args = parser.parse_args(argv)
    if not 0 <= args.discover_batch <= 100 or (args.limit is not None and args.limit < 1):
        parser.error("Invalid discover-batch or limit")
    if args.max_passes < 1 or args.retry_delay < 0:
        parser.error("Invalid retry settings")
    settings = get_settings()
    if args.data_dir is not None:
        settings = replace(settings, data_dir=args.data_dir)
    ids = list(args.ids or [])
    if args.ids_file:
        ids.extend(line.strip() for line in args.ids_file.read_text().splitlines()
                   if line.strip() and not line.strip().startswith("#"))
    if not ids:
        ids = list(settings.arxiv_range.ids())
    ids = list(dict.fromkeys(require_id(i) for i in ids))
    if args.limit:
        ids = ids[:args.limit]
    arxiv = HttpClient(settings.user_agent(), min_interval=3.1)
    s2 = HttpClient(settings.user_agent(), min_interval=1.1 if settings.s2_api_key else 3.1,
                    headers={"x-api-key": settings.s2_api_key} if settings.s2_api_key else {})
    pipeline = LieuPipeline(BatchedDiscovery(arxiv, args.discover_batch),
        ArxivSourceDownloader(arxiv, settings.data_dir / "raw"), settings.data_dir,
        SemanticScholarClient(s2))

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    from scripts.crawl_range import run_range
    result = run_range(pipeline, ids, max_passes=args.max_passes, retry_delay=args.retry_delay)
    print(json.dumps({k: v for k, v in result.items() if k != "pending_ids"}), flush=True)
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
