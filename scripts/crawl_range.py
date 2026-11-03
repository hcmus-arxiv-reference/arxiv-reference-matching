"""Run a whole Range locally with verified progress and bounded retry passes.

Uses the existing crawler and schema. Raw checkpoints survive interruption;
the two aggregate Parquet tables are rebuilt at the end of each pass.
No Hugging Face operations are performed.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import signal


from src.common.config import get_settings, member_ids
from src.crawl.discovery import BatchedDiscovery
from src.crawl.http_client import HttpClient
from src.crawl.pipeline import CrawlPipeline
from src.crawl.semantic_scholar import SemanticScholarClient
from src.crawl.source import ArxivSourceDownloader


from src.crawl.runner import inspect_publication, publication_issues, run_range


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--member", help="Range trong configs/ranges.toml; 'all' = cả nhóm")
    parser.add_argument("--max-passes", type=int, default=3)
    parser.add_argument("--retry-delay", type=int, default=1800)
    args = parser.parse_args(argv)
    if args.max_passes < 1 or args.retry_delay < 0:
        parser.error("Invalid retry settings")
    settings = replace(get_settings(), data_dir=args.data_dir)
    try:
        ids = list(member_ids(args.member)) if args.member else list(settings.arxiv_range.ids())
    except (KeyError, ValueError) as error:
        parser.error(str(error))
    user_agent = settings.user_agent()
    arxiv = HttpClient(user_agent, min_interval=3.1)
    s2 = HttpClient(user_agent, min_interval=1.1 if settings.s2_api_key else 3.1,
                    headers={"x-api-key": settings.s2_api_key} if settings.s2_api_key else {})
    pipeline = CrawlPipeline(BatchedDiscovery(arxiv),
        ArxivSourceDownloader(arxiv, settings.data_dir / "raw"), settings.data_dir,
        references=SemanticScholarClient(s2))

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    result = run_range(pipeline, ids,
                       max_passes=args.max_passes, retry_delay=args.retry_delay)
    print(json.dumps({k: v for k, v in result.items() if k != "pending_ids"}), flush=True)
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
