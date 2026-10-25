"""Retry missing tasks with an immutable copy of langtucod0n's standalone crawler.

The existing cache is read under its pipeline lock. Only missing tasks are sent
to the standalone download/reference functions; no data are merged automatically.
Raw successful responses are independently checked with the bounded extractor.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from filelock import FileLock
from src.common.config import get_settings
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader, extract_source, verified_source
from src.crawl.storage import key, write_json


def build_plan(cache):
    """Recheck the pending list against metadata, task records and file hashes."""
    state = json.loads((cache / "manifests/range-run.json").read_text())
    pipeline = CrawlPipeline(None, ArxivSourceDownloader(None, cache / "raw"), cache)
    plan = []
    for identifier in state["pending_ids"]:
        publication = pipeline._load_publication(identifier)
        missing = []
        for version in range(1, publication.versions + 1):
            source = verified_source(cache / "raw" / key(identifier) / f"v{version}")
            record = pipeline.manifest.get(identifier, version)
            if not (source and record and record.status == source.status
                    and record.checksum == source.checksum):
                missing.append(version)
        try:
            pipeline._load_references(identifier)
            references_missing = False
        except (OSError, ValueError, KeyError, TypeError):
            references_missing = True
        if missing or references_missing:
            plan.append({"id": identifier, "publication": asdict(publication),
                         "source_versions": missing, "references_missing": references_missing})
    return plan, state


def run_trial(cache, output, upstream_ref="e5be40e"):
    """Run one controlled retry pass and persist every result immediately."""
    settings = get_settings()
    settings.user_agent()  # Fail before any requests if contact is missing.
    if output.exists():
        raise ValueError("Use a fresh output directory to preserve trial evidence")
    output.mkdir(parents=True)
    source = subprocess.check_output(
        ["git", "show", f"{upstream_ref}:src/milestone1_crawler.py"])
    snapshot = output / "upstream_crawler.py"
    snapshot.write_bytes(source)
    spec = importlib.util.spec_from_file_location("trial_upstream", snapshot)
    crawler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crawler)
    crawler.DATA_DIR = output / "data"
    crawler.LOG_FILE = output / "logs/run_log.jsonl"
    crawler.COOLDOWN_LOG = output / "logs/cooldowns.jsonl"
    events = []
    original_fetch = crawler.fetch_bytes

    def audited_fetch(url, throttle, headers=None, retries=4, raw=True):
        started = time.monotonic()
        event = {"task": "source" if raw else "references", "url": url}
        try:
            payload = original_fetch(url, throttle, headers, retries, raw)
            event.update(status="not_found" if payload is None else "received",
                         bytes=0 if payload is None else len(payload))
            if payload is not None:
                event["sha256"] = hashlib.sha256(payload).hexdigest()
                if raw:
                    archive = output / "responses" / (url.rsplit("/", 1)[-1] + ".bin")
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    archive.write_bytes(payload)
                    try:
                        with tempfile.TemporaryDirectory(dir=output) as temporary:
                            tex, bib = extract_source(payload, Path(temporary))
                        event.update(validation="success" if tex else "non_tex",
                                     tex_files=len(tex), bib_files=len(bib))
                    except Exception as exc:
                        event.update(validation="invalid", validation_error=type(exc).__name__)
            return payload
        except Exception as exc:
            response = getattr(exc, "response", None)
            event.update(status="error", error_type=type(exc).__name__,
                         http_status=getattr(response, "status_code", None))
            raise
        finally:
            event["seconds"] = round(time.monotonic() - started, 3)
            events.append(event)  # Only primitive, non-secret diagnostics.

    crawler.fetch_bytes = audited_fetch
    started = time.monotonic()
    results = []
    with FileLock(str(cache / ".pipeline.lock"), timeout=0):
        plan, before = build_plan(cache)
        write_json(output / "plan.json", {"upstream_ref": upstream_ref,
            "source_sha256": hashlib.sha256(source).hexdigest(), "before": before, "tasks": plan})
        (output / "ids.txt").write_text("".join(item["id"] + "\n" for item in plan))

        def save(status, current=None):
            report = {"status": status, "pid": os.getpid(), "current_id": current,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.monotonic() - started, 1),
                "requested": len(plan), "visited": len(results),
                "recovered_publications": sum(r["complete_after"] for r in results),
                "source_outcomes": dict(Counter(v["verified_status"]
                    for r in results for v in r["versions"])),
                "reference_outcomes": dict(Counter(r["references_status"]
                    for r in results if r["references_attempted"])),
                "results": results, "network_events": list(events)}
            write_json(output / "result.json", report)
            return report

        with ThreadPoolExecutor(max_workers=1) as pool:
            for item in plan:
                identifier = item["id"]
                save("running", identifier)
                pdir = crawler.DATA_DIR / crawler.safe_dirname(identifier)
                pub = item["publication"]
                crawler.write_json(pdir / "meta.json", {
                    "arxiv_id": identifier, "n_versions": pub["versions"],
                    "title": pub["title"], "authors": pub["authors"],
                    "published": pub["submission_date"],
                    "updated": (pub["revised_dates"] or [pub["submission_date"]])[-1],
                    "journal_ref": pub["venue"], "discover_seconds": 0,
                    "provenance": "verified existing metadata; no network discovery in this trial"})
                future = pool.submit(crawler.fetch_and_save_refs, identifier, pdir) if item["references_missing"] else None
                row = {"id": identifier, "versions": [],
                       "references_attempted": future is not None,
                       "references_status": "verified_existing"}
                for version in item["source_versions"]:
                    try:
                        record = crawler.download_version(identifier, version, pdir)
                        event = next(e for e in reversed(events)
                                     if e["url"].endswith(f"/src/{identifier}v{version}"))
                        verified = event.get("validation", event["status"])
                        row["versions"].append({"version": version, "upstream": record,
                                                "verified_status": verified})
                    except Exception as exc:
                        row["versions"].append({"version": version, "verified_status": "error",
                                                "error_type": type(exc).__name__})
                if future is not None:
                    try:
                        total, with_arxiv = future.result()
                        row.update(references_status="not_found" if total is None else "received_unpaginated",
                                   references_total=total, references_with_arxiv=with_arxiv)
                    except Exception as exc:
                        row.update(references_status="error", reference_error=type(exc).__name__)
                row["complete_after"] = (all(v["verified_status"] in {"success", "non_tex"}
                    for v in row["versions"]) and row["references_status"] == "verified_existing")
                results.append(row)
                save("running")
                print(json.dumps({"visited": len(results), "total": len(plan), **row}), flush=True)
        crawler.throttle_report(round(time.monotonic() - started, 1))
        return save("finished")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upstream-ref", default="e5be40e")
    args = parser.parse_args()
    report = run_trial(args.cache, args.output, args.upstream_ref)
    print(json.dumps({k: v for k, v in report.items() if k not in {"results", "network_events"}}))


if __name__ == "__main__":
    main()
