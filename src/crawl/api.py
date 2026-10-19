"""Public Python API for crawl → validate → export → private HF upload."""
from __future__ import annotations

from collections import Counter
from itertools import islice
import math
from typing import Iterable

from filelock import FileLock
from src.common.config import Settings, get_settings
from .discovery import ArxivDiscovery
from .http_client import HttpClient
from .manifest import Manifest
from .pipeline import CrawlPipeline
from .publish import HuggingFacePublisher
from .semantic_scholar import SemanticScholarClient
from .source import ArxivSourceDownloader
from .storage import require_id, write_json


def run_crawl(ids: Iterable[str] | None = None, *, settings: Settings | None = None,
              upload: bool = False, references: bool = True, refresh: bool = False,
              upload_only: bool = False, batch_size: int = 5, min_interval: float = 3.0) -> dict:
    """Crawl configured Range or explicit IDs; upload is opt-in.

    references=False explicitly selects source/metadata-only mode. A failed
    Publication is retained locally but is not uploaded. Upload-only reads the
    validated local cache and never calls arXiv/S2. Rerun to resume after errors.
    """
    settings = settings or get_settings()
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    if not math.isfinite(min_interval) or min_interval < 3:
        raise ValueError("arXiv min_interval must be at least 3 seconds")
    if upload_only and not upload:
        raise ValueError("upload_only requires upload=True")
    if upload:
        settings.require_hf()
    user_agent = settings.user_agent() if not upload_only else "arxiv-reference-matching/upload-only"
    arxiv = HttpClient(user_agent, min_interval=min_interval)
    s2 = SemanticScholarClient(HttpClient(user_agent,
        min_interval=3.1 if not settings.s2_api_key else 1.0,
        headers={"x-api-key": settings.s2_api_key} if settings.s2_api_key else {})) if references else None
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    counts, uploads = Counter(), []
    iterator = iter(ids if ids is not None else settings.arxiv_range.ids())
    with FileLock(str(settings.data_dir / ".pipeline.lock"), timeout=0):
        pipeline = CrawlPipeline(ArxivDiscovery(arxiv), ArxivSourceDownloader(arxiv, settings.data_dir / "raw"),
                                 settings.data_dir, references=s2)
        publisher = HuggingFacePublisher(settings) if upload else None
        if publisher:
            publisher._info()  # fail before expensive crawling if repo is not usable
        while batch := list(islice(iterator, batch_size)):
            batch = list(dict.fromkeys(require_id(i) for i in batch))
            counts["requested"] += len(batch)
            if not upload_only:
                counts.update(pipeline.crawl_ids(batch, refresh=refresh))
            with FileLock(str(settings.data_dir / ".crawl.lock"), timeout=0):
                pipeline.manifest = Manifest(pipeline.manifest.path)
                bundles, tables = pipeline.export(batch, require_references=references)
                counts["ready"] += len(bundles)
                counts["not_ready"] += len(batch) - len(bundles)
                if publisher:
                    try:
                        uploads.append(publisher.publish(bundles, tables))
                    except Exception as error:
                        counts["upload_errors"] += 1
                        uploads.append({"status": "error", "error_type": type(error).__name__})
            write_json(settings.data_dir / "manifests" / "last-run.json", {"counts": dict(counts), "uploads": uploads})
    return {"counts": dict(counts), "uploads": uploads}
