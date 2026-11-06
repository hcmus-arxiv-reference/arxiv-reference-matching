"""Measure source size before/after image removal on a random sample of a corpus.

The M1 report needs the average size per Publication before and after keeping
only ``.tex/.bib``. Versions crawled before ``source.json`` recorded sizes have
no "before" number, and their archives were not kept, so this script downloads
the Versions of a random sample of complete Publications again, through the
same Source fetch Stage, into a separate work directory:

    python -m scripts.measure_sizes --corpus data/crawl-smoke \\
        --work data/size-sample --sample 300 --out stats/size-sample

The sample can also be measured on another machine (Colab) that does not have
the corpus: write a small plan where the corpus is, then run from the plan.

    python -m scripts.measure_sizes --corpus data/crawl-smoke --sample 300 \\
        --plan-out stats/size-plan.json
    python -m scripts.measure_sizes --plan size-plan.json --work /content/size-sample \\
        --out /content/size-out

The plan holds, per sampled Publication, its Version count and the corpus
receipt's file list with sha256: IDs and checksums only, no source text.

Three numbers per Version, kept apart so compression is not mistaken for
filtering:
    downloaded_bytes  bytes received from arXiv (usually gzip)
    content_bytes     archive content after decompression, before selection
    kept_bytes        ``.tex/.bib`` kept
``same_as_corpus`` says whether the kept files (names and sha256) equal the
corpus copy; arXiv may have changed nothing, so a mismatch is worth a look.

The corpus is only read. Rerun the same command to resume: Versions already
verified in the work directory are not downloaded again. arXiv is accessed
through one HttpClient with at least 3 s between requests.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from pathlib import Path

from src.common.config import get_settings
from src.common.schema import publication_key
from src.crawl.http_client import HttpClient
from src.crawl.source import ArxivSourceDownloader
from src.make_stats import load_manifest, publication_row

COLUMNS = ["arxiv_id", "version", "status", "downloaded_bytes", "content_bytes",
           "kept_bytes", "same_as_corpus"]


def complete_ids(corpus: Path) -> list[str]:
    """Publications that ``make_stats`` counts as done, in ID order."""
    records = load_manifest(corpus / "manifests" / "crawl.jsonl")
    ids = sorted({r[0] for r in records if r[2] == "discovery"})
    return [i for i in ids if publication_row(corpus, records, i)["status"] == "done"]


def versions_of(corpus: Path, arxiv_id: str) -> int:
    payload = json.loads((corpus / "metadata" / f"{publication_key(arxiv_id)}.json").read_text())
    return payload["publication"]["versions"]


def make_plan(corpus: Path, sample: int, seed: int) -> dict:
    """Seeded random sample of complete Publications with what the measurement needs."""
    population = complete_ids(corpus)
    sampled = sorted(random.Random(seed).sample(population, min(sample, len(population))))
    publications = []
    for arxiv_id in sampled:
        versions = versions_of(corpus, arxiv_id)
        files = {}
        for version in range(1, versions + 1):
            receipt = corpus / "raw" / publication_key(arxiv_id) / f"v{version}" / "source.json"
            files[str(version)] = json.loads(receipt.read_text())["files"] if receipt.exists() else None
        publications.append({"arxiv_id": arxiv_id, "versions": versions, "corpus_files": files})
    return {"format": 1, "seed": seed, "population_complete_publications": len(population),
            "publications": publications}


def measure_version(downloader, corpus_files: dict | None, arxiv_id: str, version: int) -> dict:
    """Download one Version into the work directory and compare it with the corpus copy."""
    result = downloader.download(arxiv_id, version)
    row = dict.fromkeys(COLUMNS)
    row.update(arxiv_id=arxiv_id, version=version, status=result.status)
    if result.status not in {"success", "non_tex"}:
        return row
    receipt = json.loads((result.path / "source.json").read_text())
    row.update(downloaded_bytes=receipt.get("downloaded_bytes"),
               content_bytes=receipt.get("content_bytes"),
               kept_bytes=sum((result.path / n).stat().st_size for n in receipt["files"]),
               same_as_corpus=corpus_files == receipt["files"])
    return row


def mean_ci(values: list[int]) -> dict:
    """Mean with a normal-approximation 95% interval (sample of Publications)."""
    if not values:
        return {"mean": None, "ci95": None}
    mean = statistics.mean(values)
    if len(values) < 2:
        return {"mean": round(mean, 1), "ci95": None}
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return {"mean": round(mean, 1), "ci95": [round(mean - half, 1), round(mean + half, 1)]}


def summarize(rows: list[dict], sampled: list[str], population: int) -> dict:
    """Per-Publication sums; only Publications whose every Version was measured."""
    by_id: dict[str, list[dict]] = {}
    for row in rows:
        by_id.setdefault(row["arxiv_id"], []).append(row)
    papers = []
    for arxiv_id in sampled:
        items = by_id.get(arxiv_id, [])
        if items and all(r["content_bytes"] is not None for r in items):
            papers.append({k: sum(r[k] for r in items)
                           for k in ("downloaded_bytes", "content_bytes", "kept_bytes")})
    total = {k: sum(p[k] for p in papers) for k in ("downloaded_bytes", "content_bytes", "kept_bytes")}
    measured = [r for r in rows if r["content_bytes"] is not None]
    return {
        "population_complete_publications": population,
        "sampled_publications": len(sampled),
        "measured_publications": len(papers),
        "measured_versions": len(measured),
        "versions_not_measured": len(rows) - len(measured),
        "versions_differing_from_corpus": sum(r["same_as_corpus"] is False for r in measured),
        "avg_bytes_downloaded_per_paper": mean_ci([p["downloaded_bytes"] for p in papers]),
        "avg_bytes_before_per_paper": mean_ci([p["content_bytes"] for p in papers]),
        "avg_bytes_after_per_paper": mean_ci([p["kept_bytes"] for p in papers]),
        # Ratios of totals over the same Publications.
        "size_reduction_pct": (round(100 * (1 - total["kept_bytes"] / total["content_bytes"]), 2)
                               if total["content_bytes"] else None),
        "download_to_content_ratio": (round(total["downloaded_bytes"] / total["content_bytes"], 4)
                                      if total["content_bytes"] else None),
    }


def run_plan(plan: dict, downloader, out: Path) -> dict:
    """Measure every Version of the plan; write versions.csv and summary.json to ``out``."""
    if plan.get("format") != 1:
        raise ValueError("Unknown size plan format")
    out.mkdir(parents=True, exist_ok=True)
    publications = plan["publications"]
    rows = []
    for index, item in enumerate(publications, 1):
        arxiv_id = item["arxiv_id"]
        for version in range(1, item["versions"] + 1):
            try:
                rows.append(measure_version(downloader, item["corpus_files"].get(str(version)),
                                            arxiv_id, version))
            except Exception as error:  # keep going; the Version is reported as not measured
                rows.append({**dict.fromkeys(COLUMNS), "arxiv_id": arxiv_id, "version": version,
                             "status": f"error:{type(error).__name__}"})
        print(json.dumps({"done": index, "of": len(publications), "id": arxiv_id}), flush=True)
    with (out / "versions.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {"seed": plan["seed"],
               **summarize(rows, [p["arxiv_id"] for p in publications],
                           plan["population_complete_publications"])}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, help="thư mục dữ liệu đã crawl (chỉ đọc)")
    ap.add_argument("--plan", type=Path, help="file kế hoạch đã tạo bằng --plan-out (thay cho --corpus)")
    ap.add_argument("--plan-out", type=Path, help="chỉ ghi file kế hoạch rồi dừng, không tải gì")
    ap.add_argument("--work", type=Path, help="thư mục tải lại mẫu, khác --corpus")
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20261105)
    ap.add_argument("--out", type=Path, default=Path("stats/size-sample"))
    args = ap.parse_args(argv)
    if (args.corpus is None) == (args.plan is None):
        ap.error("give exactly one of --corpus or --plan")
    if args.plan is not None:
        plan = json.loads(args.plan.read_text())
    else:
        plan = make_plan(args.corpus, args.sample, args.seed)
    if args.plan_out is not None:
        args.plan_out.parent.mkdir(parents=True, exist_ok=True)
        args.plan_out.write_text(json.dumps(plan) + "\n")
        print(json.dumps({"plan": str(args.plan_out), "publications": len(plan["publications"]),
                          "versions": sum(p["versions"] for p in plan["publications"])}))
        return 0
    if args.work is None:
        ap.error("--work is required to measure")
    if args.corpus is not None and args.work.resolve() == args.corpus.resolve():
        ap.error("--work must differ from --corpus")
    downloader = ArxivSourceDownloader(HttpClient(get_settings().user_agent(), min_interval=3.1),
                                       args.work / "raw")
    print(json.dumps(run_plan(plan, downloader, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
