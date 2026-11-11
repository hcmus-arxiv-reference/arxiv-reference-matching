"""Create, download and verify the shared M2 sample (docs/m2-cong-viec.md §4.4).

Raw files remain outside Git. Plans contain IDs, Version inventory and hashes only.
HF downloads use one resolved revision per run:
https://huggingface.co/docs/huggingface_hub/en/guides/download
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import re
import tempfile

from src.common.config import Settings, get_settings, member_ids
from src.common.corpus import FileCorpus, file_digest, verified_source
from src.common.hf_io import download_dir, raw_prefix
from src.common.json_io import write_json
from src.common.schema import publication_key

SAMPLE_VERSION = "1"
DEFAULT_SEED = 20261112


def make_plan(corpus_dir: Path, *, size: int = 100, seed: int = DEFAULT_SEED,
              hf_member: str = "bao") -> dict:
    """Sample all-source-verified Publications uniformly, including non-TeX Versions.

    References are not an M2 input, so their availability does not filter the sample.
    Hashes bind a plan to the exact metadata and receipts used during selection.
    """
    if size < 1:
        raise ValueError("Sample size must be positive")
    raw_prefix(hf_member, "2508.02872")
    if not (corpus_dir / "metadata").is_dir() or not (corpus_dir / "raw").is_dir():
        raise ValueError("Corpus needs metadata/ and raw/ (local M1 layout)")
    corpus = FileCorpus(corpus_dir)
    eligible = []
    excluded = Counter()
    for arxiv_id in sorted(member_ids("bao")):
        metadata = corpus.metadata_path(arxiv_id)
        if not metadata.exists():
            excluded["missing_metadata"] += 1
            continue
        try:
            publication = corpus.read_publication(arxiv_id)
        except (OSError, ValueError, KeyError, TypeError):
            excluded["invalid_metadata"] += 1
            continue
        versions = []
        for version in range(1, publication.versions + 1):
            directory = corpus.version_path(arxiv_id, version)
            source = verified_source(directory)
            if source is None:
                break
            versions.append({
                "version": version, "status": source.status,
                "path_in_repo": raw_prefix(hf_member, arxiv_id, version),
                "receipt_sha256": file_digest(directory / "source.json"),
            })
        if len(versions) != publication.versions:
            excluded["missing_or_invalid_source"] += 1
            continue
        eligible.append({"arxiv_id": arxiv_id, "metadata_sha256": file_digest(metadata),
                         "versions": versions})
    if len(eligible) < size:
        raise ValueError(f"Need {size} eligible Publications, found {len(eligible)}; "
                         f"excluded={dict(sorted(excluded.items()))}")
    population = "\n".join(item["arxiv_id"] for item in eligible) + "\n"
    chosen = random.Random(seed).sample(eligible, size)
    return {
        "format": 1, "sample_version": SAMPLE_VERSION, "seed": seed,
        "data_origin": "corpus",
        "range_member": "bao", "hf_member": hf_member, "sample_size": size,
        "selection": "valid_metadata_and_all_verified_sources",
        "population_count": len(eligible),
        "population_ids_sha256": hashlib.sha256(population.encode()).hexdigest(),
        "excluded": dict(sorted(excluded.items())),
        "publications": sorted(chosen, key=lambda item: item["arxiv_id"]),
    }


def make_mock(corpus_dir: Path, *, size: int = 100, seed: int = DEFAULT_SEED) -> dict:
    """Build explicitly synthetic M1 data for an offline demonstration, never real results."""
    if corpus_dir.exists() and any(corpus_dir.iterdir()):
        raise ValueError("Mock destination must be empty; existing data will not be overwritten")
    if not 1 <= size <= len(list(member_ids("bao"))):
        raise ValueError("Mock sample size must be between 1 and 5000")
    ids = sorted(random.Random(seed).sample(sorted(member_ids("bao")), size))
    for index, arxiv_id in enumerate(ids):
        key = publication_key(arxiv_id)
        versions = index % 3 + 1
        metadata = {"format": 1, "publication": {
            "arxiv_id": arxiv_id, "title": "Synthetic M2 sample (mock)",
            "authors": ["Example Author"], "submission_date": "2025-08-04",
            "revised_dates": ["2025-08-05"] * (versions - 1), "venue": None,
            "versions": versions,
        }}
        write_json(corpus_dir / "metadata" / f"{key}.json", metadata)
        for version in range(1, versions + 1):
            directory = corpus_dir / "raw" / key / f"v{version}"
            directory.mkdir(parents=True)
            non_tex = index % 5 == 0 and version == versions
            files = {}
            if not non_tex:
                text = (r"\documentclass{article}\begin{document}\section{Example}" + "\n"
                        + f"Synthetic Publication {index}, Version {version}.\n"
                        + r"\end{document}" + "\n")
                (directory / "main.tex").write_text(text, encoding="utf-8")
                files["main.tex"] = file_digest(directory / "main.tex")
            write_json(directory / "source.json", {
                "format": 1, "arxiv_id": arxiv_id, "version": version,
                "status": "non_tex" if non_tex else "success", "files": files,
                "checksum": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            })
            write_json(directory / "metadata.json", metadata)
    plan = make_plan(corpus_dir, size=size, seed=seed)
    plan["data_origin"] = "mock"
    return plan


def validate_plan(plan: dict) -> None:
    """Reject ambiguous IDs, incomplete Version inventories and unsafe HF paths."""
    if plan["format"] != 1 or plan["sample_version"] != SAMPLE_VERSION:
        raise ValueError("Unsupported sample plan version")
    if plan["range_member"] != "bao":
        raise ValueError("This M2 sample must use Bao's Range")
    if plan["data_origin"] not in {"mock", "corpus"}:
        raise ValueError("Plan must distinguish mock data from a real corpus")
    publications = plan["publications"]
    if not publications or plan["sample_size"] != len(publications):
        raise ValueError("Sample size does not match Publication inventory")
    ids = [item["arxiv_id"] for item in publications]
    if len(set(ids)) != len(ids) or not set(ids) <= set(member_ids("bao")):
        raise ValueError("Duplicate ID or Publication outside Bao's Range")
    for item in publications:
        versions = item["versions"]
        if not versions or [v["version"] for v in versions] != list(range(1, len(versions) + 1)):
            raise ValueError(f"{item['arxiv_id']}: Versions must be contiguous from v1")
        for entry in versions:
            expected = raw_prefix(plan["hf_member"], item["arxiv_id"], entry["version"])
            if entry["path_in_repo"] != expected or entry["status"] not in {"success", "non_tex"}:
                raise ValueError(f"{item['arxiv_id']}: invalid Version path/status")
        hashes = [item["metadata_sha256"], *(v["receipt_sha256"] for v in versions)]
        if any(not isinstance(h, str) or re.fullmatch(r"[0-9a-f]{64}", h) is None for h in hashes):
            raise ValueError(f"{item['arxiv_id']}: invalid SHA-256")


def verify_publication(item: dict, directory: Path, metadata: Path) -> None:
    """Verify source bytes, receipts and all replicated HF metadata against the plan."""
    arxiv_id = item["arxiv_id"]
    if file_digest(metadata) != item["metadata_sha256"]:
        raise ValueError(f"{arxiv_id}: metadata differs from plan")
    publication = FileCorpus(directory.parent).read_publication(arxiv_id, metadata.read_bytes())
    if publication.versions != len(item["versions"]):
        raise ValueError(f"{arxiv_id}: metadata Version count differs from plan")
    for entry in item["versions"]:
        version_dir = directory / f"v{entry['version']}"
        source = verified_source(version_dir)
        if source is None or source.status != entry["status"]:
            raise ValueError(f"{arxiv_id}v{entry['version']}: missing or invalid source")
        if file_digest(version_dir / "source.json") != entry["receipt_sha256"]:
            raise ValueError(f"{arxiv_id}v{entry['version']}: receipt differs from plan")
        if file_digest(version_dir / "metadata.json") != item["metadata_sha256"]:
            raise ValueError(f"{arxiv_id}v{entry['version']}: replicated metadata differs from plan")


def verify_sample(plan: dict, data_dir: Path) -> dict:
    """Check every expected Version offline; retain per-Publication failure details."""
    validate_plan(plan)
    results = []
    for item in plan["publications"]:
        key = publication_key(item["arxiv_id"])
        try:
            verify_publication(item, data_dir / "raw" / key,
                               data_dir / "metadata" / f"{key}.json")
        except (OSError, ValueError, KeyError, TypeError) as error:
            results.append({"arxiv_id": item["arxiv_id"], "status": "failed",
                            "error": str(error) if isinstance(error, ValueError) else type(error).__name__})
        else:
            results.append({"arxiv_id": item["arxiv_id"], "status": "verified"})
    return {"publications": len(results),
            "data_origin": plan["data_origin"],
            "versions": sum(len(item["versions"]) for item in plan["publications"]),
            "non_tex_versions": sum(v["status"] == "non_tex" for item in plan["publications"]
                                    for v in item["versions"]),
            "verified": sum(row["status"] == "verified" for row in results), "results": results}


def download_sample(plan: dict, settings: Settings, data_dir: Path,
                    *, revision: str | None = None) -> dict:
    """Stage and verify each Publication before moving it into local M1 layout.

    Existing Publications are verified and reused, never overwritten. An interrupted
    run can be retried; a mismatching local Publication requires a new destination.
    """
    validate_plan(plan)
    if plan["data_origin"] == "mock":
        raise ValueError("Mock plan cannot download real HF data; create a real plan with make-plan")
    data_dir.mkdir(parents=True, exist_ok=True)
    resolved_revision = None
    for item in plan["publications"]:
        key = publication_key(item["arxiv_id"])
        destination = data_dir / "raw" / key
        metadata = data_dir / "metadata" / f"{key}.json"
        if metadata.exists() and file_digest(metadata) != item["metadata_sha256"]:
            raise ValueError(f"{item['arxiv_id']}: existing metadata differs; use a new data directory")
        if destination.exists():
            verify_publication(item, destination, destination / "v1" / "metadata.json")
        else:
            # Resolve only if a download is needed: a complete rerun works offline.
            if resolved_revision is None:
                from huggingface_hub import HfApi

                settings.require_hf()
                try:
                    info = HfApi(token=settings.hf_token).repo_info(
                        repo_id=settings.hf_repo_id, repo_type="dataset", revision=revision)
                except Exception as error:
                    raise ValueError(f"HF metadata request failed: {type(error).__name__}") from None
                if not info.sha:
                    raise ValueError("HF dataset has no resolved revision")
                resolved_revision = info.sha
            with tempfile.TemporaryDirectory(prefix=".m2-download-", dir=data_dir) as temporary:
                try:
                    downloaded = download_dir(settings, raw_prefix(plan["hf_member"], item["arxiv_id"]),
                                              temporary, revision=resolved_revision)
                except Exception as error:
                    raise ValueError(f"{item['arxiv_id']}: HF download failed: {type(error).__name__}") from None
                verify_publication(item, downloaded, downloaded / "v1" / "metadata.json")
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.rename(downloaded, destination)
        source_metadata = destination / "v1" / "metadata.json"
        if not metadata.exists():
            metadata.parent.mkdir(parents=True, exist_ok=True)
            metadata.write_bytes(source_metadata.read_bytes())
    report = verify_sample(plan, data_dir)
    report["hf_revision"] = resolved_revision
    return report


def main(argv=None) -> int:
    """CLI: make-plan from local verified M1 data, download from HF, verify offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    mock = commands.add_parser("mock", help="Generate synthetic data and a clearly marked mock plan")
    mock.add_argument("--data-dir", type=Path, required=True)
    mock.add_argument("--output", type=Path, required=True)
    mock.add_argument("--size", type=int, default=100)
    mock.add_argument("--seed", type=int, default=DEFAULT_SEED)
    create = commands.add_parser("make-plan", help="Select a seeded sample from local M1 data")
    create.add_argument("--corpus", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--size", type=int, default=100)
    create.add_argument("--seed", type=int, default=DEFAULT_SEED)
    create.add_argument("--hf-member", default="bao", help="Source member directory on HF")
    for name in ("download", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--data-dir", type=Path, required=True)
        if name == "download":
            command.add_argument("--revision", help="Optional HF commit/tag; resolved once per run")
    args = parser.parse_args(argv)
    try:
        if args.command == "mock":
            if args.output.resolve().is_relative_to(args.data_dir.resolve()):
                parser.error("Keep plan output outside the mock source corpus")
            plan = make_mock(args.data_dir, size=args.size, seed=args.seed)
            write_json(args.output, plan)
            print(json.dumps({"data_origin": "mock", "publications": plan["sample_size"],
                              "seed": plan["seed"]}))
            return 0
        if args.command == "make-plan":
            if args.output.resolve().is_relative_to(args.corpus.resolve()):
                parser.error("Keep plan output outside the source corpus")
            plan = make_plan(args.corpus, size=args.size, seed=args.seed, hf_member=args.hf_member)
            validate_plan(plan)
            write_json(args.output, plan)
            print(json.dumps({"data_origin": plan["data_origin"],
                              "publications": plan["sample_size"], "seed": plan["seed"],
                              "versions": sum(len(p["versions"]) for p in plan["publications"])}))
            return 0
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        report = (download_sample(plan, get_settings(), args.data_dir, revision=args.revision)
                  if args.command == "download" else verify_sample(plan, args.data_dir))
        write_json(args.data_dir / "sample-report.json", report)
        print(json.dumps({k: v for k, v in report.items() if k != "results"}))
        return 0 if report["verified"] == report["publications"] else 2
    except (OSError, ValueError, KeyError, TypeError) as error:
        # SDK errors may contain credentials/headers; only our validation messages are printed.
        if type(error) is ValueError:
            print(f"M2 sample: {error}")
        else:
            print(f"M2 sample failed: {type(error).__name__}")
        return 2
    except Exception as error:
        response = getattr(error, "response", None)
        print(f"HF download failed: {type(error).__name__} (HTTP {getattr(response, 'status_code', None)})")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
