"""Independent tiny annotations exercise provenance, scoring and coverage."""

from copy import deepcopy
import hashlib
import json

import pytest

from src.parse.Hierarchy.compare_reference import compare_case, run_comparison, validate_reference

SOURCE = r"\section{Intro}Same. Same.".encode()
FOLDER = "2508-02872/v1"


def annotation():
    nodes = [
        {"id": "n0", "kind": "document", "content": "", "children": ["n1"]},
        {"id": "n1", "kind": "section", "content": "Intro", "children": ["n2", "n3"]},
        {"id": "n2", "kind": "sentence", "content": "Same.", "children": []},
        {"id": "n3", "kind": "sentence", "content": "Same.", "children": []},
    ]
    for node in nodes:
        node.update(source_start=0, source_end=len(SOURCE))
    return {"format_version": 1, "folder": FOLDER,
            "latex_sha256": hashlib.sha256(SOURCE).hexdigest(), "annotator": "Fixture reviewer",
            "annotation_status": "reviewed", "scope": "full", "root_id": "n0",
            "nodes": nodes, "uncertainties": [], "notes": "Manually specified test fixture"}


def prediction():
    return {"latex_sha256": hashlib.sha256(SOURCE).hexdigest(), "roots": ["root"],
            "elements": [{"element_id": "root", "kind": "document", "content": ""},
                         {"element_id": "section", "kind": "section", "content": "Intro"},
                         {"element_id": "sentence", "kind": "sentence", "content": "Same."}],
            "ordered_children": {"root": ["section"], "section": ["sentence", "sentence"]}}


def fixture_report(tmp_path):
    (tmp_path / "merged.tex").write_bytes(SOURCE)
    (tmp_path / "tree.json").write_text(json.dumps(prediction()))
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps({"results": [
        {"folder": FOLDER, "parsed": True, "latex_sha256": hashlib.sha256(SOURCE).hexdigest(),
         "artifacts": {"merged_tex": "merged.tex", "tree_json": "tree.json"}},
        {"folder": "2508-02873/v1", "parsed": False},
    ]}))
    return path


def test_independent_occurrence_ids_match_deduplicated_production_ids():
    gold = annotation()
    assert validate_reference(gold, SOURCE, FOLDER) == []
    result = compare_case(prediction(), gold)
    assert result["tree_exact"]
    assert result["leaf_content"] == {"matched": 2, "predicted": 2, "expected": 2,
                                      "precision": 1, "recall": 1, "f1": 1}
    assert result["parent_child"]["matched"] == 3


def test_content_mismatch_is_counted_without_affecting_outline():
    gold = annotation()
    gold["nodes"][3]["content"] = "Different."
    result = compare_case(prediction(), gold)
    assert not result["tree_exact"]
    assert result["leaf_content"]["f1"] == .5
    assert result["outline_exact"]


def test_root_label_choice_does_not_change_semantic_agreement():
    gold = annotation()
    gold["nodes"][0]["content"] = "Publication title"
    assert compare_case(prediction(), gold)["tree_exact"]


def test_reordering_children_changes_full_tree_even_if_content_bag_matches():
    gold = annotation()
    gold["nodes"][2]["content"] = "Other."
    actual = prediction()
    actual["elements"].append({"element_id": "other", "kind": "sentence", "content": "Other."})
    actual["ordered_children"]["section"] = ["sentence", "other"]
    result = compare_case(actual, gold)
    assert not result["tree_exact"]
    assert result["leaf_content"]["f1"] == 1


@pytest.mark.parametrize("scope,uncertainties", [("partial", []), ("outline", []), ("full", [{"reason": "Ambiguous"}])])
def test_partial_and_uncertain_references_cannot_score_full_tree(scope, uncertainties):
    gold = annotation()
    gold.update(scope=scope, uncertainties=uncertainties)
    assert "tree_exact" not in compare_case(prediction(), gold)
    if scope == "full":
        assert compare_case(prediction(), gold)["draft_full"]["tree_exact"]


def test_validator_rejects_changed_sources_dangling_reused_and_orphan_nodes():
    gold = annotation()
    assert "Reference checksum does not match source" in validate_reference(gold, SOURCE + b"%", FOLDER)
    dangling = deepcopy(gold)
    dangling["nodes"][1]["children"].append("missing")
    assert "Dangling child references" in validate_reference(dangling, SOURCE, FOLDER)
    reused = deepcopy(gold)
    reused["nodes"][1]["children"] = ["n2", "n2"]
    errors = validate_reference(reused, SOURCE, FOLDER)
    assert "Occurrence tree must have one parent per non-root node" in errors
    assert "Unreachable reference nodes" in errors
    assert validate_reference([], SOURCE, FOLDER)


def test_validator_rejects_utf8_byte_offsets_in_middle_of_character():
    source = "Đầu.".encode()
    gold = annotation()
    gold["latex_sha256"] = hashlib.sha256(source).hexdigest()
    gold["nodes"] = [{**gold["nodes"][0], "children": [], "source_start": 1, "source_end": len(source)}]
    assert any("UTF-8" in error for error in validate_reference(gold, source, FOLDER))


def test_comparison_persists_coverage_and_does_not_claim_missing_labels_are_correct(tmp_path):
    report_path = fixture_report(tmp_path)
    references = tmp_path / "references"
    first = run_comparison(report_path, references_dir=references)
    assert first["summary"]["tree_exact_agreement"] is None
    assert first["summary"]["status_counts"] == {"missing_reference": 1}
    (references / "labels").mkdir()
    gold = annotation()
    gold["annotation_status"] = "draft"
    (references / "labels/2508-02872_v1.json").write_text(json.dumps(gold))
    scored = run_comparison(report_path, references_dir=references)
    summary = scored["summary"]
    assert summary["benchmark_cases"] == 1
    assert summary["full_tree_scored_cases"] == summary["draft_reference_cases"] == 1
    assert summary["tree_exact_agreement"] == summary["leaf_content_micro"]["f1"] == 1
    assert json.loads((references / "comparison/report.json").read_text())["summary"] == summary
    (tmp_path / "merged.tex").write_bytes(SOURCE + b"changed")
    invalid = run_comparison(report_path, references_dir=references)
    assert invalid["summary"]["status_counts"] == {"invalid_reference": 1}
    assert invalid["summary"]["tree_exact_agreement"] is None


def test_engine_exception_with_valid_reference_counts_as_incorrect(tmp_path):
    report_path = fixture_report(tmp_path)
    report = json.loads(report_path.read_text())
    report["results"][0].update(parsed=False, engine_called=True)
    report_path.write_text(json.dumps(report))
    references = tmp_path / "references"
    (references / "labels").mkdir(parents=True)
    (references / "labels/2508-02872_v1.json").write_text(json.dumps(annotation()))
    scored = run_comparison(report_path, references_dir=references)
    assert scored["summary"]["status_counts"] == {"prediction_failed": 1}
    assert scored["summary"]["full_tree_scored_cases"] == 1
    assert scored["summary"]["tree_exact_agreement"] == 0
    assert scored["summary"]["leaf_content_micro"]["recall"] == 0
