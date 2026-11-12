"""Benchmark source gathering → merge → native HierarchyEngine on real Versions.

Main-file accuracy uses existing reviewed labels. Graph validity and absence of
diagnostics are separate checks, not measurements of semantic parsing accuracy.
"""

import argparse
from collections import Counter, deque
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
from time import perf_counter

if __name__ == "__main__" and not __package__:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.common.metrics import dir_size_mb, peak_rss_mb
from src.common.schema import from_records, require_id
from src.parse.Hierarchy.engine import DEFAULT_MAPPING, HierarchyEngine, ParseResult
from src.parse.MultifileGathering.benchmark import DEFAULT_LABELS, DEFAULT_RAW
from src.parse.MultifileGathering.file_tree import build_file_tree
from src.parse.MultifileGathering.merge import merge_latex

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output/benchmark"


def discover_folders(raw_dir: Path) -> list[dict]:
    """One Version per Publication, ranked by TeX count, then BibTeX count.

    Within each Publication choose the richest Version by the same counts;
    prefer the latest Version only when these counts tie.
    """
    if not raw_dir.is_dir():
        raise NotADirectoryError(raw_dir)
    candidates = []
    for publication in sorted(raw_dir.iterdir()):
        if not publication.is_dir():
            continue
        versions = []
        for folder in publication.iterdir():
            if not folder.is_dir() or re.fullmatch(r"v[1-9]\d*", folder.name) is None:
                continue
            counts = Counter(Path(name).suffix.lower()
                             for _, _, names in os.walk(folder) for name in names)
            if counts[".tex"]:
                versions.append({"folder": folder.relative_to(raw_dir).as_posix(),
                                 "tex_count": counts[".tex"], "bib_count": counts[".bib"],
                                 "version": int(folder.name[1:])})
        if versions:
            candidates.append(max(versions, key=lambda row: (
                row["tex_count"], row["bib_count"], row["version"])))
    return sorted(candidates, key=lambda row: (
        -row["tex_count"], -row["bib_count"], row["folder"]))


