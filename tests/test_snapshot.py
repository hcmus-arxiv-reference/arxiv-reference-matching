"""Discovery from the arXiv metadata snapshot (src/crawl/snapshot.py)."""
import gzip
import json
from unittest.mock import Mock
import zipfile

import pytest

from scripts import extract_snapshot as extract_cli
from src.common.corpus import Publication
from src.common.schema import read_table
from src.crawl.runner import run_range
from src.crawl.snapshot import (SnapshotDiscovery, detex, extract_snapshot, iter_records,
                                load_snapshot, parse_record)
from tests.test_lieu_crawler import make_pipeline


def record(identifier, versions=2, **extra):
    """A line shaped like Kaggle's arxiv-metadata-oai-snapshot.json ("id" first)."""
    created = ["Mon, 4 Aug 2025 20:02:03 GMT", "Thu, 7 Aug 2025 03:25:33 GMT",
               "Mon, 28 Sep 2026 14:36:45 GMT"]
    row = {"id": identifier, "submitter": "X", "authors": "A, B",
           "title": "Tunable Leg Stiffness\n  in a Hopper", "comments": None,
           "journal-ref": None, "doi": None, "categories": "cs.RO", "abstract": "...",
           "versions": [{"version": f"v{n + 1}", "created": created[n]} for n in range(versions)],
           "update_date": "2026-09-29",
           "authors_parsed": [["Chen", "Rongqian", ""], ["Chen", "Wei-Hsi", ""]]}
    row.update(extra)
    return row


def write_zip(path, rows):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("arxiv-metadata-oai-snapshot.json", "".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_parse_record_matches_api_format():
    pub = parse_record(record("2508.02873", versions=3))
    assert pub == Publication("2508.02873", "Tunable Leg Stiffness in a Hopper",
                              ["Rongqian Chen", "Wei-Hsi Chen"], "2025-08-04T20:02:03Z",
                              ["2025-08-07T03:25:33Z", "2026-09-28T14:36:45Z"], None, 3)


@pytest.mark.parametrize("tex, text", [
    (r"Bal\'azs", "Balázs"), (r"M{\"u}ller", "Müller"), (r"Fran\c{c}ois", "François"),
    (r"S{\o}rensen", "Sørensen"), (r"Erd\H{o}s", "Erdős"), (r"Nguy\^en", "Nguyên"),
    (r"Stra{\ss}e", "Straße"), ("Plain  Name", "Plain Name"), (r"\v{S}imon", "Šimon"),
])
def test_detex(tex, text):
    assert detex(tex) == text


def test_bad_version_list_is_rejected():
    row = record("2508.02873")
    row["versions"] = [{"version": "v2", "created": "Thu, 7 Aug 2025 03:25:33 GMT"}]
    with pytest.raises(ValueError):
        parse_record(row)


def test_extract_keeps_requested_ids_and_records_the_cut_off(tmp_path):
    rows = [record("2508.02872"), record("2508.02873", update_date="2026-10-01"),
            record("2508.09999"), record("2508.02874", versions=0)]
    snapshot = write_zip(tmp_path / "archive.zip", rows)
    out = tmp_path / "extract.json.gz"
    header = extract_snapshot(snapshot, ["2508.02872", "2508.02873", "2508.02874", "2508.02875"], out)
    assert header["found"] == 2 and header["missing"] == 1 and list(header["invalid"]) == ["2508.02874"]
    assert header["latest_update_date"] == "2026-10-01" and len(header["source_sha256"]) == 64
    loaded_header, pubs = load_snapshot(out)
    assert loaded_header == header and set(pubs) == {"2508.02872", "2508.02873"}
    assert gzip.decompress(out.read_bytes())       # really gzip


def test_iter_records_skips_other_ids_without_parsing(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps(record("2508.02872")) + "\nnot json at all\n" + json.dumps(record("2508.02873")) + "\n")
    assert [r["id"] for r in iter_records(path, {"2508.02873"})] == ["2508.02873"]


def test_extract_cli(tmp_path, capsys, monkeypatch):
    snapshot = write_zip(tmp_path / "archive.zip", [record("2508.02872")])
    monkeypatch.setattr(extract_cli, "member_ids", lambda name: ["2508.02872", "2508.02873"])
    assert extract_cli.main(["--snapshot", str(snapshot), "--out", str(tmp_path / "x.json")]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["found"] == 1 and printed["missing"] == 1 and printed["invalid"] == 0


def test_snapshot_discovery_sends_no_api_request_for_known_ids(tmp_path):
    ids = ["2508.02872", "2508.02873", "2508.02874"]
    pipeline, calls, _ = make_pipeline(tmp_path)
    known = {i: parse_record(record(i)) for i in ids[:2]}
    pipeline.discovery = SnapshotDiscovery(known, pipeline.discovery)
    result = run_range(pipeline, ids, max_passes=1, min_free_bytes=0)
    assert result["status"] == "complete"
    queries = [u for u in calls if "/api/query?" in u]
    assert len(queries) == 1 and "2508.02874" in queries[0] and "2508.02872" not in queries[0]
    assert pipeline.discovery.hits == 2 and pipeline.discovery.misses == 1
    rows = {r["arxiv_id"]: r for r in read_table("papers", tmp_path / "tables/papers.parquet").to_pylist()}
    assert rows["2508.02872"]["revised_dates"] == ["2025-08-07T03:25:33Z"]
    assert len([u for u in calls if "/src/" in u]) == 2 + 2 + 1   # v1, v2 of two snapshot papers + v1


def test_prefetch_only_forwards_missing_ids():
    fallback = Mock(batch_size=50)
    discovery = SnapshotDiscovery({"2508.02872": parse_record(record("2508.02872"))}, fallback)
    discovery.prefetch(["2508.02872", "2508.02873"])
    fallback.prefetch.assert_called_once_with(["2508.02873"])
    assert discovery.batch_size == 50
    discovery.prefetch(["2508.02872"])
    assert fallback.prefetch.call_count == 1
