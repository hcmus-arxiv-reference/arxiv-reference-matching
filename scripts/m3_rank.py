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
import os
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


def check_evaluation_split(splits, group_size):
    """Check the agreed Publication counts before an official evaluation."""
    counts = Counter((row["partition"], row["pool"]) for row in splits.values())
    for part in ("valid", "test"):
        for pool in ("manual", "auto"):
            actual = counts[part, pool]
            if actual != group_size:
                raise ValueError(f"{part}/{pool}: expected {group_size} Publications, got {actual}")


def run(source, output, *, group_size=None, auto_file=None, key_maps=None):
    """Fit only on train pairs, score within Publication and write one shard per Range."""
    splits = {}
    for r in read_csv(source / "labels/splits.csv"):
        pid = r["arxiv_id"]
        if pid in splits or r["partition"] not in {"train","valid","test"} or r["pool"] not in {"auto","manual"}:
            raise ValueError(f"Invalid split: {r}")
        splits[pid] = r
    if group_size is not None:
        check_evaluation_split(splits, group_size)
    gold = {}
    abstentions = set()
    for pool in ("manual", "auto"):
        directory = source / "labels" / pool
        paths = sorted(directory.glob("*.csv"))
        if pool == "auto" and auto_file:
            paths = [directory / auto_file]
        elif pool == "auto" and len(paths) > 1:
            raise ValueError("Multiple automatic runs found. Select the active CSV with --auto-file.")
        for path in paths:
            for r in read_csv(path):
                key = r["arxiv_id"], r["citation_key"]
                if key in gold or splits.get(key[0], {}).get("pool") != pool:
                    raise ValueError(f"Conflicting label or split: {key} in {path}")
                if pool == "auto":
                    confidence = r.get("confidence")
                    if confidence not in {"unsure", "sure"} or (confidence == "unsure" and r["ref_arxiv_id"]):
                        raise ValueError(f"Invalid automatic label: {key}, confidence={confidence}")
                    if confidence == "unsure":
                        abstentions.add(key)
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
    # Manual sheets cover one Version; M2 also keeps entries from other Versions.
    # Resolve manual aliases using M2's per-Publication key_map for the sheet Version.
    aligned = {}
    for (pid, cite), truth in gold.items():
        target = cite
        if splits[pid]["pool"] == "manual":
            target = (key_maps or {}).get(pid, {}).get(cite, cite)
        key = pid, target
        if key not in entries:
            raise ValueError(f"Missing M2 citation_key for {pid}/{cite}; supply the sheet Version key_map")
        if key in aligned and aligned[key] != truth:
            raise ValueError(f"Conflicting ground truth after alias resolution: {key}")
        aligned[key] = truth
    gold = aligned
    unlabeled = entries.keys() - gold.keys()
    if any(splits[pid]["pool"] == "auto" for pid, _ in unlabeled):
        raise ValueError("Automatic labels do not cover all BibTeX entries")
    if {pid for pid, _ in gold} != splits.keys() or owners.keys() != splits.keys():
        raise ValueError("Missing Publication in labels or M2 tables")
    counts = [Counter(), Counter()]
    totals = [0, 0]
    for key, entry in entries.items():
        pid = key[0]
        if key in unlabeled:
            continue
        if gold[key] and gold[key] not in refs[pid]:
            raise ValueError(f"Reference outside Publication: {key} -> {gold[key]}")
        if splits[pid]["partition"] == "train" and key not in abstentions:
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
    metrics = defaultdict(lambda: {"entries": 0, "rr_sum": 0.0, "n_with_target": 0, "n_with_empty": 0})
    for key, entry in sorted(entries.items()):
        pid, cite = key
        part = splits[pid]["partition"]
        candidates = refs[pid]
        scores = {rid: sum(weights[pair] for pair in enumerate(features(entry, ref)))
                  for rid, ref in candidates.items()}
        top = sorted(scores, key=lambda rid: (-scores[rid], rid))[:5]
        stat = metrics[part]
        stat["entries"] += 1
        truth = gold.get(key)
        if key in unlabeled:
            stat["unlabeled_manual_entries"] = stat.get("unlabeled_manual_entries", 0) + 1
        if truth is not None:
            stat["n_with_target"] += 1
        if truth is not None or (key in gold and splits[pid]["pool"] == "manual"):
            stat["n_with_empty"] += 1
        if truth in top:
            stat["rr_sum"] += 1 / (1 + top.index(truth))
        rows[owners[pid]].append(dict(arxiv_id=pid, citation_key=cite, partition=part,
            groundtruth_arxiv_id=truth, **{f"cand_{i}": rid for i,rid in enumerate(top,1)}))
    if set(metrics) != {"train","valid","test"}:
        raise ValueError("Expected non-empty train, valid and test")
    for stat in metrics.values():
        stat["mrr_at_5"] = stat["rr_sum"] / stat["n_with_target"] if stat["n_with_target"] else None
        stat["mrr_at_5_with_empty"] = stat["rr_sum"] / stat["n_with_empty"] if stat["n_with_empty"] else None
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
    parser.add_argument("--auto-file", help="Active CSV filename under labels/auto/")
    parser.add_argument("--revision", help="HF dataset revision to evaluate with --hf")
    parser.add_argument("--key-maps", type=Path, help="JSON mapping Publication to sheet-Version M2 citation aliases")
    args = parser.parse_args()
    key_maps = json.loads(args.key_maps.read_text(encoding="utf-8")) if args.key_maps else {}
    if args.auto_file and (Path(args.auto_file).name != args.auto_file or not args.auto_file.endswith(".csv")):
        parser.error("--auto-file must name one CSV under labels/auto/")
    if args.revision and not args.hf:
        parser.error("--revision requires --hf")
    source = args.source
    if args.hf:
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
        from huggingface_hub import HfApi, hf_hub_download
        from src.common.config import get_settings, load_ranges
        settings = get_settings()
        api = HfApi(token=settings.hf_token)
        repo = settings.hf_repo_id
        revision = api.dataset_info(repo, revision=args.revision).sha
        files = ["labels/splits.csv"]
        for pool in ("manual", "auto"):
            files.extend(item.path for item in api.list_repo_tree(
                repo, f"labels/{pool}", repo_type="dataset", revision=revision)
                if item.path.endswith(".csv") and (pool != "auto" or not args.auto_file
                    or item.path == f"labels/auto/{args.auto_file}"))
        files.extend(f"tables/{member}/{table}.parquet" for member in load_ranges()
                     for table in ("references", "bibtex"))
        with tempfile.TemporaryDirectory() as directory:
            for name in files:
                hf_hub_download(repo, name, repo_type="dataset", revision=revision,
                                token=settings.hf_token, local_dir=directory)
            print("Dataset revision:", revision)
            print(json.dumps(run(Path(directory), args.out, group_size=5, auto_file=args.auto_file, key_maps=key_maps), indent=2))
        return
    print(json.dumps(run(source, args.out, group_size=5, auto_file=args.auto_file, key_maps=key_maps), indent=2))


if __name__ == "__main__":
    main()
