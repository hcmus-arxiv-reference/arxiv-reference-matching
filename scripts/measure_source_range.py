"""Measure Source readiness for every published Version in a pinned Bao snapshot."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

from src.common.json_io import write_json
from src.parse.source import ASSEMBLER_VERSION, assemble_source


def inspect_version(directory):
    """Keep receipt status independent of the parser outcome."""
    receipt = json.loads((directory / "source.json").read_bytes())
    bundle = assemble_source(directory, require_receipt=True)
    if any(issue.code in {"invalid_receipt", "source_changed"} for issue in bundle.issues):
        raise ValueError(f"Unverified Version: {directory}")
    return {"publication": directory.parent.name, "version": directory.name,
            "tex": receipt["status"] == "success", "status": bundle.status,
            "issues": [issue.code for issue in bundle.issues]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_bao", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--details", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    expected = {f"2508-{number:05d}" for number in range(2872, 7872)}
    pubs = sorted(p for p in args.raw_bao.iterdir() if p.name in expected and p.is_dir())
    dirs = [v for p in pubs for v in sorted(p.iterdir()) if v.is_dir()
            and v.name.startswith("v") and v.name[1:].isdigit()]
    if not dirs:
        raise ValueError("No published Versions")
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(inspect_version, dirs, chunksize=4))
    tex = [row for row in rows if row["tex"]]
    ready = sum(row["status"] == "ready" for row in tex)
    counts = Counter(row["status"] for row in rows)
    report = {"revision": args.revision, "assembler_version": ASSEMBLER_VERSION,
              "scope": "raw/bao/2508-02872..2508-07871, published Versions only",
              "publications_present": len(pubs), "missing_ids": sorted(expected - {p.name for p in pubs}),
              "versions": len(rows), "statuses": dict(counts), "tex_versions": len(tex),
              "ready_tex_versions": ready, "ready_fraction": ready / len(tex) if tex else None,
              "issue_versions": dict(Counter(code for row in rows for code in set(row["issues"])))}
    write_json(args.details, rows)
    write_json(args.output, report)


if __name__ == "__main__":
    main()
