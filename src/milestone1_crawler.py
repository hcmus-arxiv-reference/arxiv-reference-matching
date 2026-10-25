"""Stable CLI for the checksum-verified Range crawler.

The standalone implementation from b27440f is preserved separately in
src.lieu_standalone_crawler; it does not implement this cache contract.
Run the integrated crawler with: python -m src.milestone1_crawler --data-dir data/crawl-smoke
"""
from src.crawl.lieu_pipeline import BatchedDiscovery, LieuPipeline, main

__all__ = ["BatchedDiscovery", "LieuPipeline", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
