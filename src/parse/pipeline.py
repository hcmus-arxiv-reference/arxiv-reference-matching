"""Pipeline tích hợp M2 (docs/m2-cong-viec.md mục 4.4):
Ghép các gói [A] Source -> [B, B'] Structure & BibSource -> [C] Leaves -> [D] BibTeX -> [E] Export,
hỗ trợ checkpoint/resume theo SHA-256 đầu vào và phiên bản các module, ghi log Version (C4),
lưu thứ tự anh em (C3), xuất 3 bảng Parquet và tổng hợp số liệu báo cáo.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Sequence

from src.common.corpus import FileCorpus, file_digest, verified_source
from src.common.json_io import write_json
from src.common.metrics import dir_size_mb, peak_rss_mb
from src.common.schema import publication_key, require_id
from src.parse.export import (
    EXPORT_VERSION,
    ExportResult,
    VersionInput,
    default_normalize,
    export_publication,
     extract_cite_keys,
    get_normalizer,
    merge_export_tables,
    validate_E,
    write_export_tables,
)
from src.parse.source import ASSEMBLER_VERSION, SourceBundle, assemble_source
from src.parse.types import (
    SECTION_DEPTH,
    TYPES_VERSION,
    BibResult,
    BibSource,
    Block,
    Issue,
    Leaf,
    LeafTree,
    ListNode,
    Section,
    StructureTree,
    _is_references_heading,
    validate_A,
    validate_B,
    validate_B_prime,
    validate_C,
    validate_D,
)

PIPELINE_VERSION = "1"
_FALLBACK_STRUCTURE_VERSION = "fallback-3"
_FALLBACK_LEAVES_VERSION = "fallback-3"
_FALLBACK_BIBTEX_VERSION = "fallback-3"
_FALLBACK_NORMALIZE_VERSION = "fallback-1"

_HEADING_CMD_RE = re.compile(
    r"\\(chapter|section|subsection|subsubsection|paragraph)(\*?)\s*(?:\[[^\]]*\])?\s*\{"
)
_BIB_CMD_RE = re.compile(r"\\(?:bibliography|addbibresource)\s*\{([^{}]*)\}")
_BIBITEM_RE = re.compile(
    r"\\bibitem(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}(.*?)(?=\\bibitem|\Z|\\end\{thebibliography\})",
    re.DOTALL,
)
_THEBIB_ENV_RE = re.compile(
    r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}",
    re.DOTALL,
)
_ENV_TOKEN_RE = re.compile(
    r"\\(begin|end)\{(figure\*?|table\*?|itemize|enumerate|description|"
    r"equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?|displaymath)\}"
)
_ABBREVIATIONS: tuple[str, ...] = (
    "i.e.",
    "e.g.",
    "et al.",
    "etc.",
    "Fig.",
    "Figs.",
    "Eq.",
    "Eqs.",
    "Sec.",
    "Secs.",
    "Tab.",
    "Tabs.",
    "vs.",
    "cf.",
    "Dr.",
    "Prof.",
    "Mr.",
    "Mrs.",
    "Ms.",
    "No.",
    "Vol.",
    "pp.",
)


_UNESCAPED_PERCENT_RE = re.compile(r"(?<!\\)(?:\\\\)*%")


def _strip_comments_keep_len(text: str) -> str:
    """Thay nội dung comment %... đến cuối dòng bằng khoảng trắng để giữ nguyên độ dài offset."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        m = _UNESCAPED_PERCENT_RE.search(line)
        if m is None:
            out.append(line)
            continue
        pct_idx = m.end() - 1
        if line.endswith("\r\n"):
            body_end = len(line) - 2
            ending = "\r\n"
        elif line.endswith(("\n", "\r")):
            body_end = len(line) - 1
            ending = line[-1]
        else:
            body_end = len(line)
            ending = ""
        out.append(line[:pct_idx] + (" " * (body_end - pct_idx)) + ending)
    return "".join(out)


def _find_balanced_brace_end(text: str, open_brace_pos: int) -> int | None:
    """Tìm vị trí sau dấu '}' đóng khớp với '{' tại open_brace_pos."""
    depth = 0
    i = open_brace_pos
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _iter_headings(text: str) -> list[tuple[int, int, str, bool, str]]:
    """Tìm các lệnh heading với đối số ngoặc nhọn cân bằng: (start, end, kind, starred, title_raw)."""
    results: list[tuple[int, int, str, bool, str]] = []
    pos = 0
    while True:
        m = _HEADING_CMD_RE.search(text, pos)
        if m is None:
            break
        open_brace = m.end() - 1
        close_end = _find_balanced_brace_end(text, open_brace)
        if close_end is None:
            pos = m.end()
            continue
        kind = m.group(1)
        starred = m.group(2) == "*"
        title_raw = text[open_brace + 1 : close_end - 1].strip()
        results.append((m.start(), close_end, kind, starred, title_raw))
        pos = close_end
    return results


