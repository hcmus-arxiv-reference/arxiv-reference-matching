"""Recover archive bibliography into a receipt-bound Parser sidecar.

Downloads use export.arxiv.org, the project's paced HTTP client and a contact
User-Agent. Original corpus files remain the checksum baseline for every archive.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

from scripts.m2_sample import verify_sample
from src.common.config import get_settings
from src.common.corpus import file_digest, safe_member, verified_source
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


def recover(plan: dict, corpus: Path, archive_dir: Path, output: Path, *,
            roots: dict | None = None, client=None) -> dict:
    """Fetch only Versions whose compilation path declares missing bibliography."""
    verified = verify_sample(plan, corpus)
    if verified["verified"] != verified["publications"]:
        raise ValueError("Verify the original sample before bibliography recovery")
    roots = roots or {}
    archive_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for paper in plan["publications"]:
        aid = paper["arxiv_id"]
        for version in paper["versions"]:
            number = version["version"]
            directory = corpus / "raw" / publication_key(aid) / f"v{number}"
            bundle, source, _ = build_bib_source(aid, number, directory, root_review=roots.get((aid, number)))
            if source is None:
                records.append({"arxiv_id": aid, "version": number, "status": "source_failed"})
                continue
            if not source.missing_bib and not any(issue.code == "missing_bbl" for issue in bundle.issues):
                continue
            archive = archive_dir / f"{aid}v{number}.source"
            if not archive.exists():
                if client is None:
                    client = HttpClient(get_settings().user_agent(), min_interval=3.0)
                response = client.get(f"https://export.arxiv.org/src/{aid}v{number}", resume=True)
                if response.status != 200:
                    records.append({"arxiv_id": aid, "version": number,
                                    "status": "http_error", "http_status": response.status})
                    continue
                archive.write_bytes(response.body)
            destination = output / publication_key(aid) / f"v{number}"
            manifest = prepare_sidecar(archive, directory, destination)
            records.append({"arxiv_id": aid, "version": number, "status": "verified",
                            "files": list(manifest["files"]), "archive_sha256": manifest["archive_sha256"]})
            print(f"Recovered {aid}v{number}: {len(manifest['files'])} bibliography files", flush=True)
    report = {"verified": sum(row["status"] == "verified" for row in records), "versions": records}
    write_json(output / "recovery-report.json", report)
    return report


def main():
    """Create reproducible sidecars while retaining cached archive bytes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=Path("configs/m2-sample-100.json"))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--roots", type=Path)
    args = parser.parse_args()
    plan = json.loads(args.sample.read_text(encoding="utf-8"))
    result = recover(plan, args.data_dir, args.archive_dir, args.output_dir,
                     roots=load_root_reviews(args.roots))
    print(json.dumps({"verified_supplements": result["verified"]}))


if __name__ == "__main__":
    main()
