"""Measure source size before/after image removal on a random sample of a corpus.

The M1 report needs the average size per Publication before and after keeping
only ``.tex/.bib``. Versions crawled before ``source.json`` recorded sizes have
no "before" number, and their archives were not kept, so this script downloads
the Versions of a random sample of complete Publications again, through the
same Source fetch Stage, into a separate work directory:

    python -m scripts.measure_sizes --corpus data/crawl-smoke \\
        --work data/size-sample --sample 300 --out stats/size-sample

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


def measure_version(downloader, corpus: Path, arxiv_id: str, version: int) -> dict:
    result = downloader.download(arxiv_id, version)
    row = dict.fromkeys(COLUMNS)
    row.update(arxiv_id=arxiv_id, version=version, status=result.status)
    if result.status not in {"success", "non_tex"}:
        return row
    receipt = json.loads((result.path / "source.json").read_text())
    original = corpus / "raw" / publication_key(arxiv_id) / f"v{version}" / "source.json"
    corpus_files = json.loads(original.read_text())["files"] if original.exists() else None
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, required=True, help="thư mục dữ liệu đã crawl (chỉ đọc)")
    ap.add_argument("--work", type=Path, required=True, help="thư mục tải lại mẫu, khác --corpus")
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20261105)
    ap.add_argument("--out", type=Path, default=Path("stats/size-sample"))
    args = ap.parse_args(argv)
    if args.work.resolve() == args.corpus.resolve():
        ap.error("--work must differ from --corpus")
    population = complete_ids(args.corpus)
    sampled = sorted(random.Random(args.seed).sample(population, min(args.sample, len(population))))
    client = HttpClient(get_settings().user_agent(), min_interval=3.1)
    downloader = ArxivSourceDownloader(client, args.work / "raw")
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, arxiv_id in enumerate(sampled, 1):
        for version in range(1, versions_of(args.corpus, arxiv_id) + 1):
            try:
                rows.append(measure_version(downloader, args.corpus, arxiv_id, version))
            except Exception as error:  # keep going; the Version is reported as not measured
                rows.append({**dict.fromkeys(COLUMNS), "arxiv_id": arxiv_id, "version": version,
                             "status": f"error:{type(error).__name__}"})
        print(json.dumps({"done": index, "of": len(sampled), "id": arxiv_id}), flush=True)
    with (args.out / "versions.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {"seed": args.seed, **summarize(rows, sampled, len(population))}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