def _iter_top_level_envs(text: str) -> list[tuple[int, int, str]]:
    """Tìm các môi trường khối mức cao nhất (xử lý đúng môi trường lồng nhau cùng tên)."""
    spans: list[tuple[int, int, str]] = []
    stack: list[tuple[str, int]] = []
    for m in _ENV_TOKEN_RE.finditer(text):
        action, env = m.group(1), m.group(2)
        if action == "begin":
            if not stack:
                stack.append((env, m.start()))
            elif stack[0][0] == env:
                stack.append((env, m.start()))
        else:
            if stack and stack[0][0] == env:
                _, start_pos = stack.pop()
                if not stack:
                    spans.append((start_pos, m.end(), env))
    return spans


def _split_blocks(text: str, base_offset: int) -> list[Block]:
    """Tách đoạn thân giữa hai heading thành các Block (text, env, display_math)."""
    blocks: list[Block] = []
    pos = 0
    for start_rel, end_rel, env in _iter_top_level_envs(text):
        before = text[pos:start_rel]
        _add_paragraph_blocks(before, base_offset + pos, blocks)
        raw_env = text[start_rel:end_rel]
        start = base_offset + start_rel
        end = base_offset + end_rel
        if env.startswith(("figure", "table")) or env in ("itemize", "enumerate", "description"):
            blocks.append(Block(type="env", env=env, raw=raw_env, span=(start, end)))
        else:
            blocks.append(Block(type="display_math", env=None, raw=raw_env, span=(start, end)))
        pos = end_rel
    _add_paragraph_blocks(text[pos:], base_offset + pos, blocks)
    return blocks


_PARAGRAPH_SPLIT_RE = re.compile(r"\n[ \t]*\n+")


def _add_paragraph_blocks(segment: str, offset: int, out: list[Block]) -> None:
    pos = 0
    n = len(segment)
    while pos < n:
        m = _PARAGRAPH_SPLIT_RE.search(segment, pos)
        end = m.start() if m else n
        raw_piece = segment[pos:end]
        s_trim = len(raw_piece) - len(raw_piece.lstrip())
        e_trim = len(raw_piece.rstrip())
        if e_trim > s_trim:
            raw = raw_piece[s_trim:e_trim]
            s = offset + pos + s_trim
            e = offset + pos + e_trim
            if raw.startswith("$$") and raw.endswith("$$") and len(raw) > 4:
                out.append(Block(type="display_math", env=None, raw=raw, span=(s, e)))
            elif raw.startswith(r"\[") and raw.endswith(r"\]") and len(raw) > 4:
                out.append(Block(type="display_math", env=None, raw=raw, span=(s, e)))
            else:
                out.append(Block(type="text", env=None, raw=raw, span=(s, e)))
        pos = m.end() if m else n


def _fallback_build_structure(
    bundle: SourceBundle,
    arxiv_id: str,
    version: int,
    version_dir: Path | None = None,
) -> tuple[StructureTree, BibSource]:
    """Bộ dựng StructureTree & BibSource dự phòng khi gói M2.2 chưa merge trên nhánh hiện tại."""
    text = bundle.text
    clean = _strip_comments_keep_len(text)
    bib_files: dict[str, str] = {}
    missing_bib: list[str] = []

    if version_dir is not None and version_dir.is_dir():
        available_bibs = {
            p.relative_to(version_dir).as_posix(): p
            for p in sorted(version_dir.rglob("*"))
            if p.is_file() and p.suffix.lower() == ".bib"
        }
        by_stem = {Path(k).stem: k for k in available_bibs}
        for m in _BIB_CMD_RE.finditer(clean):
            for raw_name in m.group(1).split(","):
                name = raw_name.strip()
                if not name:
                    continue
                candidates = [name, f"{name}.bib"] if not name.lower().endswith(".bib") else [name]
                matched = next((c for c in candidates if c in available_bibs), None)
                if matched is None and Path(name).stem in by_stem:
                    matched = by_stem[Path(name).stem]
                if matched is not None:
                    bib_files[matched] = available_bibs[matched].read_text(
                        encoding="utf-8", errors="replace"
                    )
                elif name not in missing_bib:
                    missing_bib.append(name)

    bibitems_raw = [
        f"\\bibitem{{{m.group(1).strip()}}}{m.group(2).strip()}"
        for m in _BIBITEM_RE.finditer(clean)
    ]
    cite_keys_seen: set[str] = set()
    cite_keys_used: list[str] = []
    for raw_k in extract_cite_keys(clean):
        for k in raw_k.split():
            if k and k not in cite_keys_seen:
                cite_keys_seen.add(k)
                cite_keys_used.append(k)

    begin_match = re.search(r"\\begin\{document\}", clean)
    end_match = re.search(r"\\end\{document\}", clean)
    dropped: list[dict[str, Any]] = []
    if begin_match and end_match and begin_match.end() <= end_match.start():
        if begin_match.start() > 0:
            dropped.append({"reason": "preamble", "span": [0, begin_match.end()]})
        doc_start = begin_match.end()
        doc_end = end_match.start()
    else:
        doc_start = 0
        doc_end = len(clean)

    body = clean[doc_start:doc_end]
    for tb in _THEBIB_ENV_RE.finditer(body):
        dropped.append(
            {"reason": "references", "span": [doc_start + tb.start(), doc_start + tb.end()]}
        )
    dropped.sort(key=lambda d: (d["span"][0], d["span"][1]))
    body_no_thebib = _THEBIB_ENV_RE.sub(lambda m: " " * len(m.group(0)), body)

    headings = _iter_headings(body_no_thebib)
    root = Section(
        kind="document",
        title_raw="",
        starred=False,
        span=(doc_start, doc_end),
        children=[],
    )
    stack: list[Section] = [root]

    if not headings:
        root.children.extend(_split_blocks(body_no_thebib, doc_start))
    else:
        lead = body_no_thebib[: headings[0][0]]
        root.children.extend(_split_blocks(lead, doc_start))
        for idx, (h_start, h_end, h_kind, starred, title_raw) in enumerate(headings):
            sec_start = doc_start + h_start
            next_heading_start = (
                doc_start + headings[idx + 1][0]
                if idx + 1 < len(headings)
                else doc_end
            )
            content_slice = body_no_thebib[h_end : next_heading_start - doc_start]
            if _is_references_heading(title_raw) or not title_raw.strip():
                dropped.append({"reason": "references", "span": [sec_start, next_heading_start]})
                continue
            while len(stack) > 1 and SECTION_DEPTH[stack[-1].kind] >= SECTION_DEPTH[h_kind]:
                finished = stack.pop()
                if stack[-1].span[1] < finished.span[1]:
                    stack[-1].span = (stack[-1].span[0], finished.span[1])
            sec = Section(
                kind=h_kind,
                title_raw=title_raw,
                starred=starred,
                span=(sec_start, next_heading_start),
                children=_split_blocks(content_slice, doc_start + h_end),
            )
            stack[-1].children.append(sec)
            stack.append(sec)
        while len(stack) > 1:
            finished = stack.pop()
            if stack[-1].span[1] < finished.span[1]:
                stack[-1].span = (stack[-1].span[0], finished.span[1])
    dropped.sort(key=lambda d: (d["span"][0], d["span"][1]))

    st_tree = StructureTree(
        arxiv_id=arxiv_id,
        version=version,
        root=root,
        dropped=dropped,
        issues=list(bundle.issues),
        structure_version=_FALLBACK_STRUCTURE_VERSION,
    )
    bib_source = BibSource(
        arxiv_id=arxiv_id,
        version=version,
        bib_files=bib_files,
        missing_bib=missing_bib,
        bibitems_raw=bibitems_raw,
        cite_keys_used=cite_keys_used,
    )
    return st_tree, bib_source


