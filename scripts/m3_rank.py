"""Train a categorical Naive Bayes ranker and evaluate the frozen Publication split.

python -m scripts.m3_rank --source data/m3-input --out data/m3-ranked
Source layout: tables/<member>/{bibtex,references}.parquet, labels/splits.csv,
labels/manual/*.csv and labels/auto/*.csv (one active run per Publication).
Use --hf instead of --source to download a single revision of those files.
Outputs are local until reviewed. No network writes are performed.
"""
import argparse
import csv
import json
import math
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from src.common.schema import from_records, write_table


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def tokens(value):
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return set(re.findall(r"[^\W_]+", "".join(c for c in text if not unicodedata.combining(c))))


def features(entry, ref):
    """Discretize pair evidence, preserving missing values as a separate category."""
    title, other = tokens(entry["title"]), tokens(ref["ref_title"])
    authors = tokens(" ".join(entry["authors"] or []))
    names = tokens(" ".join(ref["ref_authors"] or []))
    year = str(ref["ref_submission_date"] or "")[:4]
    date = min(2, abs(entry["year"] - int(year))) if entry["year"] and year.isdigit() else -1
    source = " ".join(str(entry.get(k) or "") for k in ("url", "journal", "doi", "title"))
    ids = re.findall(r"(?<!\w)(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?(?!\d)", source)
    ids = {re.sub(r"v\d+$", "", rid).lower() for rid in ids}
    def overlap(a, b):
        return int(5 * len(a & b) / len(a | b)) if a and b else -1
    return (overlap(title, other), overlap(authors, names), date,
            int(ref["ref_arxiv_id"].lower() in ids) if ids else -1)


def run(source, output):
    """Fit only on train pairs, score within Publication and write one shard per Range."""
    splits = {}
    for r in read_csv(source / "labels/splits.csv"):
        pid = r["arxiv_id"]
        if pid in splits or r["partition"] not in {"train","valid","test"} or r["pool"] not in {"auto","manual"}:
            raise ValueError(f"Invalid split: {r}")
        splits[pid] = r
    gold = {}
    for pool in ("manual", "auto"):
        for path in sorted((source / "labels" / pool).glob("*.csv")):
            for r in read_csv(path):
                key = r["arxiv_id"], r["citation_key"]
                if key in gold or splits.get(key[0], {}).get("pool") != pool:
                    raise ValueError(f"Conflicting label or split: {key} in {path}")
                gold[key] = r["ref_arxiv_id"] or None
    refs = defaultdict(dict)
    entries = {}
    owners = {}
    subsets = [("arxiv_id", "in", list(splits))]
    for path in sorted((source / "tables").glob("*/bibtex.parquet")):
        for r in pq.read_table(path, filters=subsets).to_pylist():
            pid = r["arxiv_id"]
            key = pid, r["citation_key"]
            if key in entries or owners.setdefault(pid, path.parent.name) != path.parent.name:
                raise ValueError(f"Duplicate BibTeX key or owner: {key}")
            entries[key] = r
        for r in pq.read_table(path.with_name("references.parquet"), filters=subsets).to_pylist():
            pid, rid = r["arxiv_id"], r["ref_arxiv_id"]
            if rid in refs[pid]:
                raise ValueError(f"Duplicate reference: {pid}/{rid}")
            refs[pid][rid] = r
    if entries.keys() != gold.keys() or owners.keys() != splits.keys():
        raise ValueError(f"Coverage mismatch: {len(gold.keys()-entries.keys())} labels without BibTeX, "
                         f"{len(entries.keys()-gold.keys())} entries without labels; check M2 key_map and splits")
    counts = [Counter(), Counter()]
    totals = [0, 0]
    for key, entry in entries.items():
        pid = key[0]
        if gold[key] and gold[key] not in refs[pid]:
            raise ValueError(f"Reference outside Publication: {key} -> {gold[key]}")
        if splits[pid]["partition"] == "train":
            for rid, ref in refs[pid].items():
                y = int(gold[key] == rid)
                totals[y] += 1
                counts[y].update(enumerate(features(entry, ref)))
    if not all(totals):
        raise ValueError("Training requires positive and negative candidate pairs")
    # Add-one likelihood ratios. Class priors are constant within each ranking.
    weights = {}
    for j, domain in enumerate((range(-1,6), range(-1,6), range(-1,3), range(-1,2))):
        for value in domain:
            weights[j,value] = math.log((counts[1][j,value]+1)/(totals[1]+len(domain))) - math.log(
                (counts[0][j,value]+1)/(totals[0]+len(domain)))
    rows = defaultdict(list)
    metrics = defaultdict(lambda: {"entries": 0, "rr_sum": 0.0})
    for key, entry in sorted(entries.items()):
        pid, cite = key
        part = splits[pid]["partition"]
        candidates = refs[pid]
        scores = {rid: sum(weights[pair] for pair in enumerate(features(entry, ref)))
                  for rid, ref in candidates.items()}
        top = sorted(scores, key=lambda rid: (-scores[rid], rid))[:5]
        stat = metrics[part]
        stat["entries"] += 1
        if gold[key] in top:
            stat["rr_sum"] += 1 / (1 + top.index(gold[key]))
        rows[owners[pid]].append(dict(arxiv_id=pid, citation_key=cite, partition=part,
            groundtruth_arxiv_id=gold[key], **{f"cand_{i}": rid for i,rid in enumerate(top,1)}))
    if set(metrics) != {"train","valid","test"}:
        raise ValueError("Expected non-empty train, valid and test")
    for stat in metrics.values():
        stat["mrr_at_5"] = stat["rr_sum"] / stat["entries"]
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        stage = Path(temp)/"result"
        for member, records in rows.items():
            write_table(from_records(records,"predictions"), "predictions", stage/"tables"/member/"predictions.parquet")
        (stage/"metrics.json").write_text(json.dumps(metrics,indent=2), encoding="utf-8")
        stage.rename(output)
    return dict(metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--source", type=Path)
    inputs.add_argument("--hf", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = args.source
    if args.hf:
        from huggingface_hub import snapshot_download
        from src.common.config import get_settings
        settings = get_settings()
        source = Path(snapshot_download(settings.hf_repo_id, repo_type="dataset", token=settings.hf_token,
            allow_patterns=["labels/splits.csv","labels/manual/*.csv","labels/auto/*.csv",
                            "tables/*/bibtex.parquet","tables/*/references.parquet"]))
        print("Dataset revision:", source.name)
    print(json.dumps(run(source,args.out), indent=2))


if __name__ == "__main__":
    main()
