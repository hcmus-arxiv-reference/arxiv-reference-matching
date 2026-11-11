"""Offline selection, staged HF downloads and byte-level verification using synthetic data."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import m2_sample
from src.common.config import get_settings, member_ids
from src.common.corpus import FileCorpus
from src.common.json_io import write_json
from src.common.schema import publication_key


def real_plan_from_synthetic_corpus(tmp_path, size=4):
    """Mark a synthetic fixture as corpus input solely to exercise the HF download seam."""
    root = tmp_path / "remote"
    m2_sample.make_mock(root, size=size)
    return root, m2_sample.make_plan(root, size=size)


def fake_hf(monkeypatch, remote):
    info = Mock(return_value=SimpleNamespace(sha="a" * 40))
    monkeypatch.setattr("huggingface_hub.HfApi", lambda **kwargs: SimpleNamespace(repo_info=info))

    def copy_download(settings, path_in_repo, local_dir, *, revision):
        assert revision == "a" * 40
        # The mock remote uses local M1 layout; download_dir returns HF layout.
        key = path_in_repo.split("/")[-1]
        destination = Path(local_dir) / path_in_repo
        shutil.copytree(remote / "raw" / key, destination)
        return destination

    download = Mock(side_effect=copy_download)
    monkeypatch.setattr(m2_sample, "download_dir", download)
    return info, download


def settings():
    return get_settings(env={"HF_TOKEN": "synthetic-token", "HF_REPO_ID": "test/private",
                             "MEMBER_NAME": "minh"})


def test_100_mock_publications_reproduce_plan_bytes_and_keep_every_version(tmp_path):
    first = m2_sample.make_mock(tmp_path / "one")
    second = m2_sample.make_mock(tmp_path / "two")
    write_json(tmp_path / "one.json", first)
    write_json(tmp_path / "two.json", second)
    assert (tmp_path / "one.json").read_bytes() == (tmp_path / "two.json").read_bytes()
    ids = [p["arxiv_id"] for p in first["publications"]]
    assert len(set(ids)) == 100 and set(ids) <= set(member_ids("bao"))
    assert first["data_origin"] == "mock" and first["seed"] == 20261112
    report = m2_sample.verify_sample(first, tmp_path / "one")
    assert (report["verified"], report["versions"], report["non_tex_versions"]) == (100, 199, 20)
    corpus = FileCorpus(tmp_path / "one")
    assert all(corpus.publication(arxiv_id).sources_complete for arxiv_id in ids)
    assert not any(corpus.publication(arxiv_id).complete for arxiv_id in ids)  # no S2 required
    different = m2_sample.make_mock(tmp_path / "other", seed=123)
    assert ids != [p["arxiv_id"] for p in different["publications"]]


def test_eligibility_excludes_invalid_metadata_and_sources_without_modifying_them(tmp_path):
    remote, plan = real_plan_from_synthetic_corpus(tmp_path)
    bad_source, bad_meta = plan["publications"][:2]
    source_path = remote / "raw" / publication_key(bad_source["arxiv_id"]) / "v1" / "source.json"
    source_path.write_text("broken receipt")
    meta_path = remote / "metadata" / f"{publication_key(bad_meta['arxiv_id'])}.json"
    meta_path.write_text("broken metadata")
    actual = m2_sample.make_plan(remote, size=2)
    assert actual["population_count"] == 2
    assert actual["excluded"] == {"missing_metadata": 4996, "invalid_metadata": 1,
                                   "missing_or_invalid_source": 1}
    assert bad_source["arxiv_id"] not in [p["arxiv_id"] for p in actual["publications"]]
    assert source_path.read_text() == "broken receipt" and meta_path.read_text() == "broken metadata"
    with pytest.raises(ValueError, match="Need 100.*found 2"):
        m2_sample.make_plan(remote)


@pytest.mark.parametrize("mutation", ["duplicate", "outside", "missing_version", "unsafe_path", "bad_hash"])
def test_invalid_plans_fail_before_network(tmp_path, monkeypatch, mutation):
    _, plan = real_plan_from_synthetic_corpus(tmp_path)
    if mutation == "duplicate":
        plan["publications"][1] = deepcopy(plan["publications"][0])
    elif mutation == "outside":
        plan["publications"][0]["arxiv_id"] = "2410.00001"
    elif mutation == "missing_version":
        plan["publications"][0]["versions"][0]["version"] = 2
    elif mutation == "unsafe_path":
        plan["publications"][0]["versions"][0]["path_in_repo"] = "raw/bao/../../secret"
    else:
        plan["publications"][0]["metadata_sha256"] = "incorrect"
    network = Mock()
    monkeypatch.setattr(m2_sample, "download_dir", network)
    with pytest.raises(ValueError):
        m2_sample.download_sample(plan, settings(), tmp_path / "local")
    network.assert_not_called()


def test_download_pins_revision_retains_non_tex_and_resumes_offline(tmp_path, monkeypatch):
    remote, plan = real_plan_from_synthetic_corpus(tmp_path)
    info, download = fake_hf(monkeypatch, remote)
    local = tmp_path / "local"
    result = m2_sample.download_sample(plan, settings(), local, revision="sample-tag")
    assert result["verified"] == 4 and result["hf_revision"] == "a" * 40
    assert result["versions"] == 7 and result["non_tex_versions"] == 1
    info.assert_called_once_with(repo_id="test/private", repo_type="dataset", revision="sample-tag")
    assert download.call_count == 4
    assert all(call.args[1].startswith("raw/bao/") for call in download.call_args_list)
    before = {p.relative_to(local): p.read_bytes() for p in local.rglob("*") if p.is_file()}
    info.reset_mock()
    download.reset_mock()
    rerun = m2_sample.download_sample(plan, get_settings(env={}), local)
    assert rerun["verified"] == 4
    info.assert_not_called()
    download.assert_not_called()
    assert before == {p.relative_to(local): p.read_bytes() for p in local.rglob("*") if p.is_file()}
    assert not list(local.glob(".m2-download-*"))


def test_failed_download_does_not_publish_and_retry_reuses_completed_publications(tmp_path, monkeypatch):
    remote, plan = real_plan_from_synthetic_corpus(tmp_path)
    _, download = fake_hf(monkeypatch, remote)
    copier = download.side_effect
    failing_id = plan["publications"][1]["arxiv_id"]

    def fail_second(settings, path, directory, *, revision):
        if publication_key(failing_id) in path:
            raise ConnectionError("synthetic failure")
        return copier(settings, path, directory, revision=revision)

    download.side_effect = fail_second
    local = tmp_path / "local"
    with pytest.raises(ValueError, match="HF download failed: ConnectionError"):
        m2_sample.download_sample(plan, settings(), local)
    assert not (local / "raw" / publication_key(failing_id)).exists()
    assert not list(local.glob(".m2-download-*"))
    download.reset_mock()
    download.side_effect = copier
    assert m2_sample.download_sample(plan, settings(), local)["verified"] == 4
    assert download.call_count == 3


@pytest.mark.parametrize("corrupt", ["tex", "receipt", "metadata", "missing_non_tex"])
def test_offline_verification_reports_bad_publication(tmp_path, corrupt):
    _, plan = real_plan_from_synthetic_corpus(tmp_path)
    local = tmp_path / "remote"
    first = plan["publications"][0]
    directory = local / "raw" / publication_key(first["arxiv_id"]) / "v1"
    if corrupt == "tex":
        # First Publication is non_tex; second has TeX.
        directory = local / "raw" / publication_key(plan["publications"][1]["arxiv_id"]) / "v1"
        (directory / "main.tex").write_text("modified source")
    elif corrupt == "receipt":
        path = directory / "source.json"
        path.write_text(path.read_text() + "\n")  # same JSON, different bytes
    elif corrupt == "metadata":
        path = directory / "metadata.json"
        path.write_text(path.read_text() + "\n")
    else:
        shutil.rmtree(directory)
    report = m2_sample.verify_sample(plan, local)
    assert report["verified"] == 3 and len(report["results"]) == 4
    assert sum(row["status"] == "failed" for row in report["results"]) == 1


def test_corrupt_remote_is_rejected_before_becoming_local_input(tmp_path, monkeypatch):
    remote, plan = real_plan_from_synthetic_corpus(tmp_path)
    item = plan["publications"][0]
    key = publication_key(item["arxiv_id"])
    (remote / "raw" / key / "v1" / "metadata.json").write_text("{}")
    fake_hf(monkeypatch, remote)
    local = tmp_path / "local"
    with pytest.raises(ValueError, match="metadata differs"):
        m2_sample.download_sample(plan, settings(), local)
    assert not (local / "raw" / key).exists()
    assert not list(local.glob(".m2-download-*"))


def test_mock_download_is_refused_and_existing_data_is_preserved(tmp_path):
    mock = m2_sample.make_mock(tmp_path / "mock", size=1)
    with pytest.raises(ValueError, match="Mock plan cannot"):
        m2_sample.download_sample(mock, settings(), tmp_path / "local")
    sentinel = tmp_path / "existing" / "keep.txt"
    sentinel.parent.mkdir()
    sentinel.write_text("user data")
    with pytest.raises(ValueError, match="must be empty"):
        m2_sample.make_mock(sentinel.parent)
    assert sentinel.read_text() == "user data"


def test_cli_mock_verify_and_insufficient_population_preserve_plan(tmp_path, capsys):
    local = tmp_path / "mock"
    output = tmp_path / "plan.json"
    assert m2_sample.main(["mock", "--data-dir", str(local), "--output", str(output), "--size", "3"]) == 0
    assert m2_sample.main(["verify", "--plan", str(output), "--data-dir", str(local)]) == 0
    report = json.loads((local / "sample-report.json").read_text())
    assert report["data_origin"] == "mock" and report["verified"] == 3
    before = output.read_bytes()
    assert m2_sample.main(["make-plan", "--corpus", str(local), "--output", str(output)]) == 2
    assert output.read_bytes() == before
    assert "Need 100" in capsys.readouterr().out


def test_cli_does_not_print_network_exception_secrets(tmp_path, monkeypatch, capsys):
    _, plan = real_plan_from_synthetic_corpus(tmp_path, size=1)
    path = tmp_path / "plan.json"
    write_json(path, plan)
    monkeypatch.setattr(m2_sample, "download_sample", Mock(side_effect=RuntimeError("secret-token")))
    assert m2_sample.main(["download", "--plan", str(path), "--data-dir", str(tmp_path / "local")]) == 2
    output = capsys.readouterr().out
    assert "RuntimeError" in output and "secret-token" not in output


@pytest.mark.parametrize("failure_at", ["metadata", "download"])
def test_sdk_value_errors_do_not_expose_credentials(tmp_path, monkeypatch, capsys, failure_at):
    remote, plan = real_plan_from_synthetic_corpus(tmp_path, size=1)
    info, download = fake_hf(monkeypatch, remote)
    (info if failure_at == "metadata" else download).side_effect = ValueError("secret-token")
    path = tmp_path / "plan.json"
    write_json(path, plan)
    monkeypatch.setattr(m2_sample, "get_settings", settings)
    assert m2_sample.main(["download", "--plan", str(path), "--data-dir", str(tmp_path / "local")]) == 2
    output = capsys.readouterr().out
    assert "ValueError" in output and "secret-token" not in output