def _split_sentences_with_spans(raw: str, base_span: tuple[int, int]) -> list[Leaf]:
    """Tách câu bảo toàn chữ viết tắt, số thập phân, URL, toán inline và ngoặc lệnh."""
    masked = list(raw)
    n = len(raw)

    # Che toán inline $...$ và \(...\)
    for m in re.finditer(r"\$[^$]+\$|\\\(.*?\\\)", raw, re.DOTALL):
        for i in range(m.start(), m.end()):
            if masked[i] in ".?!":
                masked[i] = "_"

    # Che nội dung trong ngoặc nhọn {...}
    depth = 0
    for i, ch in enumerate(raw):
        if ch == "{" and (i == 0 or raw[i - 1] != "\\"):
            depth += 1
        elif ch == "}" and (i == 0 or raw[i - 1] != "\\"):
            depth = max(0, depth - 1)
        elif depth > 0 and masked[i] in ".?!":
            masked[i] = "_"

    # Che URL và số thập phân
    for m in re.finditer(r"https?://\S+|\d+\.\d+", raw):
        for i in range(m.start(), m.end()):
            if masked[i] in ".?!":
                masked[i] = "_"

    # Che chữ viết tắt
    for abbr in _ABBREVIATIONS:
        for m in re.finditer(re.escape(abbr), raw, re.IGNORECASE):
            for i in range(m.start(), m.end()):
                if masked[i] == ".":
                    masked[i] = "_"

    masked_str = "".join(masked)
    leaves: list[Leaf] = []
    start = 0
    for m in re.finditer(r"[.?!](?=\s|$)", masked_str):
        end = m.end()
        seg = raw[start:end]
        s_trim = len(seg) - len(seg.lstrip())
        e_trim = len(seg.rstrip())
        text_piece = seg[s_trim:e_trim]
        if text_piece:
            leaves.append(
                Leaf(
                    kind="sentence",
                    raw=text_piece,
                    span=(base_span[0] + start + s_trim, base_span[0] + start + e_trim),
                )
            )
        start = end
    tail = raw[start:]
    if tail.strip():
        s_trim = len(tail) - len(tail.lstrip())
        e_trim = len(tail.rstrip())
        leaves.append(
            Leaf(
                kind="sentence",
                raw=tail[s_trim:e_trim],
                span=(base_span[0] + start + s_trim, base_span[0] + start + e_trim),
            )
        )
    if not leaves and raw.strip():
        leaves.append(Leaf(kind="sentence", raw=raw.strip(), span=base_span))
    return leaves


