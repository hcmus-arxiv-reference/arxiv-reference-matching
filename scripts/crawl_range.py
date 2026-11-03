"""Run a whole Range locally with verified progress and bounded retry passes.

Uses the existing crawler and schema. Raw checkpoints survive interruption;
the two aggregate Parquet tables are rebuilt at the end of each pass.
No Hugging Face operations are performed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import shutil
import signal
import time

from filelock import FileLock

from src.common.config import ArxivRange, get_settings
from src.crawl.batched import BatchedDiscovery
from src.crawl.http_client import HttpClient
from src.crawl.manifest import Manifest
from src.crawl.pipeline import CrawlPipeline
from src.crawl.semantic_scholar import SemanticScholarClient
from src.crawl.source import ArxivSourceDownloader, verified_source
from src.crawl.storage import key, write_json


def inspect_publication(pipeline, identifier):
    """Read and verify existing caches without issuing network requests."""
    result = {"metadata": False, "expected_versions": 0, "verified_versions": 0,
              "non_tex_versions": 0, "references": False, "complete": False}
    try:
        publication = pipeline._load_publication(identifier)
        result.update(metadata=True, expected_versions=publication.versions)
        for version in range(1, publication.versions + 1):
            record = pipeline.manifest.get(identifier, version)
            source = verified_source(pipeline.sources.root / key(identifier) / f"v{version}")
            if (source and record and record.status == source.status
                    and record.checksum == source.checksum):
                result["verified_versions"] += 1
                result["non_tex_versions"] += source.status == "non_tex"
        pipeline._load_references(identifier)
        result["references"] = True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    result["complete"] = (result["metadata"] and result["references"]
                          and result["verified_versions"] == result["expected_versions"])
    return result


def run_range(pipeline, identifiers, *, max_passes=3, retry_delay=1800,
              sleeper=time.sleep, min_free_bytes=5 * 1024**3, export_every=50):
    """Hold the pipeline lock, retry only incomplete Publications, and export all.

    STOP_RANGE in the data directory requests a graceful stop after the current
    Publication. Ctrl+C/SIGTERM also preserve checkpoints and export progress.
    """
    if max_passes < 1 or retry_delay < 0 or export_every < 1:
        raise ValueError("max_passes must be positive and retry_delay nonnegative")
    identifiers = list(dict.fromkeys(identifiers))
    root = pipeline.data_dir
    status_path = root / "manifests" / "range-run.json"
    started = datetime.now(timezone.utc).isoformat()
    states = {}
    pass_number, visited = 0, 0
    current = None

    def save(status, **extra):
        totals = Counter()
        for item in states.values():
            totals.update({k: int(v) for k, v in item.items()})
        report = {"status": status, "pid": os.getpid(), "started_at": started,
                  "engine": getattr(pipeline, "engine", "main"),
                  "updated_at": datetime.now(timezone.utc).isoformat(),
                  "range_first": identifiers[0] if identifiers else None,
                  "range_last": identifiers[-1] if identifiers else None,
                  "requested": len(identifiers), "pass": pass_number,
                  "visited_this_pass": visited, "current_id": current,
                  "counts": dict(totals),
                  "pending_ids": [i for i in identifiers if not states.get(i, {}).get("complete")],
                  **extra}
        write_json(status_path, report)
        return report

    with FileLock(str(root / ".pipeline.lock"), timeout=0):
        if status_path.exists():
            previous = json.loads(status_path.read_text(encoding="utf-8"))
            if (previous.get("range_first"), previous.get("range_last"), previous.get("requested")) != (
                identifiers[0] if identifiers else None,
                identifiers[-1] if identifiers else None, len(identifiers)
            ):
                raise ValueError("Data directory belongs to another Range; choose --data-dir")
        pipeline.manifest = Manifest(pipeline.manifest.path)
        print(f"Checking local cache for {len(identifiers)} Publications...", flush=True)
        states = {i: inspect_publication(pipeline, i) for i in identifiers}
        save("running")
        try:
            for pass_number in range(1, max_passes + 1):
                visited = 0
                pending = [i for i in identifiers if not states[i]["complete"]]
                for position, current in enumerate(pending):
                    if (root / "STOP_RANGE").exists():
                        raise InterruptedError("stop requested")
                    if shutil.disk_usage(root).free < min_free_bytes:
                        raise OSError("Insufficient free disk space")
                    save("running")
                    print(f"[pass {pass_number}] {current} ({position + 1}/{len(pending)} pending)", flush=True)
                    prefetch = getattr(pipeline, "prefetch", None)
                    size = getattr(pipeline, "prefetch_size", 50)
                    if prefetch is not None and position % size == 0:
                        prefetch(pending[position:position + size])
                    pipeline.crawl_ids([current])
                    states[current] = inspect_publication(pipeline, current)
                    visited += 1
                    if visited % export_every == 0:
                        with FileLock(str(root / ".crawl.lock"), timeout=0):
                            pipeline.export(identifiers)
                    report = save("running")
                    print(json.dumps({"pass": pass_number, "id": current,
                                      "complete": report["counts"].get("complete", 0),
                                      "pending": len(report["pending_ids"])}), flush=True)
                current = None
                with FileLock(str(root / ".crawl.lock"), timeout=0):
                    bundles, _ = pipeline.export(identifiers)
                # Export performs its own full validation, not just manifest counts.
                if len(bundles) == len(identifiers):
                    return save("complete", exported_publications=len(bundles))
                if pass_number < max_passes:
                    save("retry_wait", retry_delay_seconds=retry_delay,
                         exported_publications=len(bundles))
                    # Short intervals allow STOP_RANGE to interrupt a long cooldown.
                    remaining = retry_delay
                    while remaining > 0:
                        if (root / "STOP_RANGE").exists():
                            raise InterruptedError("stop requested")
                        delay = min(30, remaining)
                        sleeper(delay)
                        remaining -= delay
            return save("incomplete", exported_publications=len(bundles))
        except (KeyboardInterrupt, InterruptedError):
            with FileLock(str(root / ".crawl.lock"), timeout=0):
                bundles, _ = pipeline.export(identifiers)
            return save("stopped", exported_publications=len(bundles))
        except Exception as error:
            save("failed", error_type=type(error).__name__)
            raise


class RangePipeline(CrawlPipeline):
    """Batch discovery with the original receipt and Parquet output contract."""
    engine = "range-cli"

    @property
    def prefetch_size(self):
        return self.discovery.batch_size or 1

    def prefetch(self, identifiers):
        missing = []
        for identifier in identifiers:
            try:
                self._load_publication(identifier)
            except (OSError, ValueError, KeyError, TypeError):
                missing.append(identifier)
        self.discovery.prefetch(missing)


def parse_range(start, end):
    """Parse inclusive modern IDs; never confuse row indexes with arXiv IDs."""
    first = re.fullmatch(r"(\d{4})\.(\d{5})", start)
    last = re.fullmatch(r"(\d{4})\.(\d{5})", end)
    if not first or not last or first[1] != last[1]:
        raise ValueError("--start and --end must be base IDs in the same month, e.g. 2412.08848")
    return ArxivRange(first[1], int(first[2]), int(last[2]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="inclusive first base ID, e.g. 2412.08848")
    parser.add_argument("--end", help="inclusive last base ID, e.g. 2412.13847")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--discover-batch", type=int, default=50)
    parser.add_argument("--export-every", type=int, default=50)
    parser.add_argument("--max-passes", type=int, default=3)
    parser.add_argument("--retry-delay", type=int, default=1800)
    args = parser.parse_args(argv)
    if (args.max_passes < 1 or args.retry_delay < 0 or args.export_every < 1
            or not 1 <= args.discover_batch <= 100):
        parser.error("Invalid retry settings")
    if bool(args.start) != bool(args.end):
        parser.error("Use --start and --end together")
    settings = get_settings()
    try:
        selected = parse_range(args.start, args.end) if args.start else settings.arxiv_range
        root = args.data_dir or Path("data") / f"crawl-{selected.prefix}-{selected.start:05d}-{selected.end:05d}"
        settings = replace(settings, data_dir=root, arxiv_range=selected)
        settings.user_agent()
    except ValueError as error:
        parser.error(str(error))
    user_agent = settings.user_agent()
    arxiv = HttpClient(user_agent, min_interval=3.1)
    s2 = HttpClient(user_agent, min_interval=1.1 if settings.s2_api_key else 3.1,
                    headers={"x-api-key": settings.s2_api_key} if settings.s2_api_key else {})
    pipeline = RangePipeline(BatchedDiscovery(arxiv, args.discover_batch),
        ArxivSourceDownloader(arxiv, settings.data_dir / "raw"), settings.data_dir,
        references=SemanticScholarClient(s2))

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(f"Range {selected.prefix}.{selected.start:05d}..{selected.prefix}.{selected.end:05d}: "
          f"{len(selected)} IDs; output={settings.data_dir.resolve()}", flush=True)
    try:
        result = run_range(pipeline, settings.arxiv_range.ids(),
                           max_passes=args.max_passes, retry_delay=args.retry_delay,
                           export_every=args.export_every)
    except Exception as error:
        print(f"Crawl stopped: {type(error).__name__}: {error}", flush=True)
        return 1
    print(json.dumps({k: v for k, v in result.items() if k != "pending_ids"}), flush=True)
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
