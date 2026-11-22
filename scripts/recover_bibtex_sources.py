"""Recover archive bibliography into a receipt-bound Parser sidecar.

Downloads use export.arxiv.org, the project's paced HTTP client and a contact
User-Agent. Original corpus files remain the checksum baseline for every archive.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

from scripts.m2_sample import verify_sample
from src.common.config import get_settings
from src.common.corpus import FileCorpus, file_digest, safe_member, verified_source
from src.common.json_io import write_json
from src.common.schema import publication_key
from src.crawl.http_client import HttpClient
from src.parse.bibtex_input import build_bib_source, load_root_reviews


def prepare_sidecar(archive: Path, directory: Path, destination: Path) -> dict:
    """Check archive contents against M1, then atomically save bibliography files."""
    verified = verified_source(directory)
    if verified is None:
        raise ValueError("Original source receipt is invalid")
    receipt = json.loads((directory / "source.json").read_text(encoding="utf-8"))
    contents = {}
    hashes = {}
    with tarfile.open(archive, mode="r:*") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = PurePosixPath(member.name).as_posix().removeprefix("./")
            if PurePosixPath(name).suffix.lower() not in {".tex", ".bib", ".bbl"}:
                continue
            if not safe_member(name) or member.size > 128 * 1024 * 1024:
                raise ValueError("Unsafe archive bibliography member")
            raw = tar.extractfile(member).read()
            digest = hashlib.sha256(raw).hexdigest()
            if name in hashes and hashes[name] != digest:
                raise ValueError("Conflicting duplicate archive member")
            hashes[name] = digest
            if PurePosixPath(name).suffix.lower() in {".bib", ".bbl"}:
                contents[name] = raw
    mismatches = [name for name, digest in receipt["files"].items() if hashes.get(name) != digest]
    if mismatches:
        raise ValueError("Archive differs from original source: " + ", ".join(mismatches))
    manifest = {
        "format": 1, "arxiv_id": receipt["arxiv_id"], "version": receipt["version"],
        "receipt_sha256": file_digest(directory / "source.json"),
        "archive_sha256": file_digest(archive),
        "source_url": f"https://export.arxiv.org/src/{receipt['arxiv_id']}v{receipt['version']}",
        "files": {name: hashes[name] for name in sorted(contents)},
    }
    if destination.exists():
        existing = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        if existing != manifest or any(file_digest(destination / "files" / name) != hashes[name] for name in contents):
            raise ValueError("Existing supplement differs; use another output directory")
        return manifest
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bib-supplement-", dir=destination.parent) as stage_name:
        stage = Path(stage_name)
        for name, raw in contents.items():
            path = stage / "files" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        write_json(stage / "manifest.json", manifest)
        os.rename(stage, destination)
    return manifest


class _Fetcher:
    """One paced client for the whole run, created only when a download is needed."""

    def __init__(self, client=None):
        self.client = client

    def get(self, url):
        if self.client is None:
            self.client = HttpClient(get_settings().user_agent(), min_interval=3.0)
        return self.client.get(url, resume=True)


def _needs_recovery(bundle, source) -> bool:
    return bool(source.missing_bib) or any(issue.code == "missing_bbl" for issue in bundle.issues)


def _recover_version(aid: str, number: int, directory: Path, archive_dir: Path, output: Path,
                     fetcher: _Fetcher, *, review: dict | None = None, strict: bool = True,
                     skip_existing: bool = False, keep_archive: bool = True) -> dict | None:
    """Recover one Version; ``None`` when its compilation path declares no missing bibliography.

    ``strict`` raises on an archive that differs from the M1 receipt (sample mode);
    otherwise the Version is recorded as ``archive_mismatch`` and the run continues.
    """
    destination = output / publication_key(aid) / f"v{number}"
    if skip_existing and (destination / "manifest.json").is_file():
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        return {"arxiv_id": aid, "version": number, "status": "verified", "resumed": True,
                "files": list(manifest["files"]), "archive_sha256": manifest["archive_sha256"]}
    bundle, source, _ = build_bib_source(aid, number, directory, root_review=review)
    if source is None:
        return {"arxiv_id": aid, "version": number, "status": "source_failed"}
    if not _needs_recovery(bundle, source):
        return None
    archive = archive_dir / f"{aid}v{number}.source"
    if not archive.exists():
        response = fetcher.get(f"https://export.arxiv.org/src/{aid}v{number}")
        if response.status != 200:
            return {"arxiv_id": aid, "version": number, "status": "http_error", "http_status": response.status}
        archive.write_bytes(response.body)
    try:
        manifest = prepare_sidecar(archive, directory, destination)
    except ValueError as error:
        if strict:
            raise
        return {"arxiv_id": aid, "version": number, "status": "archive_mismatch", "error": str(error)}
    if not keep_archive:
        archive.unlink()
    print(f"Recovered {aid}v{number}: {len(manifest['files'])} bibliography files", flush=True)
    return {"arxiv_id": aid, "version": number, "status": "verified",
            "files": list(manifest["files"]), "archive_sha256": manifest["archive_sha256"]}


def _report(output: Path, records: list[dict]) -> dict:
    report = {"verified": sum(row["status"] == "verified" for row in records),
              "by_status": dict(sorted(Counter(row["status"] for row in records).items())),
              "versions": records}
    write_json(output / "recovery-report.json", report)
    return report


def recover(plan: dict, corpus: Path, archive_dir: Path, output: Path, *,
            roots: dict | None = None, client=None) -> dict:
    """Fetch only Versions whose compilation path declares missing bibliography."""
    verified = verify_sample(plan, corpus)
    if verified["verified"] != verified["publications"]:
        raise ValueError("Verify the original sample before bibliography recovery")
    roots = roots or {}
    archive_dir.mkdir(parents=True, exist_ok=True)
    fetcher = _Fetcher(client)
    records = []
    for paper in plan["publications"]:
        aid = paper["arxiv_id"]
        for version in paper["versions"]:
            number = version["version"]
            directory = corpus / "raw" / publication_key(aid) / f"v{number}"
            record = _recover_version(aid, number, directory, archive_dir, output, fetcher,
                                      review=roots.get((aid, number)))
            if record is not None:
                records.append(record)
    return _report(output, records)


def recover_corpus(corpus: Path, archive_dir: Path, output: Path, *, ids: list[str] | None = None,
                   roots: dict | None = None, client=None, keep_archives: bool = True) -> dict:
    """Range mode: every Publication in ``corpus/metadata`` (or ``ids``), without a sample plan.

    Each Version is still checked against its M1 receipt: ``verified_source`` must accept the
    directory and every receipt file must match the archive (``prepare_sidecar``). Versions with
    an existing sidecar are skipped, so an interrupted run resumes; a mismatching archive is
    reported instead of stopping the Range.
    """
    files = FileCorpus(corpus)
    roots = roots or {}
    archive_dir.mkdir(parents=True, exist_ok=True)
    fetcher = _Fetcher(client)
    if ids is None:
        ids = sorted(json.loads(path.read_text(encoding="utf-8"))["publication"]["arxiv_id"]
                     for path in sorted((corpus / "metadata").glob("*.json")))
    records = []
    for aid in ids:
        for number in range(1, files.read_publication(aid).versions + 1):
            directory = files.version_path(aid, number)
            if verified_source(directory) is None:
                records.append({"arxiv_id": aid, "version": number, "status": "source_missing"})
                continue
            if verified_source(directory).status != "success":
                continue
            record = _recover_version(aid, number, directory, archive_dir, output, fetcher,
                                      review=roots.get((aid, number)), strict=False,
                                      skip_existing=True, keep_archive=keep_archives)
            if record is not None:
                records.append(record)
    return _report(output, records)


def main():
    """Create reproducible sidecars while retaining cached archive bytes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=Path("configs/m2-sample-100.json"))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--roots", type=Path)
    parser.add_argument("--all", action="store_true",
                        help="Range mode: every Publication in --data-dir/metadata, no sample plan")
    parser.add_argument("--delete-archives", action="store_true",
                        help="Range mode: remove each archive after its sidecar is written")
    args = parser.parse_args()
    if args.all:
        result = recover_corpus(args.data_dir, args.archive_dir, args.output_dir,
                                roots=load_root_reviews(args.roots), keep_archives=not args.delete_archives)
    else:
        plan = json.loads(args.sample.read_text(encoding="utf-8"))
        result = recover(plan, args.data_dir, args.archive_dir, args.output_dir,
                         roots=load_root_reviews(args.roots))
    print(json.dumps({"verified_supplements": result["verified"], "by_status": result.get("by_status")}))


if __name__ == "__main__":
    main()