def _parse_list_block(block: Block) -> ListNode:
    """Chuyển Block danh sách (itemize/enumerate/description) thành ListNode itemize -> item."""
    raw = block.raw
    b_start = block.span[0]
    begin_m = re.match(r"^\\begin\{(?:itemize|enumerate|description)\}(?:\s*\[[^\]]*\])?", raw)
    end_m = re.search(r"\\end\{(?:itemize|enumerate|description)\}\s*$", raw)
    inner_start = begin_m.end() if begin_m else 0
    inner_end = end_m.start() if end_m else len(raw)
    if inner_end <= inner_start:
        inner_start, inner_end = 0, len(raw)
    inner = raw[inner_start:inner_end]

    parts = list(re.finditer(r"\\item(?:\s*\[[^\]]*\])?", inner))
    items: list[ListNode | Leaf] = []
    if not parts:
        sents = _split_sentences_with_spans(inner, (b_start + inner_start, b_start + inner_end))
        if not sents:
            sents = [Leaf(kind="sentence", raw="\\item", span=block.span)]
        items.append(
            ListNode(
                kind="item",
                span=(sents[0].span[0], sents[-1].span[1]),
                children=list(sents),
            )
        )
    else:
        for idx, pm in enumerate(parts):
            item_rel_start = inner_start + pm.start()
            body_rel_start = inner_start + pm.end()
            item_rel_end = (
                inner_start + parts[idx + 1].start() if idx + 1 < len(parts) else inner_end
            )
            body = raw[body_rel_start:item_rel_end]
            item_span = (b_start + item_rel_start, b_start + item_rel_end)
            sents = (
                _split_sentences_with_spans(body, (b_start + body_rel_start, b_start + item_rel_end))
                if body.strip()
                else [Leaf(kind="sentence", raw="\\item", span=item_span)]
            )
            items.append(ListNode(kind="item", span=item_span, children=list(sents)))
    return ListNode(kind="itemize", span=block.span, children=items)


def _fallback_build_leaves(tree: StructureTree) -> LeafTree:
    """Bộ dựng LeafTree dự phòng khi gói M2.3 chưa merge trên nhánh hiện tại."""

    def _convert_section(sec: Section) -> Section:
        new_children: list[Section | Block | ListNode | Leaf] = []
        for child in sec.children:
            if isinstance(child, Section):
                new_children.append(_convert_section(child))
            elif isinstance(child, Block):
                if child.type == "env" and (child.env or "").startswith(("figure", "table")):
                    new_children.append(Leaf(kind="figure", raw=child.raw, span=child.span))
                elif child.type == "display_math" or (
                    child.type == "env"
                    and (child.env or "")
                    in (
                        "equation",
                        "equation*",
                        "align",
                        "align*",
                        "gather",
                        "gather*",
                        "multline",
                        "multline*",
                        "eqnarray",
                        "eqnarray*",
                        "displaymath",
                    )
                ):
                    new_children.append(Leaf(kind="formula", raw=child.raw, span=child.span))
                elif child.type == "env" and (child.env or "") in (
                    "itemize",
                    "enumerate",
                    "description",
                ):
                    new_children.append(_parse_list_block(child))
                else:
                    new_children.extend(_split_sentences_with_spans(child.raw, child.span))
            else:
                new_children.append(child)
        return Section(
            kind=sec.kind,
            title_raw=sec.title_raw,
            starred=sec.starred,
            span=sec.span,
            children=new_children,
        )

    return LeafTree(
        arxiv_id=tree.arxiv_id,
        version=tree.version,
        root=_convert_section(tree.root),
        dropped=list(tree.dropped),
        issues=list(tree.issues),
        leaves_version=_FALLBACK_LEAVES_VERSION,
    )


