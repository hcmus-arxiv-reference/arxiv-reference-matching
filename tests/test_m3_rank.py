"""End-to-end fixture for the issue 68 ranker."""
import csv

import pyarrow.parquet as pq
import pytest

from scripts.m3_rank import run
from src.common.schema import from_records, write_table


def test_train_only_ranking_and_empty_gold(tmp_path, monkeypatch):
    root = tmp_path / "input"
    ids = ["2410.00001", "2410.00002", "2410.00003"]
    targets = ["2301.00001", "2301.00002"]
    entries, refs, labels, splits = [], [], [], []
    for pid, part in zip(ids, ("train", "valid", "test")):
        splits.append(dict(arxiv_id=pid, pool="manual", partition=part))
        for key, title, year in [("a","Graph ranking",2023), ("b","Learning agents",2024)]:
            entries.append(dict(arxiv_id=pid, citation_key=key, entry_type="article", title=title, year=year))
            rid = targets[int(key=="b")]
            refs.append(dict(arxiv_id=pid, ref_arxiv_id=rid, ref_title=title))
            labels.append(dict(arxiv_id=pid, citation_key=key,
                               ref_arxiv_id="" if key=="b" and part=="test" else rid))
    for name, rows in [("bibtex",entries),("references",refs)]:
        write_table(from_records(rows,name),name,root/"tables/lieu"/(name+".parquet"))
    for path, rows in [("splits.csv",splits),("manual/lieu.csv",labels)]:
        file = root/"labels"/path
        file.parent.mkdir(parents=True,exist_ok=True)
        with file.open("w",newline="") as stream:
            writer = csv.DictWriter(stream,fieldnames=rows[0])
            writer.writeheader()
            writer.writerows(rows)
    output = tmp_path/"out"
    metrics = run(root,output)
    assert metrics["valid"]["mrr_at_5"] == 1
    assert metrics["test"]["mrr_at_5"] == 1
    assert metrics["test"]["mrr_at_5_with_empty"] == 0.5
    assert metrics["test"]["n_with_target"] == 1
    assert metrics["test"]["n_with_empty"] == 2
    result = pq.read_table(output/"tables/lieu/predictions.parquet").to_pylist()
    assert len(result)==6 and all(r["cand_3"] is None for r in result)
    assert result[-1]["cand_1"] == targets[1] and result[-1]["groundtruth_arxiv_id"] is None
    with pytest.raises(FileExistsError):
        run(root,output)


    # Reclassify the test Publication as automatic: its empty label is an abstention.
    for row in splits:
        if row["partition"] == "test":
            row["pool"] = "auto"
    def rewrite(name, rows):
        file = root / "labels" / name
        file.parent.mkdir(exist_ok=True)
        with file.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0])
            writer.writeheader()
            writer.writerows(rows)

    rewrite("splits.csv", splits)
    rewrite("manual/lieu.csv", labels[:-2])
    rewrite("auto/run.csv", [dict(row, confidence="sure" if row["ref_arxiv_id"] else "unsure")
                             for row in labels[-2:]])
    stat = run(root, tmp_path / "auto-out")["test"]
    assert stat["entries"] == 2 and stat["n_with_empty"] == stat["n_with_target"] == 1
    assert stat["mrr_at_5_with_empty"] == stat["mrr_at_5"] == 1


    # Swap train and test, then count candidate pairs used to fit the model.
    from scripts import m3_rank
    from unittest.mock import Mock
    splits[0]["partition"], splits[-1]["partition"] = "test", "train"
    rewrite("splits.csv", splits)
    observed = Mock(wraps=m3_rank.features)
    monkeypatch.setattr(m3_rank, "features", observed)
    run(root, tmp_path / "auto-train")
    # Six predictions x two candidates, plus one known train target x two candidates.
    assert observed.call_count == 14
    observed.reset_mock()
    rewrite("auto/run.csv", [dict(row, confidence="sure") for row in labels[-2:]])
    run(root, tmp_path / "sure-train")
    assert observed.call_count == 16
