"""Split workers, immutable input import, checkpoint roundtrip and final merge."""
import ast
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import Mock
import zipfile

import pytest

from src.common.config import get_settings
from src.common.schema import read_table
from src.crawl.discovery import Publication
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader
from src.crawl.split import (archive_cache, import_cache, merge_results,
    read_cache, ready, run_stage, unpack_cache)
from scripts.prepare_kaggle import prepare
from scripts import crawl_local


IDS = ["2412.08848", "2412.08849"]


def pipeline(root, refs=False):
    discovery = Mock()
    discovery.discover.side_effect = lambda i: Publication(i, "Paper", ["An"], "2024-12-01", [], None, 1)
    discovery.prefetch = Mock()
    client = HttpClient("test", transport=Mock(return_value=HttpResponse(200, {}, b"\\documentclass{article}")),
                        sleeper=lambda _: None)
    references = Mock() if refs else None
    if refs:
        references.references.return_value = [{"citedPaper": {"paperId": "example",
            "externalIds": {"ArXiv": "2301.00001"}, "authors": [{"name": "B"}], "title": "Ref"}}]
    return CrawlPipeline(discovery, ArxivSourceDownloader(client, root / "raw"), root, references)


def test_independent_jobs_resume_and_merge_match_old_export(tmp_path):
    arxiv = pipeline(tmp_path / "arxiv")
    s2 = pipeline(tmp_path / "s2", refs=True)
    s2.discovery.discover.side_effect = AssertionError("S2 must not query arxiv")
    s2.sources.client._transport.side_effect = AssertionError("S2 must not download source")
    assert run_stage(s2, IDS, "s2")["status"] == "complete"
    assert not (s2.data_dir / "metadata").exists()
    assert run_stage(arxiv, IDS, "arxiv")["status"] == "complete"
    assert not (arxiv.data_dir / "references").exists()
    arxiv.sources.client._transport.reset_mock()
    s2.references.references.reset_mock()
    run_stage(arxiv, IDS, "arxiv")
    run_stage(s2, IDS, "s2")
    arxiv.sources.client._transport.assert_not_called()
    s2.references.references.assert_not_called()
    result = merge_results([arxiv.data_dir, s2.data_dir], tmp_path / "merged", IDS)
    assert result == {"requested": 2, "complete": 2, "pending_ids": []}
    legacy = pipeline(tmp_path / "legacy", refs=True)
    legacy.crawl_ids(IDS)
    legacy.export(IDS)
    for name in ["papers", "references"]:
        assert read_table(name, tmp_path / "merged/tables" / f"{name}.parquet").equals(
            read_table(name, legacy.data_dir / "tables" / f"{name}.parquet"))


def test_import_partial_publications_from_overlapping_readonly_snapshots(tmp_path):
    first = pipeline(tmp_path / "first", refs=True)
    first.crawl_ids(IDS)
    # Newer source is corrupt; fall back to the valid older source.
    later = pipeline(tmp_path / "later", refs=True)
    later.crawl_ids([IDS[0]])
    (later.sources.root / "2412-08848/v1/single.tex").write_text("broken")
    # A torn final manifest line must not be repaired in read-only input.
    with later.manifest.path.open("ab") as stream:
        stream.write(b'{"arxiv')
    before = later.manifest.path.read_bytes()
    output = tmp_path / "output"
    import_cache([first.data_dir, later.data_dir], output, IDS, "arxiv")
    assert later.manifest.path.read_bytes() == before
    assert all(ready(read_cache(output), i, "arxiv") for i in IDS)
    assert not (output / "references").exists()
    assert import_cache([first.data_dir], output, IDS, "arxiv") == 0
    # Only one S2 Publication available: final export must exclude the other.
    import_cache([first.data_dir], output, IDS[:1], "s2")
    result = merge_results([output], tmp_path / "final", IDS)
    assert result["complete"] == 1 and result["pending_ids"] == IDS[1:]
    assert read_table("papers", tmp_path / "final/tables/papers.parquet").num_rows == 1


def test_s2_failure_and_interrupt_keep_partial_results_for_resume(tmp_path):
    worker = pipeline(tmp_path / "s2", refs=True)
    worker.references.references.side_effect = [[], KeyboardInterrupt()]
    assert run_stage(worker, IDS, "s2")["status"] == "stopped"
    assert ready(read_cache(worker.data_dir), IDS[0], "s2")
    worker.references.references.side_effect = None
    worker.references.references.return_value = []
    worker.references.references.reset_mock()
    assert run_stage(worker, IDS, "s2")["status"] == "complete"
    worker.references.references.assert_called_once_with(IDS[1])


