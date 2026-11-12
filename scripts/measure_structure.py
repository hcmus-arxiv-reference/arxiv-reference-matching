"""Measure Source and Structure on every Version in an M2 sample plan."""
import argparse
from collections import Counter
import json
from pathlib import Path
from time import perf_counter

from src.common.corpus import file_digest
from src.common.json_io import write_json
from src.common.schema import publication_key
from src.parse.source import assemble_source
from src.parse.structure import build_structure
from src.parse.types import Section, validate_B, validate_B_prime


def measure_sample(plan, corpus):
    """Verify planned receipts, keeping failures visible in all denominators."""
    started = perf_counter()
    statuses, codes, headings = Counter(), Counter(), Counter()
    failures = []
    without_section = tex = ready = parsed = 0

    def count(section, counts):
        for child in section.children:
            if isinstance(child, Section):
                counts[child.kind] += 1
                count(child, counts)

    seen = set()
    for paper in plan["publications"]:
        aid = paper["arxiv_id"]
        if aid in seen or not paper["versions"]:
            raise ValueError(f"Duplicate Publication or empty Version list: {aid}")
        seen.add(aid)
        per_paper = Counter()
        complete = True
        has_tex = False
        for expected, entry in enumerate(paper["versions"], 1):
            version = entry["version"]
            if version != expected or entry["status"] not in {"success", "non_tex"}:
                raise ValueError(f"Invalid planned Version: {aid}v{version}")
            directory = corpus / "raw" / publication_key(aid) / f"v{version}"
            if file_digest(directory / "source.json") != entry["receipt_sha256"]:
                raise ValueError(f"Receipt differs from plan: {aid}v{version}")
            source = assemble_source(directory, require_receipt=True)
            statuses[source.status] += 1
            codes.update(issue.code for issue in source.issues)
            if entry["status"] == "success":
                tex += 1
                has_tex = True
                ready += source.status == "ready"
            if source.status == "empty_non_tex":
                continue
            try:
                tree, bib = build_structure(source, aid, version, directory)
                validate_B(tree, source.text)
                validate_B_prime(bib)
            except (ValueError, OSError, RecursionError) as error:
                failures.append({"arxiv_id": aid, "version": version, "error": str(error)})
                complete = False
                continue
            count(tree.root, per_paper)
            parsed += 1
        headings.update(per_paper)
        without_section += has_tex and complete and not per_paper["section"]
    return {"data_origin": plan["data_origin"], "publications": len(seen),
            "versions_by_status": dict(statuses), "source_issue_counts": dict(codes),
            "tex_versions": tex, "ready_tex_versions": ready,
            "ready_tex_fraction": ready / tex if tex else None,
            "structure_versions_validated": parsed, "structure_failures": failures,
            "headings_by_kind": dict(headings),
            "fully_parsed_tex_publications_without_section": without_section,
            "elapsed_seconds": round(perf_counter() - started, 3)}


def main():
    """Write the aggregate only after processing the entire plan."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if plan["data_origin"] != "corpus" and args.output.name == "structure.json":
        parser.error("Use a distinct output name for diagnostic or mock samples")
    result = measure_sample(plan, args.corpus)
    result["plan_sha256"] = file_digest(args.plan)
    write_json(args.output, result)


if __name__ == "__main__":
    main()
