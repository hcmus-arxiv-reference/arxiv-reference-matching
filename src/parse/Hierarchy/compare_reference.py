"""Compare benchmark trees with independently annotated occurrence trees.

Agreement with AI-assisted draft references is not independently verified parser
accuracy. Partial/outline annotations are never counted as full-tree references.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

if __name__ == "__main__" and not __package__:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.common.schema import ELEMENT_KINDS
from src.parse.Hierarchy.benchmark import DEFAULT_OUTPUT, write_json

DEFAULT_REFERENCES = DEFAULT_OUTPUT.parent / "gold_reference"
HEADINGS = {"chapter", "section", "subsection", "subsubsection", "paragraph"}
LEAVES = {"sentence", "formula", "figure"}


def validate_reference(label: dict, source: bytes, folder: str) -> list[str]:
    """Check annotation provenance, occurrence graph and UTF-8 evidence ranges."""
    if not isinstance(label, dict):
        return ["Reference must be a JSON object"]
    errors = []
    if label.get("format_version") != 1 or label.get("folder") != folder:
        errors.append("Wrong format_version/folder")
    if label.get("latex_sha256") != hashlib.sha256(source).hexdigest():
        errors.append("Reference checksum does not match source")
    if label.get("scope") not in {"full", "partial", "outline"}:
        errors.append("Invalid annotation scope")
    if label.get("annotation_status") not in {"draft", "reviewed"} or not label.get("annotator"):
        errors.append("Missing annotation provenance")
    if not isinstance(label.get("uncertainties"), list):
        errors.append("Missing uncertainty list")
    rows = label.get("nodes")
    if not isinstance(rows, list) or not rows:
        return errors + ["No reference nodes"]
    if any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in rows):
        return errors + ["Invalid node IDs"]
    nodes = {row["id"]: row for row in rows}
    if len(nodes) != len(rows):
        errors.append("Duplicate occurrence IDs")
    parents = Counter()
    for row in rows:
        if row.get("kind") not in ELEMENT_KINDS or not isinstance(row.get("content"), str):
            errors.append(f"Invalid kind/content: {row['id']}")
        children = row.get("children")
        if not isinstance(children, list) or any(not isinstance(child, str) for child in children):
            return errors + [f"Invalid children: {row['id']}"]
        if row.get("kind") in LEAVES and children:
            errors.append(f"Leaf has children: {row['id']}")
        parents.update(children)
        start, end = row.get("source_start"), row.get("source_end")
        if (type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(source)
                or any(offset < len(source) and source[offset] & 0xC0 == 0x80
                       for offset in (start, end))):
            errors.append(f"Invalid UTF-8 evidence range: {row['id']}")
    if set(parents) - nodes.keys():
        errors.append("Dangling child references")
    root = label.get("root_id")
    if (root not in nodes or nodes[root].get("kind") != "document"
            or sum(row.get("kind") == "document" for row in rows) != 1):
        return errors + ["Expected one document root"]
    if parents[root] or any(parents[node] != 1 for node in nodes if node != root):
        errors.append("Occurrence tree must have one parent per non-root node")
    seen = set()
    pending = [root]
    while pending:
        node = pending.pop()
        if node in seen:
            errors.append("Cycle or reused occurrence ID")
            break
        seen.add(node)
        pending.extend(child for child in nodes[node]["children"] if child in nodes)
    if seen != nodes.keys():
        errors.append("Unreachable reference nodes")
    return errors


def tree_features(nodes: dict, root: str) -> dict:
    """Expand occurrences in order, including repeated production Element IDs."""
    ordered = []
    contents, leaves, edges = Counter(), Counter(), Counter()
    outline = []
    pending = [(root, (), None, (), frozenset())]
    while pending:
        node_id, path, parent, headings, ancestors = pending.pop()
        if node_id in ancestors:
            raise ValueError("Cycle while expanding tree")
        node = nodes[node_id]
        # The specification gives the document root no fixed textual label.
        content = "" if node["kind"] == "document" else node["content"]
        identity = (node["kind"], re.sub(r"\s+", " ", content).strip())
        ordered.append((path, *identity))
        contents[identity] += 1
        if identity[0] in LEAVES:
            leaves[identity] += 1
        if parent is not None:
            edges[(*parent, *identity)] += 1
        if identity[0] in HEADINGS:
            outline.append((*headings, identity))
            headings = (*headings, identity)
        for index in range(len(node["children"]) - 1, -1, -1):
            pending.append((node["children"][index], (*path, index), identity,
                            headings, ancestors | {node_id}))
    return {"ordered": ordered, "contents": contents, "leaves": leaves,
            "edges": edges, "outline": outline}


def overlap(predicted: Counter, expected: Counter) -> dict:
    """Multiset precision/recall/F1, preserving repeated occurrences."""
    matched = sum((predicted & expected).values())
    predicted_count, expected_count = sum(predicted.values()), sum(expected.values())
    return {"matched": matched, "predicted": predicted_count, "expected": expected_count,
            "precision": matched / predicted_count if predicted_count else (1.0 if not expected_count else 0.0),
            "recall": matched / expected_count if expected_count else (1.0 if not predicted_count else 0.0),
            "f1": 2 * matched / (predicted_count + expected_count) if predicted_count + expected_count else 1.0}


def compare_case(prediction: dict | None, label: dict) -> dict:
    if prediction is None:
        actual = {"ordered": [], "contents": Counter(), "leaves": Counter(),
                  "edges": Counter(), "outline": []}
    else:
        nodes = {row["element_id"]: {**row, "children": prediction["ordered_children"].get(row["element_id"], [])}
                 for row in prediction["elements"]}
        if len(prediction["roots"]) != 1:
            raise ValueError("Prediction must have exactly one document root")
        actual = tree_features(nodes, prediction["roots"][0])
    expected = tree_features({row["id"]: row for row in label["nodes"]}, label["root_id"])
    result = {"outline_exact": prediction is not None and actual["outline"] == expected["outline"],
              "outline": overlap(Counter(actual["outline"]), Counter(expected["outline"]))}
    # A partial annotation cannot establish full-tree correctness or recall.
    if label["scope"] == "full":
        draft = dict(tree_exact=actual["ordered"] == expected["ordered"],
                      structure_exact=([item[:2] for item in actual["ordered"]]
                                       == [item[:2] for item in expected["ordered"]]),
                      ordered_structure=overlap(Counter(item[:2] for item in actual["ordered"]),
                                                Counter(item[:2] for item in expected["ordered"])),
                      node_content=overlap(actual["contents"], expected["contents"]),
                      leaf_content=overlap(actual["leaves"], expected["leaves"]),
                      parent_child=overlap(actual["edges"], expected["edges"]))
        result["draft_full"] = draft
        if not label["uncertainties"]:
            result.update(draft)
    return result


def run_comparison(report_path: str | Path | None = None, *,
                   references_dir: str | Path = DEFAULT_REFERENCES,
                   output_dir: str | Path | None = None) -> dict:
    """Read fixed benchmark predictions and references without running a parser."""
    references_dir = Path(references_dir).resolve()
    if report_path is None:
        baseline = references_dir / "baseline/report.json"
        report_path = baseline if baseline.is_file() else DEFAULT_OUTPUT / "report.json"
    report_path = Path(report_path).resolve()
    output_dir = Path(output_dir).resolve() if output_dir else references_dir / "comparison"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    results = []
    for case in report["results"]:
        if not case.get("engine_called", case["parsed"]):
            continue
        row = {"folder": case["folder"], "status": "missing_reference"}
        label_path = references_dir / "labels" / (case["folder"].replace("/", "_") + ".json")
        if label_path.is_file():
            try:
                label = json.loads(label_path.read_text(encoding="utf-8"))
                if not isinstance(label, dict):
                    raise ValueError("Reference must be a JSON object")
                source = (report_path.parent / case["artifacts"]["merged_tex"]).read_bytes()
                errors = validate_reference(label, source, case["folder"])
                if hashlib.sha256(source).hexdigest() != case["latex_sha256"]:
                    errors.append("Benchmark source changed since prediction")
                row.update(scope=label.get("scope"), annotation_status=label.get("annotation_status"),
                           annotator=label.get("annotator"), reference_errors=errors,
                           reference_path=str(label_path),
                           reference_sha256=hashlib.sha256(label_path.read_bytes()).hexdigest())
                if errors:
                    row["status"] = "invalid_reference"
                else:
                    prediction = None
                    if case["parsed"]:
                        prediction = json.loads((report_path.parent / case["artifacts"]["tree_json"]).read_text())
                        if prediction["latex_sha256"] != case["latex_sha256"]:
                            raise ValueError("Prediction checksum does not match benchmark")
                    row.update(status="compared" if prediction is not None else "prediction_failed",
                               agreement=compare_case(prediction, label))
                    row["uncertainties"] = label["uncertainties"]
            except (OSError, ValueError, KeyError, TypeError) as error:
                row.update(status="comparison_failed", error=f"{type(error).__name__}: {error}")
        results.append(row)
    compared = [row for row in results if row["status"] in {"compared", "prediction_failed"}]
    full = [row for row in compared if "tree_exact" in row["agreement"]]
    outline = [row for row in compared if row["scope"] in {"full", "outline"} and not row["uncertainties"]]
    summary = {"benchmark_cases": len(results), "status_counts": dict(Counter(row["status"] for row in results)),
               "compared_cases": len(compared), "full_tree_scored_cases": len(full),
               "tree_exact_matches": sum(row["agreement"]["tree_exact"] for row in full),
               "tree_exact_agreement": (sum(row["agreement"]["tree_exact"] for row in full) / len(full) if full else None),
               "structure_exact_agreement": (sum(row["agreement"]["structure_exact"] for row in full) / len(full)
                                             if full else None),
               "outline_scored_cases": len(outline),
               "outline_exact_agreement": (sum(row["agreement"]["outline_exact"] for row in outline) / len(outline)
                                           if outline else None),
               "draft_reference_cases": sum(row["annotation_status"] == "draft" for row in compared)}
    for feature in ("ordered_structure", "node_content", "leaf_content", "parent_child", "outline"):
        scored = outline if feature == "outline" else full
        totals = Counter()
        for row in scored:
            totals.update({key: row["agreement"][feature][key] for key in ("matched", "predicted", "expected")})
        matched, predicted, expected = (totals[key] for key in ("matched", "predicted", "expected"))
        summary[feature + "_micro"] = {
            **dict(totals), "precision": matched / predicted if scored and predicted else None,
            "recall": matched / expected if scored and expected else None,
            "f1": 2 * matched / (predicted + expected) if scored and predicted + expected else None}
    # Keep an explicitly provisional view of all full-scope draft annotations,
    # including uncertain ones, separate from the filtered scores above.
    draft_full = [row for row in compared if "draft_full" in row["agreement"]]
    provisional = {"cases": len(draft_full),
                   "uncertain_cases": sum(bool(row["uncertainties"]) for row in draft_full),
                   "interpretation": "Provisional agreement including uncertain AI labels; not verified accuracy."}
    for feature in ("node_content", "leaf_content", "parent_child", "outline"):
        totals = Counter()
        for row in draft_full:
            scores = row["agreement"] if feature == "outline" else row["agreement"]["draft_full"]
            totals.update({key: scores[feature][key] for key in ("matched", "predicted", "expected")})
        matched, predicted, expected = (totals[key] for key in ("matched", "predicted", "expected"))
        provisional[feature + "_micro"] = {
            **dict(totals), "precision": matched / predicted if predicted else None,
            "recall": matched / expected if expected else None,
            "f1": 2 * matched / (predicted + expected) if predicted + expected else None}
    summary["provisional_all_full_scope"] = provisional
    output = {"report_path": str(report_path), "references_dir": str(references_dir),
              "interpretation": "Agreement with independently generated references; draft AI annotations require review. "
                                "Not verified semantic accuracy. Document root labels are ignored; body content comparison collapses whitespace only; "
                                "cleaning differences count as mismatches. Partial/uncertain labels are excluded from full-tree scores.",
              "summary": summary, "results": results}
    write_json(output_dir / "report.json", output)
    text = ["# Đối chiếu với cây tham chiếu Agy", "",
            "Đây là mức khớp với nhãn tham chiếu. Nhãn do AI tạo còn cần kiểm tra; "
            "không đồng nhất chỉ số này với độ chính xác đã được xác minh.", "",
            "Nhãn văn bản của gốc document không được chấm vì đề không quy định nhãn cố định. "
            "Nội dung thân bài chỉ được gộp khoảng trắng trước khi so; khác biệt làm sạch vẫn tính sai. "
            "So sánh đầy đủ giữ thứ tự, cấp phân nhánh và từng lần xuất hiện, kể cả nút lặp. "
            "Nhãn thiếu, không hợp lệ, partial hoặc còn uncertainty không được tính điểm toàn cây.", "",
            f"Có {len(compared)}/{len(results)} ca đã đối chiếu. "
            f"{len(full)} ca có nhãn full không còn uncertainty; "
            f"{provisional['uncertain_cases']} ca full còn uncertainty. "
            f"{summary['draft_reference_cases']} nhãn vẫn ở trạng thái draft.", "",
            "Bảng dưới đo mức khớp F1 với bản tham chiếu, không phải độ chính xác đã xác minh. "
            "Cột tất cả bản nháp giữ cả những nhãn còn uncertainty để phục vụ rà soát.", "",
            "| Chỉ số F1 | Nhãn full không uncertainty | Tất cả nhãn full, tạm tính |",
            "|---|---:|---:|"]
    for title, feature in (("Khung heading", "outline"), ("Nội dung nút", "node_content"),
                           ("Nội dung lá", "leaf_content"), ("Cặp cha/con", "parent_child")):
        clean = summary[feature + "_micro"]["f1"]
        draft = provisional[feature + "_micro"]["f1"]
        clean_text = f"{clean:.2%}" if clean is not None else "—"
        draft_text = f"{draft:.2%}" if draft is not None else "—"
        text.append(f"| {title} | {clean_text} | {draft_text} |")
    text += ["", "## Chi tiết từng ca", "",
             "| Folder | Trạng thái | Scope | Uncertainty | Cây khớp hoàn toàn |",
             "|---|---|---|---:|---|"]
    for row in results:
        text.append(f"| {row['folder']} | {row['status']} | {row.get('scope', '—')} | "
                    f"{len(row.get('uncertainties', []))} | "
                    f"{row.get('agreement', {}).get('tree_exact', '—')} |")
    text += ["", "## Số liệu đầy đủ", "", "```json",
             json.dumps(summary, ensure_ascii=False, indent=2), "```"]
    (output_dir / "report.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, help="Defaults to frozen baseline if available, else latest benchmark")
    parser.add_argument("--references-dir", type=Path, default=DEFAULT_REFERENCES)
    parser.add_argument("--output-dir", type=Path)
    report = run_comparison(**vars(parser.parse_args()))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
