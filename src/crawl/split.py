"""Independent arXiv/S2 jobs, verified cache import and offline final export.

Each job owns its own directory. Mounted Kaggle inputs are read-only: loading
their manifests must never truncate an interrupted final line or create locks.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import shutil
import time
import zipfile

from filelock import FileLock

from src.common.schema import from_records, write_table
from .batched import BatchedDiscovery
from .http_client import HttpClient
from .manifest import Manifest, TaskRecord
from .pipeline import CrawlPipeline
from .semantic_scholar import SemanticScholarClient, reference_rows
from .source import ArxivSourceDownloader, verified_source
from .storage import key, require_id, write_json


def read_cache(root):
    """Construct a read-only cache view, tolerating only a torn final log line."""
    root = Path(root)
    manifest = object.__new__(Manifest)
    manifest.path = root / "manifests/crawl.jsonl"
    manifest.records = {}
    if manifest.path.exists():
        lines = manifest.path.read_bytes().splitlines()
        for index, line in enumerate(lines):
            try:
                record = TaskRecord(**json.loads(line))
                require_id(record.arxiv_id)
            except (ValueError, TypeError, UnicodeError):
                if index != len(lines) - 1:
                    raise ValueError(f"Corrupt manifest: {manifest.path}") from None
                break
            manifest.records[record.key] = record
    view = object.__new__(CrawlPipeline)
    view.data_dir, view.manifest = root, manifest
    view.sources = ArxivSourceDownloader(None, root / "raw")
    return view


def import_cache(roots, destination, identifiers, stage="all"):
    """Copy verified components; retain valid destination files on rerun.

    Among input snapshots, try the newest successful record first. Corrupt
    candidates fall back to older valid copies. Original inputs are untouched.
    Source Versions are imported individually even if S2 or another Version
    failed. Call only on immutable snapshots or while holding source locks.
    """
    if stage not in {"all", "arxiv", "s2"}:
        raise ValueError("Unknown stage")
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    wanted = set(identifiers)
    kinds = {"discovery", "source", "references"} if stage == "all" else (
        {"references"} if stage == "s2" else {"discovery", "source"})
    candidates = {}
    for source_root in roots:
        if Path(source_root).resolve() == root.resolve():
            continue
        view = read_cache(source_root)
        for record in view.manifest.records.values():
            if record.arxiv_id in wanted and record.kind in kinds and record.status in {"success", "non_tex"}:
                candidates.setdefault(record.key, []).append((record, view))
    copied = 0
    with FileLock(str(root / ".pipeline.lock"), timeout=0), FileLock(str(root / ".crawl.lock"), timeout=0):
        output = read_cache(root)
        # Repair only our writable destination's torn final record.
        output.manifest = Manifest(root / "manifests/crawl.jsonl")
        for task_key, choices in candidates.items():
            choices.sort(key=lambda item: item[0].updated_at or "", reverse=True)
            existing = output.manifest.get(*task_key)
            if existing and _valid_component(output, existing):
                continue
            for record, view in choices:
                if not _valid_component(view, record):
                    continue
                if record.kind == "source":
                    relative = Path("raw") / key(record.arxiv_id) / f"v{record.version}"
                    source = view.data_dir / relative
                    receipt = json.loads((source / "source.json").read_text(encoding="utf-8"))
                    target = root / relative
                    # Replace only the exact invalid Version in the destination.
                    if target.exists():
                        if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
                            raise ValueError("Unsafe destination")
                        shutil.rmtree(target)
                    target.mkdir(parents=True)
                    for name in [*receipt["files"], "source.json"]:
                        path = target / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source / name, path)
                else:
                    folder = "metadata" if record.kind == "discovery" else "references"
                    relative = Path(folder) / f"{key(record.arxiv_id)}.json"
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(view.data_dir / relative, target)
                output.manifest.upsert(replace(record, local_path=str(target)))
                copied += 1
                if copied % 100 == 0:
                    print(f'[{stage}] Imported {copied}/{len(candidates)} candidate components', flush=True)
                break
        write_json(root / "manifests/import-report.json", {"copied_components": copied,
            "stage": stage, "candidate_components": len(candidates)})
    return copied


def _valid_component(view, record):
    try:
        if record.kind == "discovery":
            view._load_publication(record.arxiv_id)
        elif record.kind == "references":
            view._load_references(record.arxiv_id)
        elif record.kind == "source":
            if type(record.version) is not int or record.version < 1:
                return False
            result = verified_source(view.sources.root / key(record.arxiv_id) / f"v{record.version}")
            return bool(result and result.status == record.status and result.checksum == record.checksum)
        else:
            return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def ready(view, identifier, stage):
    """Verify just the service this worker owns, independently of the other."""
    try:
        if stage == "s2":
            view._load_references(identifier)
            return True
        publication = view._load_publication(identifier)
        return all((record := view.manifest.get(identifier, version)) is not None
                   and _valid_component(view, record)
                   for version in range(1, publication.versions + 1))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def make_pipeline(settings, stage):
    """S2-only mode never contacts arXiv; arXiv-only mode never contacts S2."""
    if stage not in {"arxiv", "s2"}:
        raise ValueError("Unknown stage")
    arxiv = HttpClient(settings.user_agent(), min_interval=3.1)
    refs = SemanticScholarClient(HttpClient(settings.user_agent(),
        min_interval=1.1 if settings.s2_api_key else 3.1,
        headers={"x-api-key": settings.s2_api_key} if settings.s2_api_key else {}))
    return CrawlPipeline(BatchedDiscovery(arxiv),
        ArxivSourceDownloader(arxiv, settings.data_dir / "raw"), settings.data_dir,
        refs if stage == "s2" else None)


def run_stage(pipeline, identifiers, stage, *, max_seconds=9*3600, max_passes=3,
              retry_delay=1800, export_every=100, clock=time.monotonic, sleeper=time.sleep):
    """Bounded notebook session with periodic tables and per-task receipts.

    Source hashes are verified on startup and after changed Publications only,
    rather than rehashing the whole corpus at every periodic Parquet export.
    Tables here are service-specific partial outputs. merge_results enforces
    the original complete-Publication contract for the final pair of tables.
    """
    if stage not in {"arxiv", "s2"} or max_seconds <= 0 or max_passes < 1 or export_every < 1 or retry_delay < 0:
        raise ValueError("Invalid job settings")
    ids = list(dict.fromkeys(require_id(i) for i in identifiers))
    root = pipeline.data_dir
    deadline = clock() + max_seconds
    states, rows = {}, {}
    status_path = root / "manifests" / f"{stage}-run.json"
    def save(status):
        report = {"stage": stage, "status": status, "requested": len(ids),
                  "complete": sum(states.values()), "pending_ids": [i for i in ids if not states.get(i)]}
        write_json(status_path, report)
        return report
    def remember(identifier):
        states[identifier] = ready(pipeline, identifier, stage)
        if states[identifier]:
            if stage == "arxiv":
                row = asdict(pipeline._load_publication(identifier))
                row.pop("versions")
                rows[identifier] = [row]
            else:
                rows[identifier] = reference_rows(identifier, pipeline._load_references(identifier))
    def export():
        name = "papers" if stage == "arxiv" else "references"
        write_table(from_records([r for i in ids for r in rows.get(i, [])], name),
                    name, root / "tables" / f"{name}.parquet")
    def check_stop():
        if (root / "STOP_RANGE").exists():
            raise InterruptedError("stop requested")
        if clock() >= deadline:
            raise InterruptedError("session budget reached")
    with FileLock(str(root / ".pipeline.lock"), timeout=0):
        job_path = root / "manifests/job.json"
        job = {"stage": stage, "ids": ids}
        if job_path.exists() and json.loads(job_path.read_text(encoding="utf-8")) != job:
            raise ValueError("Different stage/Range in output directory")
        write_json(job_path, job)
        pipeline.manifest = Manifest(pipeline.manifest.path)
        save("checking_cache")
        try:
            print(f'[{stage}] Verifying {len(ids)} cached Publication IDs...', flush=True)
            for checked, identifier in enumerate(ids, 1):
                check_stop()
                remember(identifier)
                if checked % 100 == 0:
                    print(f'[{stage}] Checked {checked}/{len(ids)}; complete={sum(states.values())}', flush=True)
            export()
            for pass_no in range(1, max_passes + 1):
                pending = [i for i in ids if not states.get(i)]
                for position, identifier in enumerate(pending):
                    check_stop()
                    save("running")
                    print(f"[{stage} pass {pass_no}] {identifier}; complete={sum(states.values())}/{len(ids)}", flush=True)
                    if stage == "arxiv":
                        if position % 50 == 0:
                            missing = []
                            for item in pending[position:position+50]:
                                try:
                                    pipeline._load_publication(item)
                                except (OSError, ValueError, KeyError, TypeError):
                                    missing.append(item)
                            pipeline.discovery.prefetch(missing)
                        pipeline.crawl_ids([identifier])
                    else:
                        try:
                            result = pipeline.references.references(identifier)
                            reference_rows(identifier, result)
                            path = pipeline._references_path(identifier)
                            write_json(path, {"format": 1, "arxiv_id": identifier, "rows": result})
                            pipeline._record(identifier, None, "references", "success",
                                checksum=hashlib.sha256(path.read_bytes()).hexdigest(), local_path=str(path))
                        except Exception as error:
                            pipeline._failure(identifier, None, "references", error)
                            print(f'[s2] Failed {identifier}: {type(error).__name__}; HTTP={getattr(error, "status", None)}', flush=True)
                    remember(identifier)
                    save("running")
                    if (position+1) % export_every == 0:
                        export()
                export()
                if all(states.get(i) for i in ids):
                    return save("complete")
                if pass_no < max_passes:
                    save("retry_wait")
                    print(f'[{stage}] Waiting {retry_delay}s before next retry pass.', flush=True)
                    remaining = retry_delay
                    while remaining > 0:
                        check_stop()
                        delay = min(30, remaining)
                        sleeper(delay)
                        remaining -= delay
            return save("incomplete")
        except (KeyboardInterrupt, InterruptedError):
            # Existing task receipts survive even if interrupted during export.
            report = save("stopped")
            export()
            return report
        except Exception:
            save("failed")
            raise


def archive_cache(root, archive_path):
    """Write a portable checkpoint ZIP containing only crawler output files."""
    root, target = Path(root), Path(archive_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for folder in ("raw", "metadata", "references", "manifests", "tables"):
            for path in sorted((root / folder).rglob("*")):
                if path.is_file() and not path.is_symlink():
                    archive.write(path, path.relative_to(root).as_posix())
    temporary.replace(target)
    return target


def unpack_cache(archive_path, destination):
    """Extract checkpoint ZIP after rejecting traversal, links and drive paths."""
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if (":" in info.filename or "\\" in info.filename
                    or not (root / info.filename).resolve().is_relative_to(root)
                    or (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Unsafe checkpoint archive")
        archive.extractall(root)
    return root


def merge_results(roots, destination, identifiers):
    """Offline verified merge; export only Publications complete on both sides."""
    ids = list(identifiers)
    import_cache(roots, destination, ids)
    view = read_cache(destination)
    with FileLock(str(Path(destination) / ".pipeline.lock"), timeout=0):
        bundles, _ = view.export(ids)
        complete = {bundle["publication"].arxiv_id for bundle in bundles}
        report = {"requested": len(ids), "complete": len(complete),
                  "pending_ids": [i for i in ids if i not in complete]}
        write_json(Path(destination) / "manifests/merge-report.json", report)
    return report
