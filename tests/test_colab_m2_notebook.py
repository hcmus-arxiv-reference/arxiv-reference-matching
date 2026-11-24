"""Exercise notebook input adaptation and batched parsing offline with tiny synthetic data."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest

from src.common.config import member_ids
from src.common.corpus import file_digest
from src.common.json_io import write_json
from src.common.schema import publication_key, validate

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "colab_m2_benchmark.ipynb"


def cells():
    return {cell["id"]: "".join(cell["source"]) for cell in json.loads(NOTEBOOK.read_text())["cells"]}


def helpers():
    namespace = {}
    exec(compile(cells()["helpers"], "<notebook:helpers>", "exec"), namespace)
    return SimpleNamespace(**namespace)


def worker():
    # Extract the embedded child-process program without executing notebook side effects.
    import ast

    tree = ast.parse(cells()["worker"])
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "WORKER_SOURCE")
    namespace = {"__name__": "notebook_worker_test"}
    exec(compile(ast.literal_eval(assignment.value), "m2_worker.py", "exec"), namespace)
    return SimpleNamespace(**namespace)


def source(root, aid, statuses=("success", "non_tex", "unavailable")):
    key = publication_key(aid)
    metadata = {"format": 1, "publication": {
        "arxiv_id": aid, "title": "Synthetic benchmark fixture", "authors": ["Example"],
        "submission_date": "2024-09-01", "revised_dates": ["2024-09-02"] * (len(statuses) - 1),
        "venue": None, "versions": len(statuses)}}
    for version, status in enumerate(statuses, 1):
        directory = root / key / f"v{version}"
        directory.mkdir(parents=True)
        files = {}
        if status == "success":
            (directory / "main.tex").write_text(
                r"\documentclass{article}\begin{document}\section{Example}A short sentence.\end{document}")
            files["main.tex"] = file_digest(directory / "main.tex")
        write_json(directory / "source.json", {
            "format": 1, "arxiv_id": aid, "version": version, "status": status,
            "files": files, "checksum": "" if status == "unavailable" else
            hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()})
        write_json(directory / "metadata.json", metadata)


def test_notebook_code_compiles_and_contains_no_outputs():
    notebook = json.loads(NOTEBOOK.read_text())
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), cell["id"], "exec")
            assert not cell["outputs"]
            assert cell["execution_count"] is None
    assert "a800037166da8feff2fbb739a7107e4edb615ad1" in cells()["settings"]
    worker()


@pytest.mark.parametrize("member", ["bao", "minh", "nghiem", "hai", "lieu"])
def test_prepare_any_range_retains_empty_versions_and_missing_ids(tmp_path, member):
    aid, missing = list(member_ids(member))[:2]
    remote = tmp_path / "remote"
    source(remote, aid)
    result = helpers().prepare_corpus([aid, missing], tmp_path / "corpus", remote)
    assert result[0]["status"] == "verified"
    assert result[0]["source_statuses"] == {"success": 1, "non_tex": 1, "unavailable": 1}
    assert result[1] == {"arxiv_id": missing, "status": "missing_metadata", "versions": None}
    # A rerun works entirely from local verified data.
    assert helpers().prepare_corpus([aid, missing], tmp_path / "corpus", remote) == result


def test_prepare_reports_missing_source_and_rejects_corruption(tmp_path):
    aid = next(member_ids("minh"))
    remote = tmp_path / "remote"
    source(remote, aid)
    (remote / publication_key(aid) / "v2" / "source.json").unlink()
    corpus = tmp_path / "corpus"
    result = helpers().prepare_corpus([aid], corpus, remote)
    assert result[0]["missing_versions"] == [2]
    tex = corpus / "raw" / publication_key(aid) / "v1" / "main.tex"
    tex.write_text("corrupt fixture")
    with pytest.raises(ValueError, match="checksum/receipt"):
        helpers().prepare_corpus([aid], corpus, remote)
    assert tex.read_text() == "corrupt fixture"


def test_hf_folder_resolution_never_substitutes_another_member():
    RepoFolder = type("RepoFolder", (), {})

    def folder(path):
        result = RepoFolder()
        result.path = path
        return result

    api = SimpleNamespace(list_repo_tree=lambda *a, **kw: [folder("raw/bao"), folder("raw/nhminh107")])
    h = helpers()
    assert h.choose_hf_member(api, "test/private", "a" * 40, "minh") == "nhminh107"
    with pytest.raises(ValueError, match="Không xác định"):
        h.choose_hf_member(api, "test/private", "a" * 40, "hai")


def test_download_lists_selected_subtrees_and_pins_every_file(tmp_path, monkeypatch):
    RepoFile = type("RepoFile", (), {})
    seen_roots, downloads = [], []
    ids = list(member_ids("minh"))[:2]

    def tree(*args, **kwargs):
        seen_roots.append(kwargs["path_in_repo"])
        assert kwargs["revision"] == "a" * 40
        entries = []
        for name in ("source.json", "references.json", "paper.pdf"):
            entry = RepoFile()
            entry.path = kwargs["path_in_repo"] + "/v1/" + name
            entries.append(entry)
        return entries

    def download(repo_id, filename, **kwargs):
        assert kwargs["revision"] == "a" * 40
        assert kwargs["token"] == "synthetic-token"
        downloads.append(filename)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    count = helpers().download_inputs(SimpleNamespace(list_repo_tree=tree), "test/private", "a" * 40,
                                     "minh", ids, tmp_path, "synthetic-token")
    assert seen_roots == [f"raw/minh/{publication_key(aid)}" for aid in ids]
    assert count == len(downloads) == 2


def test_batched_worker_merges_tables_and_labels_resume(tmp_path):
    ids = list(member_ids("minh"))[:3]
    remote = tmp_path / "remote"
    for aid in ids:
        source(remote, aid)
    corpus = tmp_path / "corpus"
    h = helpers()
    report = h.prepare_corpus(ids, corpus, remote)
    output = tmp_path / "results"
    write_json(output / "input-report.json", {"publications": report})
    segment = output / "benchmarks" / "one"
    config = {"corpus": str(corpus), "output": str(output), "segment": str(segment),
              "ids": ids, "batch_size": 2, "member": "minh", "code_sha": "a" * 40,
              "hf_sha": "b" * 40, "range_ids": 5000, "requested_ids": 4, "test_run": True}
    w = worker()
    first = w.run(config)
    assert first["publications_total"] == first["publications_succeeded"] == 3
    assert first["metadata_missing_ids"] == 1
    assert first["range_success_rate"] == 0.75
    assert first["versions_total_metadata"] == 9
    assert first["versions_empty_non_tex"] == first["versions_empty_unavailable"] == 3
    assert first["run_kind"] == "fresh"
    assert first["version_coverage_rate"] == 1
    for name, count in [("elements", "elements_after_dedup"), ("hierarchy", "hierarchy_edges"),
                        ("bibtex", "bibtex_entries_after_dedup")]:
        table = pq.read_table(output / "tables" / f"{name}.parquet")
        assert validate(table, name) == []
        assert table.num_rows == first[count]
    config["segment"] = str(output / "benchmarks" / "two")
    second = w.run(config)
    assert second["run_kind"] == "resume_only"
    assert second["publications_resumed"] == 3
    assert len((output / "log" / "versions.jsonl").read_text().splitlines()) == 9