def test_archive_roundtrip_and_reject_zip_traversal(tmp_path):
    worker = pipeline(tmp_path / "source")
    run_stage(worker, IDS, "arxiv")
    checkpoint = archive_cache(worker.data_dir, tmp_path / "checkpoint.zip")
    restored = unpack_cache(checkpoint, tmp_path / "restore")
    assert all(ready(read_cache(restored), i, "arxiv") for i in IDS)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        unpack_cache(bad, tmp_path / "unsafe")
    assert not (tmp_path / "escape").exists()


def test_time_budget_and_range_guard(tmp_path):
    worker = pipeline(tmp_path / "job")
    ticks = iter([0, 2])
    result = run_stage(worker, IDS, "arxiv", max_seconds=1, clock=lambda: next(ticks))
    assert result["status"] == "stopped" and result["complete"] == 0
    worker.discovery.discover.assert_not_called()
    with pytest.raises(ValueError, match="Different"):
        run_stage(worker, IDS[:1], "arxiv")


def test_notebooks_compile_and_have_separate_service_outputs():
    root = Path(__file__).resolve().parents[1]
    for stage in ["arxiv", "s2"]:
        nb = json.loads((root / f"notebooks/kaggle_{stage}.ipynb").read_text(encoding="utf-8"))
        source = []
        for cell in nb["cells"]:
            if cell["cell_type"] == "code":
                code = "".join(cell["source"])
                if not code.startswith("%pip"):
                    ast.parse(code)
                    source.append(code)
        joined = "\n".join(source)
        assert f"STAGE = '{stage}'" in joined
        assert "finally:" in joined and "archive_cache" in joined
        assert ("get_secret('S2_API_KEY')" in joined) == (stage == "s2")


def test_bundle_contains_only_code_allowlist_and_verified_service_caches(tmp_path):
    original = pipeline(tmp_path / "original", refs=True)
    original.crawl_ids(IDS)
    (original.data_dir / ".env").write_text("S2_API_KEY=synthetic-secret")
    output = tmp_path / "bundle"
    report = prepare([original.data_dir], output, IDS)
    assert report["counts"] == {"arxiv": {"complete": 2, "pending": 0},
                                 "s2": {"complete": 2, "pending": 0}}
    with zipfile.ZipFile(output / "crawler-code.zip") as archive:
        assert "src/crawl/split.py" in archive.namelist()
        assert not any("get_id_range_script" in name or ".env" in name for name in archive.namelist())
    for stage in ["arxiv", "s2"]:
        with zipfile.ZipFile(output / f"{stage}-seed.zip") as archive:
            assert not any(".env" in name for name in archive.namelist())
            if stage == "s2":
                assert not any(name.startswith("raw/") for name in archive.namelist())
        restored = unpack_cache(output / f"{stage}-seed.zip", tmp_path / stage)
        assert all(ready(read_cache(restored), i, stage) for i in IDS)


def test_local_sequence_reuses_partial_cache_and_exports(tmp_path, monkeypatch):
    old = pipeline(tmp_path / 'old', refs=True)
    old.crawl_ids(IDS[:1])
    calls, workers = [], []
    def factory(settings, stage):
        calls.append(stage)
        worker = pipeline(settings.data_dir, refs=stage == 's2')
        workers.append(worker)
        return worker
    monkeypatch.setattr(crawl_local, 'make_pipeline', factory)
    settings = get_settings({'CONTACT_EMAIL': 'test@example.org'})
    result = crawl_local.run_local(settings, IDS, roots=[old.data_dir], output=tmp_path/'local')
    assert calls == ['arxiv', 's2']
    workers[0].discovery.discover.assert_called_once_with(IDS[1])
    workers[1].references.references.assert_called_once_with(IDS[1])
    assert result['merged']['complete'] == 2
    assert read_table('papers', tmp_path/'local/merged/tables/papers.parquet').num_rows == 2
    calls.clear()
    workers.clear()
    crawl_local.run_local(settings, IDS, roots=[old.data_dir], output=tmp_path/'local')
    workers[0].sources.client._transport.assert_not_called()
    workers[1].references.references.assert_not_called()


def test_local_interrupt_does_not_start_s2(tmp_path, monkeypatch):
    calls = []
    def factory(settings, stage):
        calls.append(stage)
        worker = pipeline(settings.data_dir)
        worker.discovery.discover.side_effect = KeyboardInterrupt()
        return worker
    monkeypatch.setattr(crawl_local, 'make_pipeline', factory)
    result = crawl_local.run_local(get_settings({'CONTACT_EMAIL': 'test@example.org'}),
        IDS, roots=[], output=tmp_path/'local')
    assert calls == ['arxiv']
    assert result['arxiv']['status'] == 'stopped'


def test_local_notebook_has_no_kaggle_dependency():
    root = Path(__file__).resolve().parents[1]
    nb = json.loads((root/'notebooks/local_crawl.ipynb').read_text(encoding='utf-8'))
    source = '\n'.join(''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code')
    ast.parse(source)
    assert 'kaggle_secrets' not in source and '/kaggle/input' not in source
    assert 'run_local' in source and 'cache_roots' in source
