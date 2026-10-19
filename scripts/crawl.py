"""CLI for resumable crawling and explicit Hugging Face publication."""
from __future__ import annotations
import argparse
import json

from src.common.config import ArxivRange, get_settings
from src.crawl.api import run_crawl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crawl arXiv and optionally upload validated data to private HF")
    parser.add_argument("--id", action="append", dest="ids", help="base arXiv ID; repeatable")
    parser.add_argument("--start", type=int)
    parser.add_argument("--end", type=int)
    parser.add_argument("--min-interval", type=float, default=3.0)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--upload", action="store_true", help="merge validated data into configured private HF dataset")
    parser.add_argument("--upload-only", action="store_true", help="publish verified local cache without crawling")
    parser.add_argument("--skip-references", action="store_true", help="explicit source/metadata-only mode")
    parser.add_argument("--refresh", action="store_true", help="refresh metadata/version list and S2 cache")
    args = parser.parse_args(argv)
    if args.ids and (args.start is not None or args.end is not None):
        parser.error("--id cannot be combined with --start/--end")
    if args.upload_only and args.refresh:
        parser.error("--upload-only cannot be combined with --refresh")
    settings = get_settings()
    try:
        ids = args.ids if args.ids else ArxivRange(settings.arxiv_range.prefix,
            args.start if args.start is not None else settings.arxiv_range.start,
            args.end if args.end is not None else settings.arxiv_range.end).ids()
        result = run_crawl(ids, settings=settings, upload=args.upload or args.upload_only,
                           references=not args.skip_references, refresh=args.refresh,
                           upload_only=args.upload_only, batch_size=args.batch_size,
                           min_interval=args.min_interval)
    except ValueError as error:
        print(f"Invalid configuration or data: {error}")
        return 2
    except Exception as error:
        print(f"Pipeline stopped: {type(error).__name__}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    counts = result["counts"]
    return 1 if counts.get("errors") or counts.get("not_ready") or counts.get("upload_errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
