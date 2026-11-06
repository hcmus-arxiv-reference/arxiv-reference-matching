"""Run a Range with bounded retries and resumable, verified progress.

The Runner owns policy only: which Publications to retry, when to stop, how
long to cool down, and what ``range-run.json`` reports. Everything it needs from
the crawler crosses the ``Engine`` seam below; ``CrawlPipeline`` is the Engine
on ``main`` (ADR 0001) and tests drive the Runner with an in-memory Engine.
"""
from collections import Counter
from contextlib import AbstractContextManager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time
from typing import Protocol, Sequence

from src.common.corpus import PublicationState
from src.common.json_io import write_json


class Engine(Protocol):
    """What the Runner needs from an Engine.

    - ``engine``: label written to ``range-run.json``.
    - ``data_dir``: holds ``STOP_RANGE``, ``manifests/range-run.json`` and is
      checked for free disk space.
    - ``exclusive()``: one run per data directory; fails at once if taken and
      reloads checkpoints from disk on entry.
    - ``status(id)``: verified state from local files only, no network.
    - ``crawl_ids(ids, upcoming=...)``: crawl ``ids``; ``upcoming`` is the rest
      of this pass in order, so the Engine may choose its own Discovery batch.
    - ``export(ids)``: write ``papers``/``references`` for every ready
      Publication of ``ids``; returns ``(bundles, table paths)``.
    - ``issues(id)``: unfinished tasks of one Publication, safe to print.
    """
    engine: str
    data_dir: Path

    def exclusive(self) -> AbstractContextManager: ...
    def status(self, arxiv_id: str) -> PublicationState: ...
    def crawl_ids(self, ids: list[str], *, upcoming: Sequence[str] = ()) -> dict[str, int]: ...
    def export(self, ids: list[str]) -> tuple[list, dict]: ...
    def issues(self, arxiv_id: str) -> list[dict]: ...


def inspect_publication(pipeline: Engine, identifier):
    """Read and verify existing caches without issuing network requests.

    The dict keys are summed into ``range-run.json`` counts, so they stay as is;
    the check itself is ``Engine.status``.
    """
    state = pipeline.status(identifier)
    metadata = state.publication is not None
    return {"metadata": metadata, "expected_versions": state.expected_versions,
            "verified_versions": state.verified_versions,
            "non_tex_versions": state.non_tex_versions,
            # References were only inspected after valid metadata; keep that count.
            "references": metadata and state.references_ok,
            "complete": state.complete}


def publication_issues(manifest, identifier):
    """Summarize unfinished tasks without exposing URLs, headers or payloads.

    Kept for earlier callers; the Runner asks ``Engine.issues``.
    """
    return [
        {"kind": record.kind, "version": record.version, "status": record.status,
         "http_status": record.http_status, "error_reason": record.error_reason}
        for record in manifest.records_for(identifier)
        if record.status not in {"success", "non_tex"}
    ]


def run_range(pipeline: Engine, identifiers, *, max_passes=3, retry_delay=1800,
              sleeper=time.sleep, min_free_bytes=5 * 1024**3):
    """Hold the pipeline lock, retry only incomplete Publications, and export all.

    STOP_RANGE in the data directory requests a graceful stop after the current
    Publication. Ctrl+C/SIGTERM also preserve checkpoints and export progress.
    """
    if max_passes < 1 or retry_delay < 0:
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
                  "engine": pipeline.engine,
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

    with pipeline.exclusive():
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
                    pipeline.crawl_ids([current], upcoming=pending[position + 1:])
                    states[current] = inspect_publication(pipeline, current)
                    visited += 1
                    report = save("running")
                    print(json.dumps({"pass": pass_number, "id": current,
                                      "complete": report["counts"].get("complete", 0),
                                      "pending": len(report["pending_ids"]),
                                      "issues": pipeline.issues(current)}), flush=True)
                current = None
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
            bundles, _ = pipeline.export(identifiers)
            return save("stopped", exported_publications=len(bundles))
        except Exception as error:
            save("failed", error_type=type(error).__name__)
            raise


