"""Rebuild the pilot histogram from a label CSV, an entry sheet and M1 references.

Usage: python m3/measure_baseline.py LABELS SHEET REFERENCES.parquet OUTPUT.json
"""
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def words(text):
    return set(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold()))


def measure(labels_path, sheet_path, references_path):
    labels = read_rows(labels_path)
    entries = {(r["arxiv_id"], r["citation_key"]): r["entry"] for r in read_rows(sheet_path)}
    keys = {(r["arxiv_id"], r["citation_key"]) for r in labels}
    if len(keys) != len(labels) or keys != entries.keys():
        raise ValueError("The label and entry keys must agree and be unique.")
    ids = sorted({pid for pid, _ in keys})
    refs = defaultdict(dict)
    table = pq.read_table(references_path, columns=["arxiv_id", "ref_arxiv_id", "ref_title"],
                          filters=[("arxiv_id", "in", ids)])
    for row in table.to_pylist():
        refs[row["arxiv_id"]][row["ref_arxiv_id"]] = words(row["ref_title"] or "")
    counts = {pid: dict(ranks=[0]*5, missed=0, empty=0) for pid in ids}
    for row in labels:
        pid, key, gold = row["arxiv_id"], row["citation_key"], row["ref_arxiv_id"]
        result = counts[pid]
        if not gold:
            result["empty"] += 1
            continue
        if gold not in refs[pid]:
            raise ValueError(f"Unknown reference {gold} in {pid}")
        tokens = words(entries[pid, key])
        scores = {rid: len(title & tokens)/len(title) if title else 0
                  for rid, title in refs[pid].items()}
        top = sorted(scores, key=lambda rid: (-scores[rid], rid))[:5]
        if gold in top:
            result["ranks"][top.index(gold)] += 1
        else:
            result["missed"] += 1
    return counts


if __name__ == "__main__":
    result = measure(*sys.argv[1:4])
    Path(sys.argv[4]).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
