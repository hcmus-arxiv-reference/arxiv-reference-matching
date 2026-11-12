"""Exercise real merge/native calls, failure denominators and tree exports."""

from copy import deepcopy
import hashlib
import json

import pytest

pytest.importorskip("src.parse.Hierarchy._hierarchy_native", reason="Build the native engine first")

from src.parse.Hierarchy import HierarchyEngine
from src.parse.Hierarchy import benchmark
from src.parse.Hierarchy.types import Hierarchy


def source(folder, files):
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")


def article(folder, *, body=r"\section{Intro}\input{part}\input{part}"):
    source(folder, {
        "main.tex": r"\documentclass{article}\begin{document}" + body + r"\end{document}",
        "part.tex": "Nội dung.",
    })


def label(tmp_path, folder):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({folder.parent.name + "/" + folder.name: {
        "main_file": "main.tex", "note": "Fixture root",
        "sha256": hashlib.sha256((folder / "main.tex").read_bytes()).hexdigest(),
    }}))
    return path


def test_selection_prioritizes_tex_and_richest_version(tmp_path):
    source(tmp_path / "2508-02872/v1", {"main.tex": "", "part.tex": ""})
    source(tmp_path / "2508-02872/v2", {"main.tex": "", "part.tex": ""})
    source(tmp_path / "2508-02872/v3", {"main.tex": ""})
    source(tmp_path / "2508-02873/v1", {"main.tex": "", **{f"{i}.bib": "" for i in range(10)}})
    source(tmp_path / "2508-02874/v1", {"refs.bib": ""})
    rows = benchmark.discover_folders(tmp_path)
    assert [row["folder"] for row in rows] == ["2508-02872/v2", "2508-02873/v1"]


def test_expansion_excludes_prior_publications_across_versions(tmp_path):
    raw = tmp_path / "raw"
    article(raw / "2508-02872/v1")
    article(raw / "2508-02872/v2")
    article(raw / "2508-02873/v1")
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps({"results": [{"folder": "2508-02872/v1"}]}))
    report = benchmark.run_benchmark(raw, output_dir=tmp_path / "out", limit=1,
                                     exclude_report=previous)
    assert report["summary"]["target_reached"]
    assert [row["folder"] for row in report["results"]] == ["2508-02873/v1"]
    assert report["config"]["excluded_publications"] == ["2508-02872"]


