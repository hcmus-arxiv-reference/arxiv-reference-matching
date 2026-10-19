"""CLI for resumable arXiv crawling.

Examples:
  python -m scripts.crawl --start 2872 --end 2876
  python -m scripts.crawl --id 2508.02872 --id 2508.02873
"""

from __future__ import annotations

import argparse

from src.common.config import get_settings
from src.crawl.discovery import ArxivDiscovery
from src.crawl.http_client import HttpClient
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Crawl arXiv metadata and source with checkpoint/resume")
    parser.add_argument("--id", action="append", dest="ids", help="arXiv ID; repeatable")
    parser.add_argument("--start", type=int, help="override range start")
    parser.add_argument("--end", type=int, help="override range end")
    parser.add_argument("--min-interval", type=float, default=3.0)
    args = parser.parse_args()
    client = HttpClient(settings.user_agent(), min_interval=args.min_interval)
    pipeline = CrawlPipeline(
        ArxivDiscovery(client),
        ArxivSourceDownloader(client, settings.data_dir / "raw"),
        settings.data_dir,
    )
    if args.ids:
        ids = args.ids
    else:
        crawl_range = settings.arxiv_range
        if args.start is not None or args.end is not None:
            crawl_range = type(crawl_range)(crawl_range.prefix, args.start or crawl_range.start, args.end or crawl_range.end)
        ids = list(crawl_range.ids())
    print(pipeline.crawl_ids(ids))


if __name__ == "__main__":
    main()