def _fallback_merge_bibtex(arxiv_id: str, sources: Sequence[BibSource]) -> BibResult:
    """Bộ hợp nhất BibTeX dự phòng tuân thủ hợp đồng [D] và C6."""
    entries_by_key: dict[str, dict[str, Any]] = {}
    key_map: dict[str, dict[str, str]] = {}
    raw_years: dict[str, str] = {}
    from_bib = 0
    from_bibitem = 0
    entry_before = 0
    unresolved = 0

    bib_entry_re = re.compile(
        r"@([a-zA-Z]+)\s*\{\s*([^,\s]+)\s*,(.*?)\n\s*\}", re.DOTALL
    )
    field_re = re.compile(
        r"([a-zA-Z_]+)\s*=\s*(?:\{([^{}]*)\}|\"([^\"]*)\"|(\d+))"
    )
    year_re = re.compile(r"\b(19\d{2}|20\d{2})\b")

    # Duyệt theo thứ tự Version tăng dần để Version mới hơn được ưu tiên theo C6
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for src in sorted(sources, key=lambda s: s.version):
        ver = src.version
        for bib_text in src.bib_files.values():
            for m in bib_entry_re.finditer(bib_text):
                etype = m.group(1).lower()
                if etype in ("string", "preamble", "comment"):
                    continue
                ckey = m.group(2).strip()
                body = m.group(3)
                fields: dict[str, str] = {}
                for fm in field_re.finditer(body):
                    fname = fm.group(1).lower()
                    fval = fm.group(2) or fm.group(3) or fm.group(4) or ""
                    fields[fname] = re.sub(r"\s+", " ", fval).strip()
                yr_raw = fields.get("year")
                yr_val: int | None = None
                if yr_raw:
                    ym = year_re.search(yr_raw)
                    if ym:
                        yr_val = int(ym.group(1))
                    else:
                        raw_years[ckey] = yr_raw
                authors_raw = fields.get("author", "")
                authors = [
                    a.strip() for a in re.split(r"\s+and\s+", authors_raw) if a.strip()
                ]
                entry_before += 1
                from_bib += 1
                candidates.append(
                    (
                        ver,
                        ckey,
                        {
                            "citation_key": ckey,
                            "entry_type": etype,
                            "title": fields.get("title"),
                            "authors": authors,
                            "year": yr_val,
                            "doi": fields.get("doi"),
                            "journal": fields.get("journal") or fields.get("booktitle"),
                            "url": fields.get("url"),
                        },
                    )
                )
        for item_text in src.bibitems_raw:
            m = re.match(r"\\bibitem(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}\s*(.*)", item_text, re.DOTALL)
            if not m:
                continue
            ckey = m.group(1).strip()
            rest = re.sub(r"\s+", " ", m.group(2)).strip()
            ym = year_re.search(rest)
            yr_val = int(ym.group(1)) if ym else None
            parts = [p.strip() for p in rest.split(".") if p.strip()]
            authors = [parts[0]] if parts else []
            title = parts[1] if len(parts) > 1 else (rest or None)
            entry_before += 1
            from_bibitem += 1
            candidates.append(
                (
                    ver,
                    ckey,
                    {
                        "citation_key": ckey,
                        "entry_type": "misc",
                        "title": title,
                        "authors": authors,
                        "year": yr_val,
                        "doi": None,
                        "journal": None,
                        "url": None,
                    },
                )
            )

    def _dedup_signature(item: dict[str, Any]) -> str:
        if item.get("doi"):
            return f"doi:{item['doi'].strip().lower()}"
        title_norm = re.sub(r"\W+", "", (item.get("title") or "").lower())
        if title_norm and item.get("year") is not None:
            return f"ty:{title_norm}:{item['year']}"
        return f"key:{item['citation_key']}"

    groups: dict[str, list[tuple[int, str, dict[str, Any]]]] = {}
    for cand in candidates:
        sig = _dedup_signature(cand[2])
        groups.setdefault(sig, []).append(cand)

    key_alias: dict[tuple[int, str], str] = {}
    for sig, group in groups.items():
        max_ver = max(c[0] for c in group)
        chosen_key = min(c[1] for c in group if c[0] == max_ver)
        merged: dict[str, Any] = {
            "citation_key": chosen_key,
            "entry_type": "misc",
            "title": None,
            "authors": [],
            "year": None,
            "doi": None,
            "journal": None,
            "url": None,
        }
        # Ưu tiên giá trị từ Version mới hơn
        for _, _, data in sorted(group, key=lambda x: (x[0], x[1]), reverse=True):
            if data["entry_type"] != "misc" and merged["entry_type"] == "misc":
                merged["entry_type"] = data["entry_type"]
            for field_name in ("title", "year", "doi", "journal", "url"):
                if merged[field_name] is None and data.get(field_name) is not None:
                    merged[field_name] = data[field_name]
            if not merged["authors"] and data.get("authors"):
                merged["authors"] = list(data["authors"])
        entries_by_key[chosen_key] = merged
        for ver, orig_key, _ in group:
            key_alias[(ver, orig_key)] = chosen_key

    for src in sorted(sources, key=lambda s: s.version):
        ver_map: dict[str, str] = {}
        for used in src.cite_keys_used:
            mapped = key_alias.get((src.version, used))
            if mapped is None:
                # Nếu key xuất hiện ở Version khác của cùng Publication
                other = [
                    chosen
                    for (v, k), chosen in key_alias.items()
                    if k == used
                ]
                mapped = other[-1] if other else used
            if mapped not in entries_by_key:
                unresolved += 1
                entry_before += 1
                entries_by_key[mapped] = {
                    "citation_key": mapped,
                    "entry_type": "misc",
                    "title": None,
                    "authors": [],
                    "year": None,
                    "doi": None,
                    "journal": None,
                    "url": None,
                }
            ver_map[used] = mapped
        key_map[str(src.version)] = ver_map

    sorted_entries = [entries_by_key[k] for k in sorted(entries_by_key)]
    return BibResult(
        arxiv_id=arxiv_id,
        entries=sorted_entries,
        key_map=key_map,
        raw_years=raw_years,
        stats={
            "entry_before": entry_before,
            "entry_after": len(sorted_entries),
            "from_bib": from_bib,
            "from_bibitem": from_bibitem,
            "unresolved": unresolved,
        },
        bibtex_version=_FALLBACK_BIBTEX_VERSION,
    )


