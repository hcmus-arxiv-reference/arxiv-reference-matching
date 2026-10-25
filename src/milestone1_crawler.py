"""M1 uses langtucod0n's standalone structure by the team's 2026-10-25 decision.

Use --engine integrated explicitly to operate the existing verified Range cache.
Python imports of the earlier adapter remain available for existing callers.
"""
import argparse

from src.crawl.lieu_pipeline import BatchedDiscovery, LieuPipeline

__all__ = ["BatchedDiscovery", "LieuPipeline", "main"]


def main(argv=None):
    """Choose a cache contract explicitly; standalone is the new default."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--engine", choices=("standalone", "integrated"), default="standalone")
    args, remaining = parser.parse_known_args(argv)
    if args.engine == "integrated":
        from src.crawl.lieu_pipeline import main as run
    else:
        from src.lieu_standalone_crawler import main as run
    return run(remaining)

if __name__ == "__main__":
    raise SystemExit(main())
