"""M1 crawler entry point; runs the shared src/crawl/ Engine (ADR 0001).

Run: python -m src.milestone1_crawler --data-dir data/crawl-smoke
Lieu's standalone crawler is kept at tag lieu-standalone-final, not on main.
Python imports of BatchedDiscovery/LieuPipeline remain available for callers.
"""
from src.crawl.lieu_pipeline import BatchedDiscovery, LieuPipeline, main

__all__ = ["BatchedDiscovery", "LieuPipeline", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
