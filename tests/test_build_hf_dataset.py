"""Dataset nộp bài: layout data/<bảng>/, card có configs, kiểm khóa và tham chiếu giữa bảng."""
from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from scripts import build_hf_dataset as b
from src.common.schema import from_records, write_table


def _range(root: Path, member: str, aid: str, *, orphan: bool = False) -> None:
    key = aid.replace(".", "-")
    rows = {
        "papers": [{"arxiv_id": aid, "title": "T", "authors": ["A"], "submission_date": "2025-08-04",
                    "revised_dates": [], "venue": None}],
        "references": [{"arxiv_id": aid, "ref_arxiv_id": "1706.03762", "ref_title": "Attention",
                        "ref_authors": ["V"], "ref_submission_date": "2017-06-12", "ref_s2_id": "x"}],
        "elements": [{"element_id": f"{key}#document-1", "arxiv_id": aid, "kind": "document", "content": ""},
                     {"element_id": f"{key}#sentence-1", "arxiv_id": aid, "kind": "sentence", "content": "Hi."}],
        "hierarchy": [{"arxiv_id": aid, "version": 1, "element_id": f"{key}#sentence-1",
                       "parent_id": f"{key}#document-{'9' if orphan else '1'}"}],
        "bibtex": [{"arxiv_id": aid, "citation_key": "vaswani17", "entry_type": "article", "title": "Attention",
                    "authors": ["V"], "year": 2017, "doi": None, "journal": None, "url": None}],
    }
    for name, records in rows.items():
        write_table(from_records(records, name), name, root / member / f"{name}.parquet")


def test_build_writes_layout_and_card(tmp_path: Path) -> None:
    _range(tmp_path / "src", "bao", "2508.02872")
    _range(tmp_path / "src", "minh", "2409.18594")
    report = b.build(tmp_path / "src", tmp_path / "out")

    assert report["errors"] == []
    assert report["counts"] == {"papers": 2, "references": 2, "elements": 4, "hierarchy": 2, "bibtex": 2}
    papers = pq.read_table(tmp_path / "out/data/papers/train-00000-of-00001.parquet")
    assert papers["arxiv_id"].to_pylist() == ["2409.18594", "2508.02872"], "sắp theo khóa chính"
    card = (tmp_path / "out/README.md").read_text(encoding="utf-8")
    assert "- config_name: hierarchy\n  data_files:\n  - split: train\n    path: data/hierarchy/*.parquet" in card
    assert "config_name: predictions" not in card and "| `predictions` | chưa có |" in card


def test_build_refuses_dangling_parent(tmp_path: Path) -> None:
    _range(tmp_path / "src", "bao", "2508.02872", orphan=True)
    report = b.build(tmp_path / "src", tmp_path / "out")
    assert report["errors"] == ["[hierarchy] 1 parent_id không có trong elements"]
    assert not (tmp_path / "out").exists(), "có lỗi thì không ghi gì"


def test_duplicate_key_across_ranges_is_an_error(tmp_path: Path) -> None:
    _range(tmp_path / "src", "bao", "2508.02872")
    _range(tmp_path / "src", "minh", "2508.02872")
    assert any("papers" in e for e in b.build(tmp_path / "src", tmp_path / "out")["errors"])


def test_shards_split_large_tables(tmp_path: Path, monkeypatch) -> None:
    _range(tmp_path / "src", "bao", "2508.02872")
    _range(tmp_path / "src", "minh", "2409.18594")
    monkeypatch.setattr(b, "SHARD_BYTES", 1)
    report = b.build(tmp_path / "src", tmp_path / "out")
    assert "data/elements/train-00003-of-00004.parquet" in report["files"]
    total = sum(pq.read_table(tmp_path / "out" / f).num_rows for f in report["files"] if "/elements/" in f)
    assert total == 4


def test_member_dataset_keeps_only_that_range(tmp_path: Path) -> None:
    _range(tmp_path / "src", "bao", "2508.02872")
    _range(tmp_path / "src", "minh", "2409.18594")
    report = b.build(tmp_path / "src", tmp_path / "out", ("minh",))
    assert report["errors"] == [] and report["counts"]["papers"] == 1
    papers = pq.read_table(tmp_path / "out/data/papers/train-00000-of-00001.parquet")
    assert papers["arxiv_id"].to_pylist() == ["2409.18594"]
    card = (tmp_path / "out/README.md").read_text(encoding="utf-8")
    assert "2409.18594–2410.03024" in card and b.GROUP_DATASET in card and "- n<1K" in card