def check_structure(result: ParseResult, arxiv_id: str, version: int) -> list[str]:
    """Validate table contracts, foreign keys, DAG, reachability and order data.

    A deduplicated Element can legitimately have multiple parents. Repeated
    occurrences remain in ordered_children; hierarchy stores distinct edges.
    """
    errors = []
    for name, rows in (("elements", result.elements), ("hierarchy", result.hierarchy)):
        try:
            from_records([asdict(row) for row in rows], name)
        except (ValueError, TypeError) as error:
            errors.append(f"{name}: {error}")
    nodes = {row.element_id: row for row in result.elements}
    if any(row.arxiv_id != arxiv_id for row in result.elements):
        errors.append("Element metadata does not match the Publication")
    if any(row.arxiv_id != arxiv_id or row.version != version for row in result.hierarchy):
        errors.append("Hierarchy metadata does not match the Publication/Version")
    edges = {(row.parent_id, row.element_id) for row in result.hierarchy}
    if any(parent not in nodes or child not in nodes for parent, child in edges):
        errors.append("Dangling parent_id/element_id")
    ordered_edges = {(parent, child) for parent, children in result.ordered_children.items()
                     for child in children}
    if ordered_edges != edges or any(parent not in nodes for parent in result.ordered_children):
        errors.append("ordered_children does not match hierarchy")
    roots = [row.element_id for row in result.elements if row.kind == "document"]
    if len(roots) != 1:
        errors.append(f"Expected one document root; got {len(roots)}")
    if any(child in roots for _, child in edges):
        errors.append("Document root has a parent")

    children = {node: set() for node in nodes}
    indegree = dict.fromkeys(nodes, 0)
    for parent, child in edges:
        if parent in nodes and child in nodes:
            children[parent].add(child)
            indegree[child] += 1
    pending = deque(node for node, degree in indegree.items() if degree == 0)
    visited = 0
    while pending:
        node = pending.popleft()
        visited += 1
        for child in children[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                pending.append(child)
    if visited != len(nodes):
        errors.append("Cycle in hierarchy")
    reachable = set()
    pending = deque(roots)
    while pending:
        node = pending.popleft()
        if node not in reachable:
            reachable.add(node)
            pending.extend(children[node])
    if reachable != nodes.keys():
        errors.append("Elements unreachable from the document root")
    return errors


def render_tree(result: ParseResult, max_nodes: int = 1000) -> str:
    """Render occurrences in source order; bound the preview, not the JSON data."""
    nodes = {row.element_id: row for row in result.elements}
    roots = [row.element_id for row in result.elements if row.kind == "document"]
    pending = [(node, "", "", frozenset()) for node in reversed(roots)]
    lines = []
    while pending and len(lines) < max_nodes:
        node, prefix, branch, ancestors = pending.pop()
        element = nodes.get(node)
        if element is None:
            lines.append(f"{prefix}{branch}[missing] {node}")
            continue
        content = " ".join(element.content.split())
        excerpt = content[:117] + "..." if len(content) > 120 else content
        lines.append(f"{prefix}{branch}{element.kind}: {excerpt} [{node}]")
        if node in ancestors:
            lines[-1] += " [cycle]"
            continue
        next_prefix = prefix + ("    " if branch == "└── " else "│   ") if branch else ""
        children = result.ordered_children.get(node, [])
        for index in range(len(children) - 1, -1, -1):
            pending.append((children[index], next_prefix,
                            "└── " if index == len(children) - 1 else "├── ", ancestors | {node}))
    if pending:
        lines.append(f"... Preview limited to {max_nodes} occurrences; see full JSON.")
    text = "\n".join(lines) or "[empty tree]"
    # Source text may itself contain Markdown fences.
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", text)), default=0))
    return f"{fence}text\n{text}\n{fence}\n"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize(results: list[dict]) -> dict:
    """All attempted folders remain in the denominator of merge coverage."""
    merged = [row for row in results if row["merged"]]
    parsed = [row for row in results if row["parsed"]]
    labelled = [row for row in results if row["main_correct"] is not None]
    correct = sum(row["main_correct"] for row in labelled)
    valid = sum(row["structure_valid"] is True for row in parsed)
    complete = sum(row["complete"] is True for row in parsed)
    diagnostics = Counter()
    kinds = Counter()
    for row in parsed:
        diagnostics.update(row["diagnostic_counts"])
        kinds.update(row["kind_counts"])
    return {
        "attempted_folders": len(results), "merged_folders": len(merged),
        "merge_success_rate": len(merged) / len(results) if results else None,
        "engine_calls": sum(row["engine_called"] for row in results),
        "parsed_folders": len(parsed),
        "engine_return_rate": len(parsed) / len(merged) if merged else None,
        "complete_folders": complete, "complete_rate": complete / len(parsed) if parsed else None,
        "structurally_valid_folders": valid,
        "structure_valid_rate": valid / len(parsed) if parsed else None,
        "labelled_main_cases": len(labelled), "main_correct": correct,
        "main_accuracy": correct / len(labelled) if labelled else None,
        "main_label_coverage": len(labelled) / len(results) if results else None,
        "semantic_tree_accuracy": None, "semantic_tree_labelled_cases": 0,
        "elements": sum(row["element_count"] for row in parsed),
        "edges": sum(row["edge_count"] for row in parsed),
        "diagnostics": sum(diagnostics.values()), "diagnostic_counts": dict(diagnostics),
        "kind_counts": dict(kinds),
        "stage_seconds": {stage: sum(row["seconds"].get(stage, 0) for row in results)
                          for stage in ("main", "merge", "engine", "export")},
    }


def render_report(report: dict) -> str:
    summary = report["summary"]
    accuracy = summary["main_accuracy"]
    lines = ["# Benchmark Multi-file → Merge → Hierarchy", "",
             f"- Folder đã thử: {summary['attempted_folders']}; merge được: {summary['merged_folders']}.",
             f"- Engine: {summary['engine_calls']} lần gọi; trả kết quả: {summary['parsed_folders']}.",
             f"- Không có diagnostic: {summary['complete_folders']}/{summary['parsed_folders']}.",
             f"- Cấu trúc hợp lệ: {summary['structurally_valid_folders']}/{summary['parsed_folders']}.",
             f"- Chọn main đúng: {summary['main_correct']}/{summary['labelled_main_cases']} "
             + (f"({accuracy:.2%})." if accuracy is not None else "(chưa có nhãn)."),
             f"- Elements: {summary['elements']}; cạnh: {summary['edges']}; diagnostics: {summary['diagnostics']}.",
             f"- Thời gian toàn lượt: {summary['wall_seconds']:.2f}s; "
             f"RAM đỉnh cả tiến trình: {summary['process_peak_rss_mb']} MB.", "",
             "Ưu tiên số file TeX, sau đó BibTeX; mỗi Publication lấy một Version giàu source nhất. "
             "Duyệt tiếp đến khi đủ số lần gọi engine hoặc hết ứng viên. "
             "Các ca merge bị từ chối vẫn nằm trong report.json và bảng dưới.", "",
             "**Chưa đo được độ chính xác nội dung/cây phân cấp:** chưa có cây chuẩn được gán nhãn độc lập. "
             "Tỷ lệ cấu trúc hợp lệ chỉ kiểm tra schema, metadata, khóa, cạnh, chu trình và độ liên thông; "
             "không chứng minh việc tách câu hoặc nhận diện nội dung là đúng. "
             "Độ chính xác chọn main dùng nhãn đã review, xác minh SHA-256; "
             "nhãn thiếu, mơ hồ hoặc đã đổi source không được tính điểm.", "",
             "Cây có diagnostic là kết quả chưa hoàn tất. Markdown giữ thứ tự và phần tử lặp, "
             f"giới hạn {report['config']['preview_nodes']} nút xuất hiện; JSON giữ toàn bộ records, "
             "ordered_children và diagnostic. Offset diagnostic tính bằng byte UTF-8 trong merged.tex.", "",
             "| Folder | TeX/Bib | Trạng thái | Elements / cạnh | Diagnostic | Cây |",
             "|---|---:|---|---:|---:|---|"]
    for row in report["results"]:
        links = (f"[MD]({row['artifacts']['tree_md']}) / [JSON]({row['artifacts']['tree_json']})"
                 if "tree_md" in row["artifacts"] else "—")
        lines.append(f"| {row['folder']} | {row['tex_count']}/{row['bib_count']} | {row['status']} | "
                     f"{row.get('element_count', '—')} / {row.get('edge_count', '—')} | "
                     f"{sum(row.get('diagnostic_counts', {}).values())} | {links} |")
    lines += ["", "## Diagnostic theo loại", "", "```json",
              json.dumps(summary["diagnostic_counts"], ensure_ascii=False, indent=2), "```", "",
              "Xem report.json để đọc thời gian từng bước, lỗi từng ca, đường dẫn nguồn, "
              "nhãn chọn main và các chỉ số với mẫu số đầy đủ.", ""]
    return "\n".join(lines)


def run_benchmark(raw_dir: str | Path = DEFAULT_RAW, *, limit: int = 30,
                  output_dir: str | Path = DEFAULT_OUTPUT,
                  labels_path: str | Path = DEFAULT_LABELS,
                  mapping_path: str | Path = DEFAULT_MAPPING,
                  preview_nodes: int = 1000, progress: bool = False,
                  exclude_report: str | Path | None = None) -> dict:
    """Run sequentially with bounded memory; export each case before continuing."""
    if limit < 1 or preview_nodes < 1:
        raise ValueError("limit and preview_nodes must be positive")
    raw_dir, output_dir = Path(raw_dir).resolve(), Path(output_dir).resolve()
    labels_path, mapping_path = Path(labels_path).resolve(), Path(mapping_path).resolve()
    # Fail before scanning the corpus if the native extension/mapping is unavailable.
    HierarchyEngine("2508.02872", 1, mapping_path)
    started = perf_counter()
    candidates = discover_folders(raw_dir)
    excluded = set()
    if exclude_report is not None:
        exclude_report = Path(exclude_report).resolve()
        previous = json.loads(exclude_report.read_text(encoding="utf-8"))
        excluded = {row["folder"].split("/")[0] for row in previous["results"]}
        candidates = [row for row in candidates if row["folder"].split("/")[0] not in excluded]
    discovery_seconds = perf_counter() - started
    labels = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.is_file() else {}
    results = []
    engine_calls = 0
    for candidate in candidates:
        if engine_calls >= limit:
            break
        folder = raw_dir / candidate["folder"]
        key = candidate["folder"].replace("/", "_")
        case_dir = output_dir / "cases" / key
        row = dict(candidate, main_file=None, expected_main=None, main_correct=None,
                   merged=False, engine_called=False, parsed=False, complete=None,
                   structure_valid=None, status="main_failed", error=None, seconds={}, artifacts={})
        stage = "main"
        tick = perf_counter()
        try:
            label = labels.get(candidate["folder"], {})
            expected = label.get("main_file")
            row["label_note"] = label.get("note", "No reviewed main-file label")
            if expected is not None:
                labelled_file = folder / expected
                if (labelled_file.is_file() and hashlib.sha256(labelled_file.read_bytes()).hexdigest()
                        == label.get("sha256")):
                    row["expected_main"] = expected
                    row["main_correct"] = False
                else:
                    row["label_note"] = "Label checksum missing or changed; excluded from scoring"
            main_tree = build_file_tree(folder, case_dir / "file_tree.json")
            row["main_file"] = main_tree.main_file
            row["input_files"] = list(main_tree.input_files)
            if row["expected_main"] is not None:
                row["main_correct"] = row["expected_main"] == main_tree.main_file
            row["seconds"][stage] = perf_counter() - tick
            stage, tick = "merge", perf_counter()
            latex = merge_latex(folder, main_file=main_tree.main_file)
            row["seconds"][stage] = perf_counter() - tick
            row["merged"] = True
            row["latex_sha256"] = hashlib.sha256(latex.encode("utf-8")).hexdigest()
            row["latex_bytes"] = len(latex.encode("utf-8"))
            (case_dir / "merged.tex").write_text(latex, encoding="utf-8")
            row["artifacts"]["merged_tex"] = (case_dir / "merged.tex").relative_to(output_dir).as_posix()
            stage, tick = "engine", perf_counter()
            publication_key = folder.parent.name
            arxiv_id = require_id(re.sub(r"^(\d{4})-(\d{4,5})$", r"\1.\2", publication_key))
            engine = HierarchyEngine(arxiv_id, candidate["version"], mapping_path)
            row["engine_called"] = True
            engine_calls += 1
            result = engine.parse(latex)
            row["seconds"][stage] = perf_counter() - tick
            row.update(parsed=True, complete=result.complete, element_count=len(result.elements),
                       edge_count=len(result.hierarchy),
                       diagnostic_counts=dict(Counter(item["code"] for item in result.diagnostics)),
                       kind_counts=dict(Counter(item.kind for item in result.elements)))
            stage, tick = "export", perf_counter()
            row["structure_errors"] = check_structure(result, arxiv_id, candidate["version"])
            row["structure_valid"] = not row["structure_errors"]
            row["status"] = ("invalid_structure" if row["structure_errors"] else
                             "complete" if result.complete else "partial")
            for kind, filename in (("tree_json", "tree.json"), ("tree_md", "tree.md")):
                row["artifacts"][kind] = (case_dir / filename).relative_to(output_dir).as_posix()
            write_json(case_dir / "tree.json", {
                "folder": candidate["folder"], "arxiv_id": arxiv_id, "version": candidate["version"],
                "main_file": row["main_file"], "latex_sha256": row["latex_sha256"],
                "complete": result.complete, "structure_errors": row["structure_errors"],
                "roots": [item.element_id for item in result.elements if item.kind == "document"],
                **asdict(result),
            })
            (case_dir / "tree.md").write_text(
                f"# {candidate['folder']}\n\n"
                f"Status: {row['status']}; elements: {len(result.elements)}; "
                f"edges: {len(result.hierarchy)}; diagnostics: {len(result.diagnostics)}.\n\n"
                "[Full JSON](tree.json) · [Merged LaTeX](merged.tex)\n\n"
                + render_tree(result, preview_nodes), encoding="utf-8")
            row["seconds"][stage] = perf_counter() - tick
        except Exception as error:
            # Preserve failed cases and continue; these are part of benchmark coverage.
            row["seconds"][stage] = perf_counter() - tick
            row["status"] = f"{stage}_failed"
            if stage == "merge" and isinstance(error, ValueError) and "Cannot merge LaTeX (needs_review)" in str(error):
                row["status"] = "merge_needs_review"
            row["error"] = f"{type(error).__name__}: {error}"
        write_json(case_dir / "case.json", row)
        results.append(row)
        if progress:
            print(f"[{engine_calls}/{limit}] {candidate['folder']} "
                  f"tex={candidate['tex_count']} {row['status']}", flush=True)
            if row["error"]:
                details = row["error"].splitlines()
                print("  " + (details[1] if len(details) > 1 else details[0]), flush=True)
    summary = summarize(results)
    summary.update(target_engine_calls=limit, target_reached=engine_calls == limit,
                   available_publications=len(candidates), discovery_seconds=discovery_seconds,
                   wall_seconds=perf_counter() - started, process_peak_rss_mb=peak_rss_mb())
    report = {"config": {"raw_dir": str(raw_dir), "output_dir": str(output_dir),
                         "labels_path": str(labels_path), "mapping_path": str(mapping_path),
                         "mapping_sha256": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
                         "exclude_report": str(exclude_report) if exclude_report is not None else None,
                         "excluded_publications": sorted(excluded),
                         "limit": limit, "preview_nodes": preview_nodes},
              "summary": summary, "results": results}
    write_json(output_dir / "report.json", report)
    (output_dir / "report.md").write_text(render_report(report), encoding="utf-8")
    # Snapshot only files referenced by this run; exclude stale cases from earlier runs.
    paths = [output_dir / "report.json", output_dir / "report.md"]
    for row in results:
        paths.extend((output_dir / "cases" / row["folder"].replace("/", "_")).iterdir())
    summary["output_size_mb_snapshot"] = sum(dir_size_mb(path) for path in paths)
    write_json(output_dir / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--limit", type=int, default=30, help="Target number of actual engine calls")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS, dest="labels_path")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING, dest="mapping_path")
    parser.add_argument("--preview-nodes", type=int, default=1000)
    parser.add_argument("--exclude-report", type=Path,
                        help="Exclude every Publication listed in an earlier report, across all Versions")
    args = parser.parse_args()
    report = run_benchmark(**vars(args), progress=True)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {Path(args.output_dir).resolve() / 'report.md'}")


if __name__ == "__main__":
    main()
