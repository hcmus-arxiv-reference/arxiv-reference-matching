"""Orchestration layer: discovery, source downloads, checkpoints and resume."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from src.common.config import ArxivRange

from .discovery import ArxivDiscovery, Publication
from .manifest import Manifest, TaskRecord
from .source import ArxivSourceDownloader


class CrawlPipeline:
    def __init__(self, discovery: ArxivDiscovery, sources: ArxivSourceDownloader, data_dir: str | Path = "data") -> None:
        self.discovery = discovery
        self.sources = sources
        self.data_dir = Path(data_dir)
        self.manifest = Manifest(self.data_dir / "manifests" / "crawl.jsonl")

    def _save_publication(self, publication: Publication) -> None:
        path = self.data_dir / "metadata" / f"{publication.arxiv_id.replace('/', '-')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(publication), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def crawl_ids(self, ids: list[str]) -> dict[str, int]:
        stats = {"success": 0, "non_tex": 0, "unavailable": 0, "errors": 0, "skipped": 0}
        for arxiv_id in ids:
            existing = self.manifest.get(arxiv_id, None, "discovery")
            try:
                publication = self.discovery.discover(arxiv_id) if existing is None or existing.status != "success" else self._load_publication(arxiv_id)
                self._save_publication(publication)
                self.manifest.upsert(TaskRecord(arxiv_id, None, "discovery", "success", updated_at=self._now()))
                for version in range(1, publication.versions + 1):
                    prior = self.manifest.get(arxiv_id, version)
                    if prior and prior.status == "success":
                        stats["skipped"] += 1
                        continue
                    result = self.sources.download(arxiv_id, version)
                    self.manifest.upsert(TaskRecord(arxiv_id, version, "source", result.status, 1, None, str(result.path), result.checksum, updated_at=self._now()))
                    stats[result.status] = stats.get(result.status, 0) + 1
            except Exception as error:  # one bad publication must not stop the range
                self.manifest.upsert(TaskRecord(arxiv_id, None, "discovery", "error", 1, error_reason=str(error), updated_at=self._now()))
                stats["errors"] += 1
        return stats

    def crawl_range(self, arxiv_range: ArxivRange) -> dict[str, int]:
        return self.crawl_ids(list(arxiv_range.ids()))

    def _load_publication(self, arxiv_id: str) -> Publication:
        path = self.data_dir / "metadata" / f"{arxiv_id.replace('/', '-')}.json"
        return Publication(**json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
