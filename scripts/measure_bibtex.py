"""Measure M2.4b using Structure on the group's verified M2 sample plan."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import random
import subprocess
from time import perf_counter

from src.common.corpus import FileCorpus, file_digest
from src.common.json_io import write_json
from src.common.metrics import measure
from src.common.schema import from_records
from src.parse import types as shared_types
from src.parse.bibtex import BIBTEX_VERSION, merge_bibtex
from src.parse.source import assemble_source
from src.parse.structure import build_structure
from scripts.m2_sample import validate_plan, verify_sample


DEFAULT_SAMPLE = Path("configs/m2-sample-100.json")
_TOTALS = ("entry_before", "entry_after", "groups_before_filter", "groups_filtered_out",
           "from_bib", "from_bibitem", "unresolved", "field_conflicts", "versions_without_bibliography")


def run(data_dir: Path, size: int | None = None, seed: int | None = None,
        *, sample_path: Path | None = None) -> dict:
    """Measure a verified plan by default, retaining explicit seeded diagnostics.

    Passing size and seed is the legacy diagnostic API. The CLI always uses a
    shared plan, whose metadata, receipt inventory and checksums are verified
    before processing. Diagnostic runs are identified separately in the output.
    """
    corpus = FileCorpus(data_dir)
    plan = None
    if sample_path is not None or (size is None and seed is None):
        if size is not None or seed is not None:
            raise ValueError("A sample plan cannot be combined with size or seed")
        sample_path = Path(sample_path or DEFAULT_SAMPLE)
        plan = json.loads(sample_path.read_text(encoding="utf-8"))
        validate_plan(plan)
        verification = verify_sample(plan, data_dir)
        if verification["verified"] != verification["publications"]:
            failed = [row["arxiv_id"] for row in verification["results"] if row["status"] != "verified"]
            raise ValueError(f"Sample verification failed for {len(failed)} Publications: {', '.join(failed)}")
        sample = [item["arxiv_id"] for item in plan["publications"]]
        seed = plan["seed"]
    else:
        ids = sorted(path.stem.replace("-", ".") for path in (data_dir / "metadata").glob("*.json"))
        if size is None or seed is None or not 1 <= size <= len(ids):
            raise ValueError("Diagnostic sampling requires a valid size and seed")
        sample = sorted(random.Random(seed).sample(ids, size))
    totals = dict.fromkeys(_TOTALS, 0)
    versions, issues, source_issues, unresolved = Counter(), Counter(), Counter(), Counter()
    checks = Counter()
    invalid_metadata, partial, failures, entry_counts = [], [], [], []
    assembly_failures, structure_failures = [], []
    merge_seconds = repeat_seconds = 0.0

    with measure("bibtex sample") as timing:
        for arxiv_id in sample:
            try:
                publication = corpus.read_publication(arxiv_id)
            except (OSError, KeyError, TypeError, ValueError):
                invalid_metadata.append(arxiv_id)
                continue
            sources = []
            for version in range(1, publication.versions + 1):
                directory = corpus.version_path(arxiv_id, version)
                bundle = assemble_source(directory, require_receipt=True)
                versions[bundle.status] += 1
                source_issues.update(issue.code for issue in bundle.issues)
                if bundle.status == "error":
                    assembly_failures.append({
                        "arxiv_id": arxiv_id,
                        "version": version,
                        "codes": sorted({issue.code for issue in bundle.issues if issue.severity == "error"}),
                    })
                    continue
                try:
                    _, source = build_structure(bundle, arxiv_id, version, directory)
                except (OSError, ValueError, RecursionError) as error:
                    structure_failures.append({"arxiv_id": arxiv_id, "version": version,
                                               "error": str(error)})
                    continue
                sources.append(source)
                errors = shared_types.validate_B_prime(source, raise_on_error=False)
                checks["bib_source_failed" if errors else "bib_source_passed"] += 1
                if errors:
                    failures.append({"arxiv_id": arxiv_id, "version": version,
                                     "check": "validate_B_prime", "error_count": len(errors),
                                     "example": errors[0]})
            if len(sources) != publication.versions:
                partial.append(arxiv_id)
            if not sources:
                continue

            start = perf_counter()
            result = merge_bibtex(arxiv_id, sources)
            merge_seconds += perf_counter() - start
            for key in _TOTALS:
                totals[key] += result.stats[key]
            entry_counts.append({"arxiv_id": arxiv_id, "versions": len(sources),
                                 "entry_before": result.stats["entry_before"],
                                 "entry_after": result.stats["entry_after"]})
            issues.update(issue["code"] for issue in result.stats["issues"])
            unresolved.update(issue["reason"] for issue in result.stats["unresolved_keys"])
            checks["invalid_years"] += len(result.stats["invalid_years"])
            checks["publications_processed"] += 1
            checks["multi_version_publications_processed"] += len(sources) > 1
            blank_keys = sum(not row["citation_key"].strip() for row in result.entries)
            checks["blank_citation_key_entries"] += blank_keys
            checks["publications_with_blank_citation_keys"] += blank_keys > 0
            from_records(result.entries, "bibtex")
            checks["bibtex_schema_passed"] += 1
            errors = shared_types.validate_D(result, sources, raise_on_error=False)
            checks["bib_result_failed" if errors else "bib_result_passed"] += 1
            if errors:
                failures.append({"arxiv_id": arxiv_id, "check": "validate_D", "error_count": len(errors),
                                 "example": errors[0]})
            start = perf_counter()
            repeat = merge_bibtex(arxiv_id, list(reversed(sources)))
            repeat_seconds += perf_counter() - start
            if json.dumps(asdict(repeat)) != json.dumps(asdict(result)):
                raise ValueError(f"Unstable BibResult for {arxiv_id}")
            checks["repeatable_bib_results"] += 1

    return {
        "bibtex_version": BIBTEX_VERSION,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "sample": {"data_dir": data_dir.as_posix(), "size": len(sample), "seed": seed, "arxiv_ids": sample,
                   "plan": sample_path.as_posix() if plan is not None else None,
                   "plan_sha256": file_digest(sample_path) if plan is not None else None,
                   "data_origin": plan["data_origin"] if plan is not None else "diagnostic"},
        "input_method": "build_structure on receipt-verified assembled source",
        "versions_by_assembly_status": dict(versions),
        "versions_expected": sum(versions.values()),
        "invalid_metadata_publications": invalid_metadata,
        "publications_missing_assembled_versions": partial,
        "assembly_failures": assembly_failures,
        "structure_failures": structure_failures,
        **totals,
        "duplicates_removed": totals["entry_before"] - totals["groups_before_filter"],
        "largest_bibliographies": sorted(entry_counts, key=lambda row: -row["entry_before"])[:5],
        "unresolved_by_reason": dict(unresolved),
        "bibtex_issues_by_code": dict(issues),
        "source_issues_by_code": dict(source_issues),
        "checks": {
            "shared_types_available": True,
            "shared_types_sha256": file_digest(Path(shared_types.__file__)),
            **checks,
        },
        "boundary_failures": failures,
        "timing": {**timing.to_dict(), "merge_seconds": round(merge_seconds, 6),
                   "repeat_merge_seconds": round(repeat_seconds, 6)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--output", type=Path, default=Path("metrics/bibtex.json"))
    args = parser.parse_args()
    metrics = run(args.data_dir, sample_path=args.sample)
    write_json(args.output, metrics)
    print(args.output)


if __name__ == "__main__":
    main()