def test_real_pipeline_exports_ordered_occurrences_and_metadata(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    folder = raw / "2508-02872/v2"
    article(folder)
    report = benchmark.run_benchmark(raw, output_dir=out, labels_path=label(tmp_path, folder), limit=1)
    summary = report["summary"]
    assert summary["target_reached"]
    assert summary["engine_calls"] == summary["parsed_folders"] == summary["complete_folders"] == 1
    assert summary["main_accuracy"] == summary["structure_valid_rate"] == 1
    assert summary["semantic_tree_accuracy"] is None
    row = report["results"][0]
    payload = json.loads((out / row["artifacts"]["tree_json"]).read_text())
    assert payload["arxiv_id"] == "2508.02872" and payload["version"] == 2
    assert all(edge["version"] == 2 for edge in payload["hierarchy"])
    section = next(element for element in payload["elements"] if element["kind"] == "section")
    assert len(payload["ordered_children"][section["element_id"]]) == 2
    preview = (out / row["artifacts"]["tree_md"]).read_text()
    assert preview.count("sentence: Nội dung.") == 2
    assert "Chưa đo được độ chính xác" in (out / "report.md").read_text()
    assert json.loads((out / "report.json").read_text())["summary"] == summary


def test_failed_merge_is_logged_and_selection_continues_until_target(tmp_path):
    raw = tmp_path / "raw"
    article(raw / "2508-02872/v1", body=r"\input{missing}")
    source(raw / "2508-02872/v1", {"unused.tex": ""})  # richest candidate first
    article(raw / "2508-02873/v1")
    report = benchmark.run_benchmark(raw, output_dir=tmp_path / "out", limit=1)
    summary = report["summary"]
    assert summary["attempted_folders"] == 2
    assert summary["merge_success_rate"] == .5
    assert summary["engine_calls"] == 1
    assert report["results"][0]["status"] == "merge_failed"
    assert "missing" in report["results"][0]["error"]
    assert report["results"][1]["status"] == "complete"


def test_diagnostics_keep_partial_tree_without_claiming_accuracy(tmp_path):
    raw = tmp_path / "raw"
    article(raw / "2508-02872/v1", body=r"\section{Intro}Body. \unknown{content}")
    report = benchmark.run_benchmark(raw, output_dir=tmp_path / "out", limit=1)
    row = report["results"][0]
    assert row["status"] == "partial"
    assert row["structure_valid"]
    assert row["diagnostic_counts"]["unhandled_command"] == 1
    assert report["summary"]["complete_rate"] == 0
    assert report["summary"]["main_accuracy"] is None
    assert report["summary"]["semantic_tree_accuracy"] is None


def test_unknown_compilation_branch_is_reported_as_review_with_reason(tmp_path, capsys):
    raw = tmp_path / "raw"
    article(raw / "2508-02872/v1", body=r"\ifdraft\input{part}\fi")
    report = benchmark.run_benchmark(raw, output_dir=tmp_path / "out", limit=1, progress=True)
    assert report["results"][0]["status"] == "merge_needs_review"
    assert report["summary"]["engine_calls"] == 0
    assert "unsupported_conditional" in capsys.readouterr().out


def test_gather_failure_stays_in_labelled_accuracy_denominator(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    folder = raw / "2508-02872/v1"
    article(folder)

    def fail(*args):
        raise OSError("Synthetic gather failure")

    monkeypatch.setattr(benchmark, "build_file_tree", fail)
    report = benchmark.run_benchmark(raw, output_dir=tmp_path / "out", labels_path=label(tmp_path, folder))
    assert report["summary"]["main_accuracy"] == 0
    assert report["summary"]["labelled_main_cases"] == 1
    assert report["summary"]["engine_calls"] == 0
    assert not report["summary"]["target_reached"]


def test_stale_labels_are_excluded(tmp_path):
    raw = tmp_path / "raw"
    folder = raw / "2508-02872/v1"
    article(folder)
    labels = label(tmp_path, folder)
    with (folder / "main.tex").open("a") as stream:
        stream.write("% changed\n")
    report = benchmark.run_benchmark(raw, output_dir=tmp_path / "out", labels_path=labels, limit=1)
    assert report["summary"]["main_accuracy"] is None
    assert "checksum" in report["results"][0]["label_note"]


def test_engine_exception_does_not_prevent_next_case(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    article(raw / "2508-02872/v1")
    article(raw / "2508-02873/v1")
    original = HierarchyEngine.parse

    def parse(engine, latex):
        if r"\input" in latex:
            pytest.fail("Engine must receive merged LaTeX")
        parse.calls += 1
        if parse.calls == 1:
            raise RuntimeError("Synthetic parse failure")
        return original(engine, latex)

    parse.calls = 0
    monkeypatch.setattr(HierarchyEngine, "parse", parse)
    report = benchmark.run_benchmark(raw, output_dir=tmp_path / "out", limit=2)
    assert report["summary"]["engine_calls"] == 2
    assert report["summary"]["engine_return_rate"] == .5
    assert report["results"][0]["status"] == "engine_failed"
    assert report["results"][1]["status"] == "complete"


def test_structure_allows_deduplicated_dag_and_rejects_broken_graphs():
    result = HierarchyEngine("2508.02872", 1).parse(r"\section{A}Same.\section{B}Same.")
    assert benchmark.check_structure(result, "2508.02872", 1) == []
    dangling = deepcopy(result)
    dangling.hierarchy[0].parent_id = "2508-02872#missing"
    assert "Dangling parent_id/element_id" in benchmark.check_structure(dangling, "2508.02872", 1)
    cyclic = deepcopy(result)
    root = next(row.element_id for row in cyclic.elements if row.kind == "document")
    leaf = next(row.element_id for row in cyclic.elements if row.kind == "sentence")
    cyclic.hierarchy.append(Hierarchy("2508.02872", 1, root, leaf))
    cyclic.ordered_children[leaf] = [root]
    errors = benchmark.check_structure(cyclic, "2508.02872", 1)
    assert "Cycle in hierarchy" in errors
    assert "Document root has a parent" in errors
    assert benchmark.check_structure(result, "2508.02873", 2)


def test_preview_is_bounded_and_handles_markdown_fences():
    result = HierarchyEngine("2508.02872", 1).parse(r"\section{````Danger}Same. Same.")
    preview = benchmark.render_tree(result, 2)
    assert preview.startswith("`````text\n")
    assert "Preview limited to 2" in preview
    assert preview.endswith("`````\n")


def test_empty_corpus_and_invalid_arguments(tmp_path):
    report = benchmark.run_benchmark(tmp_path, output_dir=tmp_path / "out")
    assert report["summary"]["attempted_folders"] == 0
    assert report["summary"]["main_accuracy"] is None
    assert not report["summary"]["target_reached"]
    with pytest.raises(ValueError, match="positive"):
        benchmark.run_benchmark(tmp_path, limit=0)
    with pytest.raises(NotADirectoryError):
        benchmark.discover_folders(tmp_path / "missing")
