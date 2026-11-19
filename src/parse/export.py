"""Gói M2.5 (Integration & Export): đổi \\cite, chuẩn hóa, băm cây con (C1),
hợp Element giữa các Version, sinh cạnh hierarchy (C2), lưu thứ tự anh em (C3),
ghi log Version (C4) và kiểm tra 9 bất biến liên module I1–I9.

Tài liệu thiết kế & hợp đồng dữ liệu:
- docs/m2-interfaces.md (mục 3 [E], mục 4 I1–I9, mục 5)
- docs/data-contract.md (mục 4: C1–C6)
- Danh sách lệnh định dạng LaTeX cơ bản tham khảo từ LaTeX2e Unofficial Reference
  Manual (https://latexref.xyz/) và gói booktabs (https://ctan.org/pkg/booktabs).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import csv
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

import pyarrow as pa

from src.common.schema import (
    ELEMENT_KINDS,
    from_records,
    publication_key,
    require_id,
    validate as validate_schema_table,
    write_table,
)
from src.parse._fallback import (
    FORMATTING_COMMANDS,
    fallback_normalize as default_normalize,
)
from src.parse.types import (
    LEAF_KINDS,
    LIST_KINDS,
    SECTION_KINDS,
    BibResult,
    BibSource,
    Issue,
    Leaf,
    LeafTree,
    ListNode,
    Section,
    SourceBundle,
    StructureTree,
    compute_element_id,
    source_bundle_from_dict,
    validate_C,
    validate_D,
)

EXPORT_VERSION = "1"

# Danh sách lệnh trích dẫn khớp với src/parse/structure.py (không nhận nhầm \citestyle, \setcitestyle, ...)
_CITE_COMMANDS: tuple[str, ...] = (
    "citeyearpar",
    "citeauthor",
    "citeyear",
    "citealp",
    "citealt",
    "citenum",
    "parencite",
    "textcite",
    "autocite",
    "footcite",
    "fullcite",
    "supercite",
    "citep",
    "citet",
    "cite",
)
_CITE_COMMAND_RE = re.compile(
    r"(\\(?:(?:" + "|".join(_CITE_COMMANDS) + r"))(?![a-zA-Z])\*?(?:\s*\[[^\]]*\])*)\s*\{([^{}]*)\}",
    re.IGNORECASE,
)
_REFERENCES_TITLE_RE = re.compile(
    r"^(?:references|bibliography|works\s+cited|literature\s+cited)\.?$",
    re.IGNORECASE,
)


def rewrite_citations(raw: str, version_key_map: Mapping[str, str] | None) -> str:
    """Đổi citation key trong mọi lệnh \\cite*{...} theo key_map của Version.

    Thực hiện TRƯỚC khi gọi normalize() theo hợp đồng [E] (docs/m2-interfaces.md mục 3).
    """
    if not raw or not version_key_map:
        return raw

    def _replace(match: re.Match[str]) -> str:
        prefix, body = match.group(1), match.group(2)
        parts = body.split(",")
        mapped: list[str] = []
        for part in parts:
            stripped = part.strip()
            if not stripped:
                mapped.append(part)
                continue
            tokens = [version_key_map.get(tok, tok) for tok in stripped.split()]
            new_key = " ".join(tokens)
            if len(parts) == 1:
                mapped.append(new_key)
            else:
                lead = part[: len(part) - len(part.lstrip())]
                trail = part[len(part.rstrip()) :]
                mapped.append(f"{lead}{new_key}{trail}")
        return f"{prefix}{{{','.join(mapped)}}}"

    return _CITE_COMMAND_RE.sub(_replace, raw)


def extract_cite_keys(text: str) -> list[str]:
    """Trích danh sách citation key xuất hiện trong các lệnh \\cite*{...}."""
    if not text:
        return []
    keys: list[str] = []
    for match in _CITE_COMMAND_RE.finditer(text):
        for part in match.group(2).split(","):
            for key in part.strip().split():
                if key:
                    keys.append(key)
    return keys


def get_normalizer(
    normalize_fn: Callable[[str, str], str] | None = None,
    *,
    allow_fallback: bool = True,
) -> Callable[[str, str], str]:
    """Lấy hàm normalize được truyền vào, hoặc từ src.parse.normalize nếu đã có."""
    if normalize_fn is not None:
        return normalize_fn
    try:
        from src.parse.normalize import normalize as team_normalize  # type: ignore[import-not-found]

        return team_normalize
    except ImportError as exc:
        if allow_fallback:
            return default_normalize
        raise ImportError(
            "Thiếu gói thật `src.parse.normalize`. Truyền `allow_fallback=True` "
            "(hoặc `--allow-fallback`) nếu muốn chạy bản thay thế tạm."
        ) from exc


@dataclass
class VersionInput:
    """Đầu vào của một Version cho bước Export [E]."""

    version: int
    status: str  # "ready" | "parsed" | "success" | "empty_non_tex" | "non_tex" | "failed" | "missing"
    leaf_tree: LeafTree | None = None
    source_bundle: SourceBundle | None = None
    structure_tree: StructureTree | None = None
    bib_source: BibSource | None = None
    issues: list[str] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)
    seconds: float | None = None


@dataclass
class ExportResult:
    """Kết quả xuất [E] của một Publication."""

    arxiv_id: str
    elements: list[dict[str, Any]]
    hierarchy: list[dict[str, Any]]
    bibtex: list[dict[str, Any]]
    version_logs: list[dict[str, Any]]
    order: dict[str, dict[str, list[str]]]
    stats: dict[str, int]
    root_by_version: dict[int, str] = field(default_factory=dict)


def _collect_issue_codes(*sources: Any) -> list[str]:
    """Gom mã lỗi từ các điểm giao A/B/C và giữ thứ tự xuất hiện duy nhất."""
    seen: set[str] = set()
    codes: list[str] = []
    for src in sources:
        if src is None:
            continue
        items = getattr(src, "issues", src) if not isinstance(src, list) else src
        for item in items:
            if isinstance(item, Issue):
                code = item.code
            elif isinstance(item, Mapping):
                code = str(item.get("code", ""))
            else:
                code = str(item)
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
    return codes


def export_publication(
    arxiv_id: str,
    versions: Sequence[VersionInput],
    bib_result: BibResult | None = None,
    *,
    total_versions: int | None = None,
    normalize_fn: Callable[[str, str], str] | None = None,
    include_seconds: bool = False,
    validate_output: bool = True,
) -> ExportResult:
    """Chạy 5 bước M2.5 cho một Publication và trả về ExportResult.

    Thứ tự bắt buộc (docs/m2-interfaces.md mục 3 [E]):
    1. Đổi \\cite{k} trong raw theo key_map[version].
    2. Chuẩn hóa từng node bằng normalize().
    3. Băm từ lá lên gốc (C1): element_id = <key>#<kind>-<16 hex sha256>.
    4. Hợp các Element của mọi Version, mỗi element_id giữ một dòng.
    5. Sinh cạnh hierarchy (C2), gộp cạnh trùng dưới cùng cha và đếm vào log.
    """
    require_id(arxiv_id)
    normalizer = get_normalizer(normalize_fn)

    by_ver: dict[int, VersionInput] = {}
    for v_in in versions:
        if type(v_in.version) is not int or v_in.version < 1:
            raise ValueError(f"version không hợp lệ: {v_in.version!r}")
        if v_in.version in by_ver:
            raise ValueError(f"Trùng VersionInput cho version {v_in.version}")
        by_ver[v_in.version] = v_in

    expected_count = total_versions if total_versions is not None else (max(by_ver) if by_ver else 0)
    if expected_count < 1:
        raise ValueError("Publication phải có ít nhất 1 Version")

    key_map_by_ver: dict[str, Mapping[str, str]] = {}
    if bib_result is not None:
        if bib_result.arxiv_id != arxiv_id:
            raise ValueError(f"BibResult.arxiv_id ({bib_result.arxiv_id}) != {arxiv_id}")
        key_map_by_ver = bib_result.key_map or {}

    elements_by_id: dict[str, dict[str, Any]] = {}
    elements_list: list[dict[str, Any]] = []
    hierarchy_list: list[dict[str, Any]] = []
    version_logs: list[dict[str, Any]] = []
    order_map: dict[str, dict[str, list[str]]] = {}
    root_by_version: dict[int, str] = {}

    elements_before_dedup = 0
    total_duplicate_sibling_edges = 0
    counts_by_status: dict[str, int] = defaultdict(int)

    for ver_num in range(1, expected_count + 1):
        v_in = by_ver.get(ver_num)
        if v_in is None or v_in.status == "missing":
            log_status = "missing"
            issues = _collect_issue_codes(v_in.issues if v_in else [])
            counts_by_status["missing"] += 1
            log_row: dict[str, Any] = {
                "arxiv_id": arxiv_id,
                "version": ver_num,
                "status": log_status,
                "issues": issues,
                "elements": 0,
                "edges": 0,
                "duplicate_sibling_edges": 0,
                "no_bibliography": False,
            }
            if include_seconds and v_in is not None and v_in.seconds is not None:
                log_row["seconds"] = round(float(v_in.seconds), 4)
            version_logs.append(log_row)
            continue

        raw_status = v_in.status
        if raw_status in ("empty_non_tex", "non_tex"):
            counts_by_status["empty_non_tex"] += 1
            issues = _collect_issue_codes(v_in.source_bundle, v_in.issues)
            log_row = {
                "arxiv_id": arxiv_id,
                "version": ver_num,
                "status": "empty_non_tex",
                "issues": issues,
                "elements": 0,
                "edges": 0,
                "duplicate_sibling_edges": 0,
                "no_bibliography": False,
            }
            if v_in.fallbacks:
                log_row["fallbacks"] = sorted(set(v_in.fallbacks))
            if include_seconds and v_in.seconds is not None:
                log_row["seconds"] = round(float(v_in.seconds), 4)
            version_logs.append(log_row)
            continue

        if raw_status == "failed" or v_in.leaf_tree is None:
            counts_by_status["failed"] += 1
            issues = _collect_issue_codes(
                v_in.source_bundle, v_in.structure_tree, v_in.leaf_tree, v_in.issues
            )
            log_row = {
                "arxiv_id": arxiv_id,
                "version": ver_num,
                "status": "failed",
                "issues": issues,
                "elements": 0,
                "edges": 0,
                "duplicate_sibling_edges": 0,
                "no_bibliography": False,
            }
            if v_in.fallbacks:
                log_row["fallbacks"] = sorted(set(v_in.fallbacks))
            if include_seconds and v_in.seconds is not None:
                log_row["seconds"] = round(float(v_in.seconds), 4)
            version_logs.append(log_row)
            continue

        if raw_status not in ("ready", "parsed", "success"):
            raise ValueError(f"Trạng thái Version không hợp lệ: {raw_status!r}")

        tree = v_in.leaf_tree
        if tree.arxiv_id != arxiv_id or tree.version != ver_num:
            raise ValueError(
                f"LeafTree ({tree.arxiv_id} v{tree.version}) không khớp ({arxiv_id} v{ver_num})"
            )

        ver_key_map = key_map_by_ver.get(str(ver_num), {})
        ver_element_ids: set[str] = set()
        ver_edges_seen: set[tuple[str, str]] = set()
        ver_edges_list: list[dict[str, Any]] = []
        ver_order: dict[str, list[str]] = {}
        ver_dup_sibling_edges = 0
        ver_nodes_count = 0

        def _visit(node: Section | ListNode | Leaf) -> str:
            nonlocal ver_dup_sibling_edges, ver_nodes_count
            if isinstance(node, Leaf):
                rewritten = rewrite_citations(node.raw, ver_key_map)
                content = normalizer(node.kind, rewritten)
                eid = compute_element_id(arxiv_id, node.kind, content)
                ver_nodes_count += 1
                ver_element_ids.add(eid)
                if eid not in elements_by_id:
                    row = {
                        "element_id": eid,
                        "arxiv_id": arxiv_id,
                        "kind": node.kind,
                        "content": content,
                    }
                    elements_by_id[eid] = row
                    elements_list.append(row)
                return eid

            child_ids = [_visit(child) for child in node.children]
            if isinstance(node, ListNode):
                content = ""
            elif node.kind == "document":
                content = ""
            else:
                rewritten = rewrite_citations(node.title_raw, ver_key_map)
                content = normalizer(node.kind, rewritten)

            eid = compute_element_id(arxiv_id, node.kind, content, child_ids)
            ver_nodes_count += 1
            ver_element_ids.add(eid)

            if child_ids:
                ver_order[eid] = list(child_ids)
                seen_under_this_parent: set[str] = set()
                for cid in child_ids:
                    if cid in seen_under_this_parent:
                        ver_dup_sibling_edges += 1
                        continue
                    seen_under_this_parent.add(cid)
                    edge_key = (cid, eid)
                    if edge_key not in ver_edges_seen:
                        ver_edges_seen.add(edge_key)
                        ver_edges_list.append({
                            "arxiv_id": arxiv_id,
                            "version": ver_num,
                            "element_id": cid,
                            "parent_id": eid,
                        })

            if eid not in elements_by_id:
                row = {
                    "element_id": eid,
                    "arxiv_id": arxiv_id,
                    "kind": node.kind,
                    "content": content,
                }
                elements_by_id[eid] = row
                elements_list.append(row)
            return eid

        root_id = _visit(tree.root)
        root_by_version[ver_num] = root_id
        elements_before_dedup += ver_nodes_count
        total_duplicate_sibling_edges += ver_dup_sibling_edges
        hierarchy_list.extend(ver_edges_list)
        order_map[str(ver_num)] = ver_order

        if v_in.bib_source is not None:
            no_bib = not bool(v_in.bib_source.bib_files) and not bool(v_in.bib_source.bibitems_raw)
        elif bib_result is not None:
            no_bib = len(bib_result.entries) == 0
        else:
            no_bib = True

        issues = _collect_issue_codes(
            v_in.source_bundle, v_in.structure_tree, tree, v_in.issues
        )
        counts_by_status["parsed"] += 1
        log_row = {
            "arxiv_id": arxiv_id,
            "version": ver_num,
            "status": "parsed",
            "issues": issues,
            "elements": len(ver_element_ids),
            "edges": len(ver_edges_list),
            "duplicate_sibling_edges": ver_dup_sibling_edges,
            "no_bibliography": no_bib,
        }
        if v_in.fallbacks:
            log_row["fallbacks"] = sorted(set(v_in.fallbacks))
        if include_seconds and v_in.seconds is not None:
            log_row["seconds"] = round(float(v_in.seconds), 4)
        version_logs.append(log_row)

    bibtex_rows: list[dict[str, Any]] = []
    bib_before = 0
    bib_after = 0
    if bib_result is not None:
        bib_before = int(bib_result.stats.get("entry_before", len(bib_result.entries)))
        bib_after = int(bib_result.stats.get("entry_after", len(bib_result.entries)))
        for entry in bib_result.entries:
            bibtex_rows.append({
                "arxiv_id": arxiv_id,
                "citation_key": entry["citation_key"],
                "entry_type": entry["entry_type"],
                "title": entry.get("title"),
                "authors": list(entry.get("authors") or []),
                "year": entry.get("year"),
                "doi": entry.get("doi"),
                "journal": entry.get("journal"),
                "url": entry.get("url"),
            })

    stats = {
        "versions_total": expected_count,
        "versions_parsed": counts_by_status["parsed"],
        "versions_non_tex": counts_by_status["empty_non_tex"],
        "versions_failed": counts_by_status["failed"],
        "versions_missing": counts_by_status["missing"],
        "elements_before_dedup": elements_before_dedup,
        "elements_after_dedup": len(elements_list),
        "bibtex_before_dedup": bib_before,
        "bibtex_after_dedup": bib_after,
        "duplicate_sibling_edges": total_duplicate_sibling_edges,
    }

    result = ExportResult(
        arxiv_id=arxiv_id,
        elements=elements_list,
        hierarchy=hierarchy_list,
        bibtex=bibtex_rows,
        version_logs=version_logs,
        order=order_map,
        stats=stats,
        root_by_version=root_by_version,
    )
    if validate_output:
        validate_E(result, expected_versions=expected_count, raise_on_error=True)
    return result


def validate_E(
    result: ExportResult,
    *,
    expected_versions: int | None = None,
    raise_on_error: bool = True,
) -> list[str]:
    """Kiểm tra 9 bất biến liên module I1–I9 (docs/m2-interfaces.md mục 4).

    - I1: Mọi element_id, parent_id trong hierarchy có trong elements cùng arxiv_id.
    - I2: Mỗi Version parsed có đúng một root document, không chu trình, mọi node đi tới được root.
    - I3: Không có Element nào có tiêu đề khớp References/Bibliography.
    - I4: kind của cha hợp lệ: lá không làm cha; cha của item luôn là itemize; con của itemize luôn là item.
    - I5: Mọi \\cite{k} trong elements.content có (arxiv_id, k) trong bibtex.
    - I6: Hai Version giống hệt nhau cho cùng một tập cạnh, và không sinh Element mới.
    - I8: Số dòng log = tổng số Version theo metadata; mọi Version non_tex có log empty_non_tex.
    - I9: validate() của schema.py qua cả ba bảng (elements, hierarchy, bibtex).
    """
    errors: list[str] = []
    arxiv_id = result.arxiv_id

    # I9: kiểm tra schema.py trên cả 3 bảng trước tiên
    for table_name, rows in (
        ("elements", result.elements),
        ("hierarchy", result.hierarchy),
        ("bibtex", result.bibtex),
    ):
        try:
            tbl = from_records(rows, table_name)
            schema_errs = validate_schema_table(tbl, table_name)
            errors.extend(f"[I9] {e}" for e in schema_errs)
        except Exception as exc:
            errors.append(f"[I9] Bảng {table_name} không hợp lệ: {exc}")

    elem_map: dict[str, dict[str, Any]] = {}
    prefix = f"{publication_key(arxiv_id)}#"
    for row in result.elements:
        eid = row.get("element_id", "")
        if row.get("arxiv_id") != arxiv_id or not str(eid).startswith(prefix):
            errors.append(f"[I1] Element {eid!r} không khớp arxiv_id {arxiv_id!r}")
        elem_map[eid] = row

    # I1 & I4: kiểm tra khóa ngoại và quan hệ cha-con trên hierarchy
    edges_by_ver: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for edge in result.hierarchy:
        ver = edge["version"]
        cid = edge["element_id"]
        pid = edge["parent_id"]
        if edge.get("arxiv_id") != arxiv_id:
            errors.append(f"[I1] Cạnh ({cid} -> {pid}) khác arxiv_id {arxiv_id}")
        if cid not in elem_map:
            errors.append(f"[I1] element_id {cid!r} ở v{ver} không tồn tại trong elements")
        if pid not in elem_map:
            errors.append(f"[I1] parent_id {pid!r} ở v{ver} không tồn tại trong elements")
        edges_by_ver[ver].append((cid, pid))

        if cid in elem_map and pid in elem_map:
            c_kind = elem_map[cid]["kind"]
            p_kind = elem_map[pid]["kind"]
            if p_kind in LEAF_KINDS:
                errors.append(f"[I4] Lá {pid!r} ({p_kind}) không được làm cha của {cid!r}")
            if c_kind == "document":
                errors.append(f"[I4] Root document {cid!r} không được có cha {pid!r}")
            if c_kind == "item" and p_kind != "itemize":
                errors.append(f"[I4] Cha của item {cid!r} phải là itemize, nhận {p_kind!r}")
            if p_kind == "itemize" and c_kind != "item":
                errors.append(f"[I4] Con của itemize {pid!r} phải là item, nhận {c_kind!r}")
            if c_kind in SECTION_KINDS and p_kind not in SECTION_KINDS:
                errors.append(
                    f"[I4] Cha của Section {cid!r} ({c_kind}) phải là Section/document, nhận {p_kind!r}"
                )

    # I2: Mỗi Version parsed có đúng một root document, không chu trình, mọi node đi tới được root
    for log in result.version_logs:
        if log.get("status") != "parsed":
            continue
        ver = log["version"]
        ver_edges = edges_by_ver.get(ver, [])
        parents_of: dict[str, list[str]] = defaultdict(list)
        nodes_in_ver: set[str] = set()
        for cid, pid in ver_edges:
            parents_of[cid].append(pid)
            nodes_in_ver.add(cid)
            nodes_in_ver.add(pid)
        if not nodes_in_ver and ver in result.root_by_version:
            nodes_in_ver.add(result.root_by_version[ver])

        roots = [
            nid
            for nid in nodes_in_ver
            if not parents_of.get(nid) and nid in elem_map and elem_map[nid]["kind"] == "document"
        ]
        if len(roots) != 1:
            errors.append(
                f"[I2] Version {ver} phải có đúng 1 root document, tìm thấy {len(roots)}: {roots}"
            )
            continue
        root_id = roots[0]

        # Kiểm tra không chu trình và mọi node đều đi tới được root_id
        state: dict[str, int] = {}  # 0/absent: unvisited, 1: visiting, 2: visited
        can_reach_root: dict[str, bool] = {root_id: True}

        def _dfs(nid: str) -> bool:
            st = state.get(nid, 0)
            if st == 1:
                errors.append(f"[I2] Phát hiện chu trình tại {nid!r} ở Version {ver}")
                return False
            if st == 2:
                return can_reach_root.get(nid, False)
            state[nid] = 1
            reaches = nid == root_id
            for nxt in parents_of.get(nid, ()):
                if _dfs(nxt):
                    reaches = True
            state[nid] = 2
            can_reach_root[nid] = reaches
            return reaches

        for nid in sorted(nodes_in_ver):
            if not _dfs(nid):
                errors.append(f"[I2] Node {nid!r} ở Version {ver} không đi tới được root {root_id!r}")

    # I3: Không có Section nào có tiêu đề khớp References/Bibliography
    for row in result.elements:
        if row["kind"] in SECTION_KINDS and row["kind"] != "document":
            if _REFERENCES_TITLE_RE.match(row["content"].strip()):
                errors.append(
                    f"[I3] Section {row['element_id']!r} có tiêu đề References/Bibliography: {row['content']!r}"
                )

    # I5: Mọi \cite{k} trong elements.content có (arxiv_id, k) trong bibtex
    bib_keys = {
        (row["arxiv_id"], row["citation_key"]) for row in result.bibtex
    }
    for row in result.elements:
        for cited in extract_cite_keys(row["content"]):
            if (row["arxiv_id"], cited) not in bib_keys:
                errors.append(
                    f"[I5] Element {row['element_id']!r} trích dẫn {cited!r} không có trong bảng bibtex"
                )

    # I6: Hai Version giống hệt nhau cho cùng một tập cạnh và không sinh Element mới
    seen_roots: dict[str, set[tuple[str, str]]] = {}
    elements_seen_so_far: set[str] = set()
    for log in result.version_logs:
        if log.get("status") != "parsed":
            continue
        ver = log["version"]
        ver_edge_set = {(cid, pid) for cid, pid in edges_by_ver.get(ver, [])}
        ver_nodes = {nid for edge in ver_edge_set for nid in edge}
        root_id = result.root_by_version.get(ver)
        if root_id:
            ver_nodes.add(root_id)
        if root_id and root_id in seen_roots:
            if ver_edge_set != seen_roots[root_id]:
                errors.append(
                    f"[I6] Version {ver} có cùng root {root_id!r} nhưng tập cạnh khác Version trước"
                )
            new_elems = ver_nodes - elements_seen_so_far
            if new_elems:
                errors.append(
                    f"[I6] Version {ver} giống hệt Version trước nhưng sinh thêm Element: {sorted(new_elems)}"
                )
        elif root_id:
            seen_roots[root_id] = ver_edge_set
        elements_seen_so_far.update(ver_nodes)

    # I8: Số dòng log = tổng số Version theo metadata; mọi Version non_tex có log empty_non_tex
    target_versions = expected_versions if expected_versions is not None else result.stats.get("versions_total")
    if target_versions is not None and len(result.version_logs) != target_versions:
        errors.append(
            f"[I8] Số dòng log Version ({len(result.version_logs)}) != số Version theo metadata ({target_versions})"
        )
    logged_vers = [log.get("version") for log in result.version_logs]
    if logged_vers != list(range(1, len(result.version_logs) + 1)):
        errors.append(f"[I8] Thứ tự version trong log không liên tục từ 1: {logged_vers}")
    for log in result.version_logs:
        st = log.get("status")
        if st not in ("parsed", "empty_non_tex", "failed", "missing"):
            errors.append(f"[I8] Trạng thái log không hợp lệ: {st!r}")
        if st == "empty_non_tex" and (log.get("elements") != 0 or log.get("edges") != 0):
            errors.append(f"[I8] Version {log.get('version')} empty_non_tex phải có 0 element và 0 edge")

    if errors and raise_on_error:
        raise ValueError("\n".join(errors))
    return errors


def format_csv_bundle(result: ExportResult) -> dict[str, str]:
    """Định dạng kết quả [E] ra bộ chuỗi CSV/JSONL chuẩn của golden fixture."""
    import io

    def _to_csv(fieldnames: list[str], rows: list[dict[str, Any]]) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            out: dict[str, Any] = {}
            for k in fieldnames:
                val = row.get(k)
                if isinstance(val, list):
                    out[k] = json.dumps(val, ensure_ascii=False)
                elif val is None:
                    out[k] = ""
                else:
                    out[k] = val
            writer.writerow(out)
        return buf.getvalue()

    elements_csv = _to_csv(["element_id", "arxiv_id", "kind", "content"], result.elements)
    hierarchy_csv = _to_csv(["arxiv_id", "version", "element_id", "parent_id"], result.hierarchy)
    bibtex_csv = _to_csv(
        ["arxiv_id", "citation_key", "entry_type", "title", "authors", "year", "doi", "journal", "url"],
        result.bibtex,
    )
    versions_jsonl = "".join(
        json.dumps(log, ensure_ascii=False) + "\n" for log in result.version_logs
    )
    return {
        "elements.csv": elements_csv,
        "hierarchy.csv": hierarchy_csv,
        "bibtex.csv": bibtex_csv,
        "versions.jsonl": versions_jsonl,
    }


def load_golden_case(
    case_dir: str | Path,
) -> tuple[str, int, list[VersionInput], BibResult | None]:
    """Đọc các điểm giao [A], [B], [B'], [C], [D] từ một thư mục golden case."""
    case_path = Path(case_dir)
    d_path = case_path / "D.json"
    bib_result = (
        BibResult.from_dict(json.loads(d_path.read_text(encoding="utf-8")))
        if d_path.exists()
        else None
    )

    a_files = sorted(case_path.glob("A.v*.json"))
    c_files = sorted(case_path.glob("C.v*.json"))
    ver_nums: set[int] = set()
    for p in (*a_files, *c_files):
        m = re.search(r"\.v(\d+)\.json$", p.name)
        if m:
            ver_nums.add(int(m.group(1)))
    if not ver_nums:
        raise ValueError(f"Không tìm thấy file Version trong {case_path}")

    arxiv_id = bib_result.arxiv_id if bib_result is not None else ""
    versions: list[VersionInput] = []
    for ver in sorted(ver_nums):
        a_path = case_path / f"A.v{ver}.json"
        b_path = case_path / f"B.v{ver}.json"
        bp_path = case_path / f"B'.v{ver}.json"
        c_path = case_path / f"C.v{ver}.json"

        sb = (
            source_bundle_from_dict(json.loads(a_path.read_text(encoding="utf-8")))
            if a_path.exists()
            else None
        )
        st = (
            StructureTree.from_dict(json.loads(b_path.read_text(encoding="utf-8")))
            if b_path.exists()
            else None
        )
        bs = (
            BibSource.from_dict(json.loads(bp_path.read_text(encoding="utf-8")))
            if bp_path.exists()
            else None
        )
        lt = (
            LeafTree.from_dict(json.loads(c_path.read_text(encoding="utf-8")))
            if c_path.exists()
            else None
        )
        if not arxiv_id:
            for obj in (lt, st, bs):
                if obj is not None and getattr(obj, "arxiv_id", ""):
                    arxiv_id = obj.arxiv_id
                    break
        status = sb.status if sb is not None else ("ready" if lt is not None else "missing")
        versions.append(
            VersionInput(
                version=ver,
                status=status,
                leaf_tree=lt,
                source_bundle=sb,
                structure_tree=st,
                bib_source=bs,
            )
        )
    if bib_result is not None:
        bib_sources = [v.bib_source for v in versions if v.bib_source is not None]
        validate_D(bib_result, bib_sources=bib_sources or None)
    for v in versions:
        if v.leaf_tree is not None:
            validate_C(v.leaf_tree, structure_tree=v.structure_tree)
    return arxiv_id, max(ver_nums), versions, bib_result


def merge_export_tables(results: Sequence[ExportResult]) -> dict[str, pa.Table]:
    """Hợp kết quả của nhiều Publication thành 3 bảng PyArrow đã qua kiểm tra schema."""
    elements_rows: list[dict[str, Any]] = []
    hierarchy_rows: list[dict[str, Any]] = []
    bibtex_rows: list[dict[str, Any]] = []
    for res in sorted(results, key=lambda r: r.arxiv_id):
        elements_rows.extend(res.elements)
        hierarchy_rows.extend(res.hierarchy)
        bibtex_rows.extend(res.bibtex)
    return {
        "elements": from_records(elements_rows, "elements"),
        "hierarchy": from_records(hierarchy_rows, "hierarchy"),
        "bibtex": from_records(bibtex_rows, "bibtex"),
    }


def write_export_tables(tables: Mapping[str, pa.Table], out_dir: str | Path) -> dict[str, Path]:
    """Ghi 3 bảng elements, hierarchy, bibtex ra file Parquet nguyên tử."""
    base = Path(out_dir)
    base.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name in ("elements", "hierarchy", "bibtex"):
        target = base / f"{name}.parquet"
        write_table(tables[name], name, target)
        written[name] = target
    return written
