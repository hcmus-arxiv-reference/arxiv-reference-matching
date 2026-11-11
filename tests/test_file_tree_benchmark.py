"""Verify benchmark selection, independent labels and score denominators."""

import hashlib
import json

import pytest

from src.parse.MultifileGathering import benchmark
from src.parse.MultifileGathering.file_tree import FileTree


def source(folder, files):
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def labels_file(tmp_path, raw):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({
        "paper/v1": {
            "main_file": "main.tex", "note": "Synthetic article root",
            "sha256": hashlib.sha256((raw / "paper/v1/main.tex").read_bytes()).hexdigest(),
        },
    }))
    return path


def test_selection_prefers_many_sources_and_distinct_publications(tmp_path):
    source(tmp_path / "a/v1", {"main.tex": "", "one.tex": "", "refs.bib": ""})
    source(tmp_path / "a/v2", {"main.tex": "", "one.tex": "", "refs.bib": ""})
    source(tmp_path / "b/v1", {"main.tex": "", "refs.bib": ""})
    source(tmp_path / "c/v1", {"only.bib": ""})
    selected = benchmark.select_folders(tmp_path, 2)
    assert [row["folder"] for row in selected] == ["a/v2", "b/v1"]
    assert selected[0]["tex_count"] == 2
    assert selected[0]["bib_count"] == 1


def test_default_selection_contains_ninety_folders(tmp_path):
    for number in range(91):
        source(tmp_path / f"paper-{number:02d}/v1", {"main.tex": ""})
    selected = benchmark.select_folders(tmp_path)
    assert len(selected) == 90
    assert len({row["folder"].split("/")[0] for row in selected}) == 90


def test_calls_once_per_folder_and_writes_separate_outputs(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    source(raw / "paper/v1", {"main.tex": r"\documentclass{article}\input{part}", "part.tex": "Text"})
    source(raw / "unknown/v1", {"only.tex": "Text"})
    labels = labels_file(tmp_path, raw)
    calls = []
    original = benchmark.build_file_tree

    def gather(folder, output):
        calls.append(folder)
        return original(folder, output)

    monkeypatch.setattr(benchmark, "build_file_tree", gather)
    output = tmp_path / "output"
    report = benchmark.run_benchmark(raw, labels_path=labels, output_dir=output)
    assert len(calls) == 2
    assert len(list((output / "trees").glob("*.json"))) == 2
    assert (output / "report.json").is_file()
    assert report["summary"]["main_accuracy"] == 1
    assert report["summary"]["main_label_coverage"] == 0.5
    assert report["summary"]["full_tree_agreement"] == 1


def test_wrong_main_is_counted_against_reviewed_label(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    source(raw / "paper/v1", {
        "a_figure.tex": r"\documentclass{standalone}",
        "main.tex": r"\documentclass{article}\input{part}", "part.tex": "Text",
    })
    monkeypatch.setattr(benchmark, "build_file_tree", lambda folder, output: FileTree("a_figure.tex", ()))
    report = benchmark.run_benchmark(raw, labels_path=labels_file(tmp_path, raw), output_dir=tmp_path / "out")
    assert report["summary"]["main_accuracy"] == 0
    assert report["summary"]["input_false_negative"] == 1
    assert report["summary"]["full_tree_agreement"] == 0


def test_failed_call_stays_in_accuracy_denominator(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    source(raw / "paper/v1", {"main.tex": r"\documentclass{article}"})

    def fail(*args):
        raise OSError("Synthetic failure")

    monkeypatch.setattr(benchmark, "build_file_tree", fail)
    report = benchmark.run_benchmark(raw, labels_path=labels_file(tmp_path, raw), output_dir=tmp_path / "out")
    assert report["summary"]["labelled_main_cases"] == 1
    assert report["summary"]["main_accuracy"] == 0
    assert report["summary"]["successful_calls"] == 0
    assert report["results"][0]["error"] == "OSError: Synthetic failure"


def test_changed_label_is_excluded(tmp_path):
    raw = tmp_path / "raw"
    folder = raw / "paper/v1"
    source(folder, {"main.tex": r"\documentclass{article}"})
    labels = labels_file(tmp_path, raw)
    source(folder, {"main.tex": "Changed"})
    report = benchmark.run_benchmark(raw, labels_path=labels, output_dir=tmp_path / "out")
    assert report["summary"]["main_accuracy"] is None
    assert report["summary"]["unscored_main_cases"] == 1


def test_empty_raw_and_missing_labels_do_not_report_perfect_accuracy(tmp_path):
    report = benchmark.run_benchmark(tmp_path, labels_path=tmp_path / "missing.json", output_dir=tmp_path / "out")
    assert report["summary"]["folders"] == 0
    assert report["summary"]["main_accuracy"] is None
    assert report["summary"]["input_exact_agreement"] is None


def test_invalid_selection_arguments(tmp_path):
    with pytest.raises(NotADirectoryError):
        benchmark.select_folders(tmp_path / "missing")
    with pytest.raises(ValueError):
        benchmark.select_folders(tmp_path, 0)
