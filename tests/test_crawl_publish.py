"""Upload tests exercise real Parquet merging against an in-memory Hub contract."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.common.config import get_settings
from src.common.schema import from_records, read_table, write_table
from src.crawl.discovery import Publication
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.pipeline import CrawlPipeline
from src.crawl.publish import HuggingFacePublisher
from src.crawl.source import ArxivSourceDownloader
from src.crawl import api as workflow


class FakeHub:
    def __init__(self, root):
        self.root = root; root.mkdir()
        self.sha = "initial"; self.private = True
        self.files = {}; self.commits = []; self.fail = False

    def repo_info(self, **kwargs):
        siblings = [SimpleNamespace(rfilename=name, blob_id=hashlib.sha1(
            f"blob {len(body)}\0".encode() + body).hexdigest(), lfs=None) for name, body in self.files.items()]
        return SimpleNamespace(private=self.private, sha=self.sha, siblings=siblings)

    def hf_hub_download(self, *, filename, revision, **kwargs):
        assert revision == self.sha
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.files[filename])
        return str(path)

    def create_commit(self, *, operations, parent_commit, **kwargs):
        if self.fail:
            raise RuntimeError("synthetic upload failure")
        assert parent_commit == self.sha
        paths = []
        for operation in operations:
            self.files[operation.path_in_repo] = Path(operation.path_or_fileobj).read_bytes()
            paths.append(operation.path_in_repo)
        self.commits.append(paths)
        self.sha = f"commit-{len(self.commits)}"
        return SimpleNamespace(oid=self.sha)


def settings(root):
    return get_settings(env={"HF_TOKEN": "synthetic", "HF_REPO_ID": "test/dataset",
                             "MEMBER_NAME": "bao", "CONTACT_EMAIL": "test@example.invalid", "DATA_DIR": str(root)})


def bundle(root, identifier="2508.02872", *, pdf=False, with_references=True):
    discovery = Mock()
    discovery.discover.return_value = Publication(identifier, "Title", ["Alice"], "2025-08-04", [], None, 1)
    client = HttpClient("offline", transport=lambda *_: HttpResponse(200, {}, b"%PDF-1.7\n" if pdf else b"\\documentclass{article}"))
    references = Mock(); references.references.return_value = []
    pipeline = CrawlPipeline(discovery, ArxivSourceDownloader(client, root / "raw"), root,
                             references if with_references else None)
    pipeline.crawl_ids([identifier])
    return pipeline.export([identifier], require_references=with_references)


def test_upload_is_atomic_scoped_and_idempotent(tmp_path):
    data = tmp_path / "data"; hub = FakeHub(tmp_path / "hub")
    bundles, tables = bundle(data)
    publisher = HuggingFacePublisher(settings(data), api=hub)
    assert publisher.publish(bundles, tables)["status"] == "uploaded"
    paths = hub.commits[0]
    assert all(p.startswith(("raw/bao/", "tables/bao/")) for p in paths)
    assert "raw/bao/2508-02872/v1/single.tex" in paths
    assert "raw/bao/2508-02872/v1/references.json" in paths
    assert "tables/bao/references.parquet" in paths
    assert not any(".env" in p or "source.ok" in p for p in paths)
    assert publisher.publish(bundles, tables)["status"] == "unchanged"
    assert len(hub.commits) == 1


def test_merging_second_batch_preserves_remote_papers_and_other_member(tmp_path):
    data = tmp_path / "data"; hub = FakeHub(tmp_path / "hub")
    hub.files["raw/other/keep.txt"] = b"unchanged"
    publisher = HuggingFacePublisher(settings(data), api=hub)
    publisher.publish(*bundle(data))
    publisher.publish(*bundle(data, "2508.02873"))
    path = hub.hf_hub_download(filename="tables/bao/papers.parquet", revision=hub.sha)
    assert {r["arxiv_id"] for r in read_table("papers", path).to_pylist()} == {"2508.02872", "2508.02873"}
    assert hub.files["raw/other/keep.txt"] == b"unchanged"


def test_merge_replaces_reference_rows_only_for_successful_publications(tmp_path):
    data = tmp_path / "data"; hub = FakeHub(tmp_path / "hub")
    def reference(identifier):
        return {"arxiv_id": identifier, "ref_arxiv_id": "1706.03762", "ref_title": "Old", "ref_authors": [],
                "ref_submission_date": None, "ref_s2_id": None}
    path = tmp_path / "refs.parquet"
    write_table(from_records([reference("2508.02872"), reference("2508.02873")], "references"), "references", path)
    hub.files["tables/bao/references.parquet"] = path.read_bytes()
    HuggingFacePublisher(settings(data), api=hub).publish(*bundle(data))
    path = hub.hf_hub_download(filename="tables/bao/references.parquet", revision=hub.sha)
    assert [r["arxiv_id"] for r in read_table("references", path).to_pylist()] == ["2508.02873"]


def test_source_only_mode_leaves_existing_references_table_untouched(tmp_path):
    data = tmp_path / "data"; hub = FakeHub(tmp_path / "hub")
    hub.files["tables/bao/references.parquet"] = b"unread because not selected"
    HuggingFacePublisher(settings(data), api=hub).publish(*bundle(data, with_references=False))
    assert hub.files["tables/bao/references.parquet"] == b"unread because not selected"


def test_non_tex_upload_retains_receipt_without_fake_tex(tmp_path):
    data = tmp_path / "data"; hub = FakeHub(tmp_path / "hub")
    HuggingFacePublisher(settings(data), api=hub).publish(*bundle(data, pdf=True))
    assert "raw/bao/2508-02872/v1/source.json" in hub.files
    assert not any(p.endswith(".tex") for p in hub.files)


def test_failed_upload_can_retry_without_success_receipt(tmp_path):
    data = tmp_path / "data"; hub = FakeHub(tmp_path / "hub")
    bundles, tables = bundle(data)
    publisher = HuggingFacePublisher(settings(data), api=hub)
    hub.fail = True
    with pytest.raises(RuntimeError):
        publisher.publish(bundles, tables)
    assert not (data / "manifests/last-upload.json").exists()
    hub.fail = False
    assert publisher.publish(bundles, tables)["status"] == "uploaded"


def test_public_repo_and_corrupt_source_never_upload(tmp_path):
    data = tmp_path / "data"; hub = FakeHub(tmp_path / "hub")
    bundles, tables = bundle(data)
    publisher = HuggingFacePublisher(settings(data), api=hub)
    hub.private = False
    with pytest.raises(ValueError, match="private"):
        publisher.publish(bundles, tables)
    hub.private = True
    (bundles[0]["sources"][0].path / "single.tex").write_text("tampered")
    with pytest.raises(ValueError, match="Source changed"):
        publisher.publish(bundles, tables)
    assert not hub.commits


def test_remote_revision_change_rejected_before_commit(tmp_path):
    data = tmp_path / "data"; hub = FakeHub(tmp_path / "hub")
    publisher = HuggingFacePublisher(settings(data), api=hub)
    info = hub.repo_info
    count = [0]
    def changing(**kwargs):
        count[0] += 1
        if count[0] == 2:
            hub.sha = "someone-else"
        return info(**kwargs)
    hub.repo_info = changing
    with pytest.raises(RuntimeError, match="changed"):
        publisher.publish(*bundle(data))
    assert not hub.commits


def test_conflicting_remote_source_receipt_rejected(tmp_path):
    data = tmp_path / "data"; hub = FakeHub(tmp_path / "hub")
    hub.files["raw/bao/2508-02872/v1/source.json"] = b'{}'
    with pytest.raises(ValueError, match="conflicts"):
        HuggingFacePublisher(settings(data), api=hub).publish(*bundle(data))
    assert not hub.commits


def test_public_python_api_crawl_upload_then_upload_only(tmp_path, monkeypatch):
    from tests.test_crawl_pipeline import feed
    data = tmp_path / "data"; hub = FakeHub(tmp_path / "hub")
    calls = []
    def transport(request, _):
        calls.append(request.full_url)
        if "/api/query" in request.full_url:
            return HttpResponse(200, {}, feed(1))
        if "semanticscholar" in request.full_url:
            return HttpResponse(200, {}, b'{"data":[]}')
        return HttpResponse(200, {}, b"\\documentclass{article}")
    monkeypatch.setattr(workflow, "HttpClient", lambda user_agent, **kwargs: HttpClient(
        user_agent, transport=transport, sleeper=lambda _: None, **kwargs))
    monkeypatch.setattr(workflow, "HuggingFacePublisher", lambda s: HuggingFacePublisher(s, api=hub))
    result = workflow.run_crawl(["2508.02872"], settings=settings(data), upload=True)
    assert result["counts"]["ready"] == 1 and result["uploads"][0]["status"] == "uploaded"
    calls.clear()
    result = workflow.run_crawl(["2508.02872"], settings=settings(data), upload=True, upload_only=True)
    assert not calls and result["uploads"][0]["status"] == "unchanged"