def get_module_versions() -> dict[str, str]:
    """Lấy phiên bản của mọi module trong pipeline để ghi nhận vào checkpoint done.json."""
    versions = {
        "assembler": ASSEMBLER_VERSION,
        "structure": _FALLBACK_STRUCTURE_VERSION,
        "leaves": _FALLBACK_LEAVES_VERSION,
        "normalize": _FALLBACK_NORMALIZE_VERSION,
        "bibtex": _FALLBACK_BIBTEX_VERSION,
        "types": TYPES_VERSION,
        "export": EXPORT_VERSION,
        "pipeline": PIPELINE_VERSION,
    }
    try:
        from src.parse.structure import STRUCTURE_VERSION  # type: ignore[import-not-found]

        versions["structure"] = str(STRUCTURE_VERSION)
    except ImportError:
        pass
    try:
        from src.parse.leaves import LEAVES_VERSION  # type: ignore[import-not-found]

        versions["leaves"] = str(LEAVES_VERSION)
    except ImportError:
        pass
    try:
        from src.parse.normalize import NORMALIZE_VERSION  # type: ignore[import-not-found]

        versions["normalize"] = str(NORMALIZE_VERSION)
    except ImportError:
        pass
    try:
        from src.parse.bibtex import BIBTEX_VERSION  # type: ignore[import-not-found]

        versions["bibtex"] = str(BIBTEX_VERSION)
    except ImportError:
        pass
    return versions


