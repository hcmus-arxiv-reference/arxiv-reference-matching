"""Compatibility imports for Liễu's contributions, now shared Engine defaults.

New callers use CrawlPipeline and src.crawl.cli. Existing imports and the
legacy engine label remain supported for saved notebooks and run receipts.
"""
from .pipeline import CrawlPipeline
from .discovery import BatchedDiscovery


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
    """Forward the historical CLI to the canonical entry point."""
    from .cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
