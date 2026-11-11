"""Benchmark file-tree gathering on source-rich folders from distinct Publications.

Main-file accuracy uses reviewed labels, never predictions as their own labels.
Dependency scores measure agreement with assemble_source on its ready cases only.
Both implementations share the LaTeX scanner, so dependency agreement is not an
independent measure of accuracy or proof that the source compiles.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter

if __name__ == "__main__" and not __package__:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.parse.MultifileGathering.file_tree import build_file_tree
from src.parse.source import assemble_source

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_RAW = MODULE_DIR.parents[2] / "data/arxiv_crawl_20261024/raw"
DEFAULT_LABELS = MODULE_DIR / "benchmark_labels.json"
DEFAULT_OUTPUT = MODULE_DIR / "output/benchmark"
DEFAULT_LIMIT = 90


def select_folders(raw_dir: Path, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Rank by tex+bib count; keep one richest Version per Publication."""
    if not raw_dir.is_dir():
        raise NotADirectoryError(raw_dir)
    if limit < 1:
        raise ValueError("limit must be positive")
    selected = []
    for publication in sorted(raw_dir.iterdir()):
        if not publication.is_dir():
            continue
        versions = []
        for folder in publication.iterdir():
            if not folder.is_dir() or not folder.name.startswith("v") or not folder.name[1:].isdigit():
                continue
            tex_count = bib_count = 0
            for _, _, filenames in os.walk(folder):
                for name in filenames:
                    suffix = Path(name).suffix.lower()
                    tex_count += suffix == ".tex"
                    bib_count += suffix == ".bib"
            if tex_count:
                versions.append({
                    "folder": folder.relative_to(raw_dir).as_posix(),
                    "tex_count": tex_count, "bib_count": bib_count,
                    "version": int(folder.name[1:]),
                })
        if versions:
            selected.append(max(versions, key=lambda item: (
                item["tex_count"] + item["bib_count"], item["tex_count"],
                item["bib_count"], item["version"],
            )))
    return sorted(selected, key=lambda item: (
        -(item["tex_count"] + item["bib_count"]),
        -item["tex_count"], -item["bib_count"], item["folder"],
    ))[:limit]


def summarize(results: list[dict]) -> dict:
    """Keep unlabelled/ambiguous and incomplete reference cases out of scores."""
    labelled = [row for row in results if row["expected_main"] is not None]
    reference_ready = [row for row in results if row["reference_status"] == "ready"]
    correct = sum(row["main_correct"] is True for row in labelled)
    true_positive = false_positive = false_negative = 0
    exact = full_exact = 0
    for row in reference_ready:
        predicted = set(row["predicted_inputs"])
        expected = set(row["reference_inputs"])
        true_positive += len(predicted & expected)
        false_positive += len(predicted - expected)
        false_negative += len(expected - predicted)
        matched = predicted == expected and row["error"] is None
        exact += matched
        full_exact += matched and row["main_correct"] is True
    return {
        "folders": len(results),
        "successful_calls": sum(row["error"] is None for row in results),
        "labelled_main_cases": len(labelled),
        "unscored_main_cases": len(results) - len(labelled),
        "main_correct": correct,
        "main_accuracy": correct / len(labelled) if labelled else None,
        "main_label_coverage": len(labelled) / len(results) if results else None,
        "reference_ready_cases": len(reference_ready),
        "input_exact_matches": exact,
        "input_exact_agreement": exact / len(reference_ready) if reference_ready else None,
        "full_tree_matches": full_exact,
        "full_tree_agreement": full_exact / len(reference_ready) if reference_ready else None,
        "input_true_positive": true_positive,
        "input_false_positive": false_positive,
        "input_false_negative": false_negative,
        "input_micro_precision": (true_positive / (true_positive + false_positive)
                                  if true_positive + false_positive else None),
        "input_micro_recall": (true_positive / (true_positive + false_negative)
                               if true_positive + false_negative else None),
        "gather_seconds": sum(row["seconds"] for row in results),
    }


def run_benchmark(raw_dir: str | Path = DEFAULT_RAW, *, limit: int = DEFAULT_LIMIT,
                  output_dir: str | Path = DEFAULT_OUTPUT,
                  labels_path: str | Path = DEFAULT_LABELS) -> dict:
    """Call build_file_tree once per folder and persist predictions and scores."""
    raw_dir = Path(raw_dir).resolve()
    output_dir = Path(output_dir).resolve()
    labels_path = Path(labels_path).resolve()
    labels = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.is_file() else {}
    selected = select_folders(raw_dir, limit)
    results = []
    for candidate in selected:
        relative = candidate["folder"]
        folder = raw_dir / relative
        label = labels.get(relative, {})
        row = dict(candidate, expected_main=label.get("main_file"),
                   label_note=label.get("note", "No reviewed label"),
                   predicted_main=None, predicted_inputs=[], main_correct=None,
                   reference_status="not_evaluated", reference_inputs=None,
                   reference_issues=[], error=None)
        if row["expected_main"] is not None:
            labelled_file = folder / row["expected_main"]
            if (not labelled_file.is_file() or
                    hashlib.sha256(labelled_file.read_bytes()).hexdigest() != label.get("sha256")):
                row["expected_main"] = None
                row["label_note"] = "Label checksum missing or changed; excluded from scoring"
        started = perf_counter()
        try:
            tree = build_file_tree(folder, output_dir / "trees" / (relative.replace("/", "_") + ".json"))
            row["predicted_main"] = tree.main_file
            row["predicted_inputs"] = list(tree.input_files)
        except Exception as error:
            # One failed Version must not prevent reporting the remaining calls.
            row["error"] = f"{type(error).__name__}: {error}"
        row["seconds"] = perf_counter() - started
        if row["expected_main"] is not None:
            row["main_correct"] = row["error"] is None and row["predicted_main"] == row["expected_main"]
            reference = assemble_source(folder, root_file=row["expected_main"])
            row["reference_status"] = reference.status
            row["reference_issues"] = sorted({issue.code for issue in reference.issues})
            if reference.status == "ready":
                row["reference_inputs"] = [name for name in reference.files if name != reference.root]
        results.append(row)
    report = {
        "raw_dir": str(raw_dir), "labels_path": str(labels_path),
        "selection": "Top tex+bib counts; one richest Version per Publication; ties prefer latest Version",
        "limitations": [
            "Main labels are source-reviewed annotations, not verified TeX compilation roots.",
            "Ambiguous or unlabelled main cases are excluded and coverage is reported.",
            "Dependency scores are agreement with assemble_source on ready cases only; both share _scan.",
            "This intentionally source-rich sample does not estimate accuracy across the entire corpus.",
            "BibTeX files influence selection; bibliography commands are outside input_files scope.",
        ],
        "summary": summarize(results), "results": results,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_dir", nargs="?", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_benchmark(args.raw_dir, limit=args.limit,
                           output_dir=args.output_dir, labels_path=args.labels)
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {args.output_dir.resolve() / 'report.json'}")