def compute_publication_input_sha256(corpus: FileCorpus, arxiv_id: str, total_versions: int) -> str:
    """Băm tất định metadata.json và source.json của mọi Version thuộc Publication."""
    meta_path = corpus.metadata_path(arxiv_id)
    meta_hash = file_digest(meta_path) if meta_path.exists() else "missing"
    ver_hashes: list[str] = []
    for ver in range(1, total_versions + 1):
        vdir = corpus.version_path(arxiv_id, ver)
        receipt = vdir / "source.json"
        if receipt.exists():
            ver_hashes.append(f"v{ver}:{file_digest(receipt)}")
        else:
            ver_hashes.append(f"v{ver}:missing")
    payload = json.dumps(
        {"arxiv_id": arxiv_id, "metadata": meta_hash, "versions": ver_hashes},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _save_publication_checkpoint(
    parse_dir: Path,
    result: ExportResult,
    input_sha256: str,
    module_versions: Mapping[str, str],
) -> None:
    """Lưu order.json (C3), export.json (cache trung gian) và done.json (checkpoint)."""
    key = publication_key(result.arxiv_id)
    pub_dir = parse_dir / key
    pub_dir.mkdir(parents=True, exist_ok=True)
    write_json(pub_dir / "order.json", result.order)
    write_json(
        pub_dir / "export.json",
        {
            "arxiv_id": result.arxiv_id,
            "elements": result.elements,
            "hierarchy": result.hierarchy,
            "bibtex": result.bibtex,
            "version_logs": result.version_logs,
            "stats": result.stats,
            "root_by_version": {str(k): v for k, v in result.root_by_version.items()},
        },
    )
    write_json(
        pub_dir / "done.json",
        {
            "format": 1,
            "arxiv_id": result.arxiv_id,
            "input_sha256": input_sha256,
            "module_versions": dict(module_versions),
        },
    )


def _load_publication_checkpoint(
    parse_dir: Path,
    arxiv_id: str,
    input_sha256: str,
    module_versions: Mapping[str, str],
    expected_versions: int,
) -> ExportResult | None:
    """Đọc lại kết quả đã lưu nếu done.json khớp input_sha256 và module_versions."""
    key = publication_key(arxiv_id)
    pub_dir = parse_dir / key
    done_path = pub_dir / "done.json"
    export_path = pub_dir / "export.json"
    order_path = pub_dir / "order.json"
    if not (done_path.is_file() and export_path.is_file() and order_path.is_file()):
        return None
    try:
        done = json.loads(done_path.read_text(encoding="utf-8"))
        if (
            done.get("format") != 1
            or done.get("arxiv_id") != arxiv_id
            or done.get("input_sha256") != input_sha256
            or done.get("module_versions") != dict(module_versions)
        ):
            return None
        cached = json.loads(export_path.read_text(encoding="utf-8"))
        order = json.loads(order_path.read_text(encoding="utf-8"))
        result = ExportResult(
            arxiv_id=cached["arxiv_id"],
            elements=cached["elements"],
            hierarchy=cached["hierarchy"],
            bibtex=cached["bibtex"],
            version_logs=cached["version_logs"],
            order=order,
            stats=cached["stats"],
            root_by_version={
                int(k): v for k, v in cached.get("root_by_version", {}).items()
            },
        )
        validate_E(result, expected_versions=expected_versions, raise_on_error=True)
        return result
    except Exception:
        return None


@dataclass
class PublicationRunOutcome:
    """Kết quả chạy hoặc resume một Publication."""

    result: ExportResult
    resumed: bool
    seconds: float


def parse_publication(
    corpus_dir: str | Path,
    arxiv_id: str,
    *,
    parse_dir: str | Path | None = None,
    resume: bool = True,
    assemble_fn: Callable[[Path], SourceBundle] | None = None,
    structure_fn: Callable[..., tuple[StructureTree, BibSource]] | None = None,
    leaves_fn: Callable[[StructureTree], LeafTree] | None = None,
    bibtex_fn: Callable[[str, list[BibSource]], BibResult] | None = None,
    normalize_fn: Callable[[str, str], str] | None = None,
    module_versions: Mapping[str, str] | None = None,
) -> PublicationRunOutcome:
    """Chạy toàn bộ pipeline M2 cho một Publication (hỗ trợ checkpoint/resume)."""
    t0 = time.perf_counter()
    require_id(arxiv_id)
    corpus = FileCorpus(Path(corpus_dir))
    publication = corpus.read_publication(arxiv_id)
    total_versions = publication.versions

    mod_versions = dict(module_versions or get_module_versions())
    input_sha = compute_publication_input_sha256(corpus, arxiv_id, total_versions)

    if parse_dir is not None and resume:
        cached = _load_publication_checkpoint(
            Path(parse_dir), arxiv_id, input_sha, mod_versions, total_versions
        )
        if cached is not None:
            return PublicationRunOutcome(
                result=cached,
                resumed=True,
                seconds=time.perf_counter() - t0,
            )

    assembler = assemble_fn or assemble_source
    if structure_fn is None:
        try:
            from src.parse.structure import build_structure as structure_fn  # type: ignore[import-not-found]
        except ImportError:
            structure_fn = _fallback_build_structure
    if leaves_fn is None:
        try:
            from src.parse.leaves import build_leaves as leaves_fn  # type: ignore[import-not-found]
        except ImportError:
            leaves_fn = _fallback_build_leaves
    if bibtex_fn is None:
        try:
            from src.parse.bibtex import merge_bibtex as bibtex_fn  # type: ignore[import-not-found]
        except ImportError:
            bibtex_fn = _fallback_merge_bibtex
    normalizer = get_normalizer(normalize_fn)

    version_inputs: list[VersionInput] = []
    bib_sources: list[BibSource] = []

    for ver in range(1, total_versions + 1):
        v_start = time.perf_counter()
        vdir = corpus.version_path(arxiv_id, ver)
        verified = verified_source(vdir)
        if verified is None:
            version_inputs.append(
                VersionInput(
                    version=ver,
                    status="missing",
                    issues=["missing_or_invalid_source"],
                    seconds=time.perf_counter() - v_start,
                )
            )
            continue

        if verified.status == "non_tex":
            sb = assembler(vdir)
            version_inputs.append(
                VersionInput(
                    version=ver,
                    status="empty_non_tex",
                    source_bundle=sb,
                    seconds=time.perf_counter() - v_start,
                )
            )
            continue

        try:
            sb = assembler(vdir)
            if sb.status == "empty_non_tex":
                version_inputs.append(
                    VersionInput(
                        version=ver,
                        status="empty_non_tex",
                        source_bundle=sb,
                        seconds=time.perf_counter() - v_start,
                    )
                )
                continue
            if sb.status != "ready":
                version_inputs.append(
                    VersionInput(
                        version=ver,
                        status="failed",
                        source_bundle=sb,
                        issues=[i.code for i in sb.issues] or ["assemble_failed"],
                        seconds=time.perf_counter() - v_start,
                    )
                )
                continue
            validate_A(sb)
            try:
                st_tree, bib_src = structure_fn(sb, arxiv_id, ver, vdir)
            except TypeError:
                st_tree, bib_src = structure_fn(sb, arxiv_id, ver)
            validate_B(st_tree)
            validate_B_prime(bib_src)
            leaf_tree = leaves_fn(st_tree)
            validate_C(leaf_tree, structure_tree=st_tree)
            bib_sources.append(bib_src)
            version_inputs.append(
                VersionInput(
                    version=ver,
                    status="parsed",
                    leaf_tree=leaf_tree,
                    source_bundle=sb,
                    structure_tree=st_tree,
                    bib_source=bib_src,
                    seconds=time.perf_counter() - v_start,
                )
            )
        except Exception as exc:
            version_inputs.append(
                VersionInput(
                    version=ver,
                    status="failed",
                    issues=[f"parse_error:{type(exc).__name__}"],
                    seconds=time.perf_counter() - v_start,
                )
            )

    if bib_sources:
        try:
            bib_res = bibtex_fn(arxiv_id, bib_sources)
            validate_D(bib_res, bib_sources=bib_sources)
        except Exception:
            bib_res = _fallback_merge_bibtex(arxiv_id, bib_sources)
    else:
        bib_res = BibResult(
            arxiv_id=arxiv_id,
            entries=[],
            key_map={str(v): {} for v in range(1, total_versions + 1)},
            raw_years={},
            stats={
                "entry_before": 0,
                "entry_after": 0,
                "from_bib": 0,
                "from_bibitem": 0,
                "unresolved": 0,
            },
            bibtex_version=mod_versions["bibtex"],
        )

    export_res = export_publication(
        arxiv_id,
        version_inputs,
        bib_res,
        total_versions=total_versions,
        normalize_fn=normalizer,
        include_seconds=False,
        validate_output=True,
    )

    if parse_dir is not None:
        _save_publication_checkpoint(Path(parse_dir), export_res, input_sha, mod_versions)

    return PublicationRunOutcome(
        result=export_res,
        resumed=False,
        seconds=time.perf_counter() - t0,
    )


def run_batch(
    corpus_dir: str | Path,
    out_dir: str | Path,
    *,
    arxiv_ids: Sequence[str] | None = None,
    plan_path: str | Path | None = None,
    metrics_path: str | Path | None = None,
    resume: bool = True,
    assemble_fn: Callable[[Path], SourceBundle] | None = None,
    structure_fn: Callable[..., tuple[StructureTree, BibSource]] | None = None,
    leaves_fn: Callable[[StructureTree], LeafTree] | None = None,
    bibtex_fn: Callable[[str, list[BibSource]], BibResult] | None = None,
    normalize_fn: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """Chạy batch trên danh sách Publication hoặc plan, xuất 3 bảng Parquet, log Version và metrics."""
    start_time = time.perf_counter()
    corpus_path = Path(corpus_dir)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    plan_seed: int | None = None
    if arxiv_ids is not None:
        target_ids = sorted(set(arxiv_ids))
    elif plan_path is not None:
        plan_data = json.loads(Path(plan_path).read_text(encoding="utf-8"))
        plan_seed = plan_data.get("seed")
        target_ids = sorted(p["arxiv_id"] for p in plan_data["publications"])
    else:
        meta_dir = corpus_path / "metadata"
        target_ids = sorted(
            json.loads(p.read_text(encoding="utf-8"))["publication"]["arxiv_id"]
            for p in sorted(meta_dir.glob("*.json"))
        )

    mod_versions = get_module_versions()
    results: list[ExportResult] = []
    resumed_count = 0
    pub_parsed_count = 0
    pub_failed_count = 0

    for aid in target_ids:
        outcome = parse_publication(
            corpus_path,
            aid,
            parse_dir=out_path,
            resume=resume,
            assemble_fn=assemble_fn,
            structure_fn=structure_fn,
            leaves_fn=leaves_fn,
            bibtex_fn=bibtex_fn,
            normalize_fn=normalize_fn,
            module_versions=mod_versions,
        )
        res = outcome.result
        results.append(res)
        if outcome.resumed:
            resumed_count += 1
        if res.stats["versions_failed"] == 0 and res.stats["versions_missing"] == 0:
            pub_parsed_count += 1
        else:
            pub_failed_count += 1

    tables = merge_export_tables(results)
    tables_dir = out_path / "tables"
    write_export_tables(tables, tables_dir)

    log_path = out_path / "log" / "versions.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    all_logs: list[dict[str, Any]] = []
    for res in results:
        all_logs.extend(res.version_logs)
    log_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in all_logs),
        encoding="utf-8",
    )

    status_counts = Counter(row["status"] for row in all_logs)
    v_total = len(all_logs)
    v_parsed = status_counts["parsed"]
    v_non_tex = status_counts["empty_non_tex"]
    v_failed = status_counts["failed"]
    v_missing = status_counts["missing"]
    tex_versions = v_total - v_non_tex

    elem_before = sum(r.stats["elements_before_dedup"] for r in results)
    elem_after = sum(r.stats["elements_after_dedup"] for r in results)
    bib_before = sum(r.stats["bibtex_before_dedup"] for r in results)
    bib_after = sum(r.stats["bibtex_after_dedup"] for r in results)
    dup_edges = sum(r.stats["duplicate_sibling_edges"] for r in results)

    elapsed = time.perf_counter() - start_time
    n_pubs = len(target_ids)
    git_commit: str | None = None
    try:
        import subprocess

        git_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        git_commit = None

    metrics: dict[str, Any] = {
        "module": "export",
        "git_commit": git_commit,
        "seed": plan_seed,
        "module_versions": mod_versions,
        "publications_total": n_pubs,
        "publications_succeeded": pub_parsed_count,
        "publications_failed": pub_failed_count,
        "publications_resumed": resumed_count,
        "publication_parse_rate": round(pub_parsed_count / n_pubs, 6) if n_pubs else 0.0,
        "versions_total_metadata": v_total,
        "versions_parsed": v_parsed,
        "versions_empty_non_tex": v_non_tex,
        "versions_failed": v_failed,
        "versions_missing": v_missing,
        "version_coverage_rate": round((v_parsed + v_non_tex) / v_total, 6) if v_total else 0.0,
        "version_tex_parse_rate": round(v_parsed / tex_versions, 6) if tex_versions else 1.0,
        "elements_before_dedup": elem_before,
        "elements_after_dedup": elem_after,
        "elements_dedup_saved": elem_before - elem_after,
        "elements_dedup_rate": round(1.0 - (elem_after / elem_before), 6) if elem_before else 0.0,
        "bibtex_entries_before_dedup": bib_before,
        "bibtex_entries_after_dedup": bib_after,
        "bibtex_dedup_saved": bib_before - bib_after,
        "bibtex_dedup_rate": round(1.0 - (bib_after / bib_before), 6) if bib_before else 0.0,
        "hierarchy_edges": tables["hierarchy"].num_rows,
        "duplicate_sibling_edges": dup_edges,
        "elapsed_seconds": round(elapsed, 4),
        "avg_seconds_per_publication": round(elapsed / n_pubs, 4) if n_pubs else 0.0,
        "peak_rss_mb": round(peak_rss_mb() or 0.0, 2),
        "output_dir_size_mb": round(dir_size_mb(out_path), 4),
    }
    if metrics_path is not None:
        write_json(Path(metrics_path), metrics)
    write_json(out_path / "metrics.json", metrics)
    return metrics
