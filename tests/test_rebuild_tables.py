"""scripts/rebuild_tables.py rebuilds the same rows Export writes, from the raw/ layout on the Hub."""
import shutil

from scripts import rebuild_tables
from src.common.schema import read_table
from src.crawl.storage import key
from test_crawl_publish import bundle


def hub_layout(data, ids, member="bao"):
    """Copy a local crawl into raw/<member>/<key>/v<n>/ as the publisher uploads it."""
    raw = data.parent / "hub" / "raw" / member
    paths = []
    for arxiv_id in ids:
        k = key(arxiv_id)
        for version_dir in sorted((data / "raw" / k).glob("v*")):
            target = raw / k / version_dir.name
            target.mkdir(parents=True)
            shutil.copyfile(version_dir / "source.json", target / "source.json")
            shutil.copyfile(data / "metadata" / f"{k}.json", target / "metadata.json")
            shutil.copyfile(data / "references" / f"{k}.json", target / "references.json")
            paths += [f"raw/{member}/{k}/{version_dir.name}/{n}" for n in ("source.json", "metadata.json", "references.json")]
    return raw, paths


def test_rebuilt_rows_equal_the_exported_rows(tmp_path):
    data = tmp_path / "data"
    ids = ["2508.02872", "2508.02873"]
    for arxiv_id in ids:
        _, tables = bundle(data, arxiv_id)
    exported = read_table("papers", tables["papers"]).to_pylist()   # last batch only: one row
    raw, paths = hub_layout(data, ids)
    papers, references, skipped = rebuild_tables.rebuild(raw, rebuild_tables.plan(paths, "bao"))
    assert skipped == {}
    assert [r["arxiv_id"] for r in papers] == ids
    assert papers[-1] == exported[0]
    assert all(r["arxiv_id"] in ids for r in references)


def test_publication_missing_a_version_receipt_is_skipped(tmp_path):
    data = tmp_path / "data"
    bundle(data, "2508.02872")
    raw, paths = hub_layout(data, ["2508.02872"])
    paths = [p for p in paths if not p.endswith("/v1/source.json")]
    papers, _, skipped = rebuild_tables.rebuild(raw, rebuild_tables.plan(paths, "bao"))
    assert papers == [] and skipped == {"incomplete_versions": ["2508-02872"]}


def test_other_members_and_unrelated_files_are_ignored():
    keys = rebuild_tables.plan(["raw/other/2508-02872/v1/source.json", "raw/bao/2508-02872/v1/main.tex",
                                "tables/bao/papers.parquet"], "bao")
    assert keys == {"2508-02872": {"receipts": set(), "v1": set()}}
