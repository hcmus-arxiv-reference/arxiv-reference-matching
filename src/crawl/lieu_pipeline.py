"""M1 crawler CLI and compatibility aliases for Liễu's Stage implementations.

Run: python -m src.milestone1_crawler --data-dir data/crawl-smoke
Batched Discovery (src/crawl/discovery.py:BatchedDiscovery) and References
overlapped with source downloads (CrawlPipeline._crawl) were contributed by
Liễu (langtucod0n) in merge parent 0d19257 and are now the defaults of the
shared Engine. src/crawl/ is the only Engine on main
(docs/adr/0001-src-crawl-la-khung-duy-nhat.md); the standalone crawler is kept
at tag lieu-standalone-final. LieuPipeline remains only so existing imports
and range-run.json (engine "lieu") keep working; it adds no behaviour.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import signal

from src.common.config import get_settings
from src.crawl.discovery import BatchedDiscovery
from src.crawl.http_client import HttpClient
from src.crawl.pipeline import CrawlPipeline
from src.crawl.semantic_scholar import SemanticScholarClient
from src.crawl.source import ArxivSourceDownloader
from src.crawl.storage import require_id

__all__ = ["BatchedDiscovery", "LieuPipeline", "main"]


class LieuPipeline(CrawlPipeline):
    """Alias of CrawlPipeline; ``s2`` is the old name of ``references``."""
    engine = "lieu"

    @property
    def s2(self):
        return self.references

    @s2.setter
    def s2(self, client):
        self.references = client


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
