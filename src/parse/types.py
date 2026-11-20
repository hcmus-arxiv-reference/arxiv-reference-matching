"""Shared intermediate types and boundary validators for Milestone 2 (Parsing).

Defines the data structures and invariant checks for each module boundary:
- [A] SourceBundle (M2.1 -> M2.2, defined in src.parse.source)
- [B] StructureTree (M2.2 -> M2.3)
- [B'] BibSource (M2.2 -> M2.4b)
- [C] LeafTree (M2.3 -> M2.5)
- [D] BibResult (M2.4b -> M2.5)

Source:
- https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/
- docs/m2-interfaces.md
- docs/data-contract.md
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Any, Sequence

from src.common.schema import from_records, make_element_id, require_id
from src.parse.source import Issue, SourceBundle, Span

TYPES_VERSION = "1"

SECTION_KINDS: tuple[str, ...] = (
    "document",
    "chapter",
    "section",
    "subsection",
    "subsubsection",
    "paragraph",
)
SECTION_DEPTH: dict[str, int] = {kind: idx for idx, kind in enumerate(SECTION_KINDS)}

BLOCK_TYPES: tuple[str, ...] = ("text", "env", "display_math")
LEAF_KINDS: tuple[str, ...] = ("sentence", "formula", "figure")
LIST_KINDS: tuple[str, ...] = ("itemize", "item")

_SOURCE_STATUSES = {"ready", "needs_review", "error", "empty_non_tex"}
_ISSUE_SEVERITIES = {"warning", "error"}
_REFERENCES_TITLES = {
    "references",
    "reference",
    "bibliography",
    "works cited",
    "literature cited",
}
_LATEX_CMD_CLEAN_RE = re.compile(r"\\[a-zA-Z@]+\*?|\{|\}")
_UNESCAPED_COMMENT_RE = re.compile(r"(?<!\\)(?:\\\\)*%")


# --------------------------------------------------------------------------
# Dataclasses for boundaries [B], [B'], [C], [D]
# --------------------------------------------------------------------------


@dataclass
class Block:
    """Unparsed content block between structural headings in [B]."""

    type: str  # text | env | display_math
    env: str | None  # environment name if type == "env", else None
    raw: str  # exact slice of SourceBundle.text[span] with comments blanked
    span: tuple[int, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": "Block",
            "type": self.type,
            "env": self.env,
            "raw": self.raw,
            "span": list(self.span),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Block:
        return cls(
            type=data["type"],
            env=data.get("env"),
            raw=data["raw"],
            span=(int(data["span"][0]), int(data["span"][1])),
        )


@dataclass
class Leaf:
    """Leaf element in [C] LeafTree."""

    kind: str  # sentence | formula | figure
    raw: str  # unnormalized LaTeX, \cite keys still original
    span: tuple[int, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": "Leaf",
            "kind": self.kind,
            "raw": self.raw,
            "span": list(self.span),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Leaf:
        return cls(
            kind=data["kind"],
            raw=data["raw"],
            span=(int(data["span"][0]), int(data["span"][1])),
        )


@dataclass
class ListNode:
    """List container (`itemize`) or list entry (`item`) in [C] LeafTree."""

    kind: str  # itemize | item
    span: tuple[int, int]
    children: list[ListNode | Leaf] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": "ListNode",
            "kind": self.kind,
            "span": list(self.span),
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ListNode:
        return cls(
            kind=data["kind"],
            span=(int(data["span"][0]), int(data["span"][1])),
            children=[_node_from_dict(c) for c in data.get("children", [])],
        )


@dataclass
class Section:
    """Structural heading node used in both [B] StructureTree and [C] LeafTree."""

    kind: str  # document | chapter | section | subsection | subsubsection | paragraph
    title_raw: str  # unnormalized heading title ("" for document)
    starred: bool
    span: tuple[int, int]
    children: list[Section | Block | ListNode | Leaf] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": "Section",
            "kind": self.kind,
            "title_raw": self.title_raw,
            "starred": self.starred,
            "span": list(self.span),
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Section:
        return cls(
            kind=data["kind"],
            title_raw=data["title_raw"],
            starred=bool(data["starred"]),
            span=(int(data["span"][0]), int(data["span"][1])),
            children=[_node_from_dict(c) for c in data.get("children", [])],
        )


def _node_from_dict(data: dict[str, Any]) -> Section | Block | ListNode | Leaf:
    node_type = data.get("node")
    if node_type == "Section" or ("title_raw" in data and "starred" in data):
        return Section.from_dict(data)
    if node_type == "Block" or "type" in data:
        return Block.from_dict(data)
    if node_type == "ListNode" or data.get("kind") in LIST_KINDS:
        return ListNode.from_dict(data)
    if node_type == "Leaf" or data.get("kind") in LEAF_KINDS:
        return Leaf.from_dict(data)
    raise ValueError(f"Cannot deserialize unknown tree node: {data!r}")


@dataclass
class StructureTree:
    """[B] Output of M2.2 Structure and input to M2.3 Leaves."""

    arxiv_id: str
    version: int
    root: Section
    dropped: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    structure_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "arxiv_id": self.arxiv_id,
            "version": self.version,
            "root": self.root.to_dict(),
            "dropped": self.dropped,
            "issues": self.issues,
            "structure_version": self.structure_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StructureTree:
        return cls(
            arxiv_id=data["arxiv_id"],
            version=int(data["version"]),
            root=Section.from_dict(data["root"]),
            dropped=list(data.get("dropped", [])),
            issues=list(data.get("issues", [])),
            structure_version=str(data.get("structure_version", "1")),
        )


@dataclass
class BibSource:
    """[B'] Bibliography and citation raw data extracted by M2.2 for M2.4b."""

    arxiv_id: str
    version: int
    bib_files: dict[str, str] = field(default_factory=dict)
    missing_bib: list[str] = field(default_factory=list)
    bibitems_raw: list[str] = field(default_factory=list)
    cite_keys_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BibSource:
        return cls(
            arxiv_id=data["arxiv_id"],
            version=int(data["version"]),
            bib_files=dict(data.get("bib_files", {})),
            missing_bib=list(data.get("missing_bib", [])),
            bibitems_raw=list(data.get("bibitems_raw", [])),
            cite_keys_used=list(data.get("cite_keys_used", [])),
        )


@dataclass
class LeafTree:
    """[C] Output of M2.3 Leaves and input to M2.5 Export."""

    arxiv_id: str
    version: int
    root: Section
    dropped: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    leaves_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "arxiv_id": self.arxiv_id,
            "version": self.version,
            "root": self.root.to_dict(),
            "dropped": self.dropped,
            "issues": self.issues,
            "leaves_version": self.leaves_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LeafTree:
        return cls(
            arxiv_id=data["arxiv_id"],
            version=int(data["version"]),
            root=Section.from_dict(data["root"]),
            dropped=list(data.get("dropped", [])),
            issues=list(data.get("issues", [])),
            leaves_version=str(data.get("leaves_version", "1")),
        )


@dataclass
class BibResult:
    """[D] Deduplicated BibTeX entries and citation key map from M2.4b."""

    arxiv_id: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    key_map: dict[str, dict[str, str]] = field(default_factory=dict)
    raw_years: dict[str, str] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    bibtex_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BibResult:
        return cls(
            arxiv_id=data["arxiv_id"],
            entries=list(data.get("entries", [])),
            key_map={str(k): dict(v) for k, v in data.get("key_map", {}).items()},
            raw_years=dict(data.get("raw_years", {})),
            stats=dict(data.get("stats", {})),
            bibtex_version=str(data.get("bibtex_version", "1")),
        )


def source_bundle_from_dict(data: dict[str, Any]) -> SourceBundle:
    """Deserialize [A] SourceBundle from a golden JSON dictionary."""
    return SourceBundle(
        status=data["status"],
        root=data.get("root"),
        text=data.get("text", ""),
        files=list(data.get("files", [])),
        unused_tex_files=list(data.get("unused_tex_files", [])),
        spans=[Span(**s) for s in data.get("spans", [])],
        issues=[Issue(**i) for i in data.get("issues", [])],
        includes=list(data.get("includes", [])),
        checksums=dict(data.get("checksums", {})),
        assembler_version=str(data.get("assembler_version", "1")),
    )


# --------------------------------------------------------------------------
# Internal validation helpers
# --------------------------------------------------------------------------


def _finish(errors: list[str], raise_on_error: bool) -> list[str]:
    if errors and raise_on_error:
        raise ValueError("\n".join(errors))
    return errors


def _check_id_and_version(arxiv_id: Any, version: Any, prefix: str, errors: list[str]) -> None:
    try:
        require_id(arxiv_id)
    except ValueError as exc:
        errors.append(f"[{prefix}] {exc}")
    if type(version) is not int or version < 1:
        errors.append(f"[{prefix}] version phải là số nguyên >= 1, nhận {version!r}")


def _check_span(
    span: Any,
    prefix: str,
    errors: list[str],
    *,
    allow_empty: bool = False,
    max_len: int | None = None,
) -> bool:
    if (
        not isinstance(span, (tuple, list))
        or len(span) != 2
        or type(span[0]) is not int
        or type(span[1]) is not int
    ):
        errors.append(f"[{prefix}] span phải là cặp số nguyên (start, end), nhận {span!r}")
        return False
    start, end = span
    if start < 0 or (end < start if allow_empty else end <= start):
        errors.append(f"[{prefix}] span không hợp lệ: ({start}, {end})")
        return False
    if max_len is not None and end > max_len:
        errors.append(f"[{prefix}] span ({start}, {end}) vượt quá độ dài văn bản {max_len}")
        return False
    return True


def _normalized_heading_title(raw_title: str) -> str:
    cleaned = _LATEX_CMD_CLEAN_RE.sub(" ", raw_title)
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", cleaned)
    return " ".join(cleaned.lower().split())


def _is_references_heading(raw_title: str) -> bool:
    return _normalized_heading_title(raw_title) in _REFERENCES_TITLES


def _has_unescaped_comment(text: str) -> bool:
    return bool(_UNESCAPED_COMMENT_RE.search(text))


def _check_dropped(dropped: Any, prefix: str, max_len: int | None, errors: list[str]) -> None:
    if not isinstance(dropped, list):
        errors.append(f"[{prefix}] dropped phải là list")
        return
    for idx, item in enumerate(dropped):
        if not isinstance(item, dict):
            errors.append(f"[{prefix}] dropped[{idx}] phải là dict")
            continue
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"[{prefix}] dropped[{idx}] thiếu reason hợp lệ")
        if "span" in item:
            _check_span(
                tuple(item["span"]) if isinstance(item["span"], list) else item["span"],
                f"{prefix}.dropped[{idx}]",
                errors,
                allow_empty=True,
                max_len=max_len,
            )


# --------------------------------------------------------------------------
# Boundary Validators: validate_A, validate_B, validate_B_prime, validate_C, validate_D
# --------------------------------------------------------------------------


def validate_A(bundle: SourceBundle, *, raise_on_error: bool = True) -> list[str]:
    """Kiểm tra bất biến điểm giao [A] SourceBundle (M2.1 -> M2.2)."""
    errors: list[str] = []
    if not isinstance(bundle, SourceBundle):
        return _finish(["[A] bundle phải là SourceBundle"], raise_on_error)

    if bundle.status not in _SOURCE_STATUSES:
        errors.append(f"[A] status không hợp lệ: {bundle.status!r}")
    if not isinstance(bundle.assembler_version, str) or not bundle.assembler_version.strip():
        errors.append("[A] assembler_version phải là chuỗi khác rỗng")
    if not isinstance(bundle.text, str):
        errors.append("[A] text phải là chuỗi")
        return _finish(errors, raise_on_error)

    if not isinstance(bundle.files, list) or not all(isinstance(f, str) and f for f in bundle.files):
        errors.append("[A] files phải là danh sách tên file khác rỗng")
    if not isinstance(bundle.unused_tex_files, list) or not all(
        isinstance(f, str) and f for f in bundle.unused_tex_files
    ):
        errors.append("[A] unused_tex_files phải là danh sách tên file khác rỗng")
    if isinstance(bundle.files, list) and isinstance(bundle.unused_tex_files, list):
        overlap = set(bundle.files) & set(bundle.unused_tex_files)
        if overlap:
            errors.append(f"[A] files và unused_tex_files giao nhau: {sorted(overlap)}")

    for idx, issue in enumerate(bundle.issues):
        if not isinstance(issue, Issue):
            errors.append(f"[A] issues[{idx}] phải là Issue")
            continue
        if issue.severity not in _ISSUE_SEVERITIES:
            errors.append(f"[A] issues[{idx}].severity không hợp lệ: {issue.severity!r}")
        if not issue.code or not isinstance(issue.code, str):
            errors.append(f"[A] issues[{idx}].code phải là chuỗi khác rỗng")
        if type(issue.line) is not int or issue.line < 1:
            errors.append(f"[A] issues[{idx}].line phải >= 1")

    if bundle.status == "empty_non_tex":
        if bundle.text != "":
            errors.append("[A] status='empty_non_tex' nhưng text khác rỗng")
        if bundle.root is not None:
            errors.append("[A] status='empty_non_tex' nhưng root không phải None")
        if bundle.files:
            errors.append("[A] status='empty_non_tex' nhưng files không rỗng")
        if bundle.spans:
            errors.append("[A] status='empty_non_tex' nhưng spans không rỗng")
    elif bundle.status == "error":
        if not any(isinstance(i, Issue) and i.severity == "error" for i in bundle.issues):
            errors.append("[A] status='error' nhưng không có Issue nào mang severity='error'")
    elif bundle.status in {"ready", "needs_review"}:
        if not isinstance(bundle.root, str) or not bundle.root:
            errors.append(f"[A] status={bundle.status!r} nhưng thiếu root")
        elif bundle.root not in bundle.files:
            errors.append(f"[A] root {bundle.root!r} không nằm trong files")
        for f in bundle.files:
            if f not in bundle.checksums:
                errors.append(f"[A] file {f!r} thiếu checksum trong checksums")

        if bundle.text:
            if not bundle.spans:
                errors.append("[A] text khác rỗng nhưng spans rỗng")
            else:
                if bundle.spans[0].output_start != 0:
                    errors.append(
                        f"[A] span đầu tiên phải bắt đầu tại 0, nhận {bundle.spans[0].output_start}"
                    )
                if bundle.spans[-1].output_end != len(bundle.text):
                    errors.append(
                        f"[A] span cuối phải kết thúc tại len(text)={len(bundle.text)}, "
                        f"nhận {bundle.spans[-1].output_end}"
                    )
                prev_end = 0
                for idx, span in enumerate(bundle.spans):
                    if not isinstance(span, Span):
                        errors.append(f"[A] spans[{idx}] phải là Span")
                        continue
                    if span.output_start != prev_end:
                        errors.append(
                            f"[A] spans[{idx}] không liên tục: output_start={span.output_start} != {prev_end}"
                        )
                    if span.output_end <= span.output_start:
                        errors.append(f"[A] spans[{idx}] có output range rỗng hoặc âm")
                    if span.source_end <= span.source_start or span.source_start < 0:
                        errors.append(f"[A] spans[{idx}] có source range không hợp lệ")
                    if (span.output_end - span.output_start) != (span.source_end - span.source_start):
                        errors.append(f"[A] spans[{idx}] độ dài output và source lệch nhau")
                    if span.file not in bundle.files:
                        errors.append(f"[A] spans[{idx}].file {span.file!r} không thuộc files")
                    if type(span.line) is not int or span.line < 1:
                        errors.append(f"[A] spans[{idx}].line phải >= 1")
                    prev_end = span.output_end

    return _finish(errors, raise_on_error)


def validate_B(
    tree: StructureTree,
    source_text: str | None = None,
    *,
    raise_on_error: bool = True,
) -> list[str]:
    """Kiểm tra bất biến điểm giao [B] StructureTree (M2.2 -> M2.3)."""
    errors: list[str] = []
    if not isinstance(tree, StructureTree):
        return _finish(["[B] tree phải là StructureTree"], raise_on_error)

    _check_id_and_version(tree.arxiv_id, tree.version, "B", errors)
    if not isinstance(tree.structure_version, str) or not tree.structure_version.strip():
        errors.append("[B] structure_version phải là chuỗi khác rỗng")

    max_len = len(source_text) if source_text is not None else None
    _check_dropped(tree.dropped, "B", max_len, errors)

    if not isinstance(tree.root, Section):
        errors.append("[B] root phải là Section")
        return _finish(errors, raise_on_error)
    if tree.root.kind != "document":
        errors.append(f"[B] root.kind phải là 'document', nhận {tree.root.kind!r}")
    if tree.root.title_raw != "":
        errors.append(f"[B] root.title_raw phải là '', nhận {tree.root.title_raw!r}")
    if tree.root.starred is not False:
        errors.append("[B] root.starred phải là False")

    def walk_section(sec: Section, path: str, is_root: bool) -> None:
        if sec.kind not in SECTION_DEPTH:
            errors.append(f"[{path}] Section.kind không hợp lệ: {sec.kind!r}")
            return
        if not isinstance(sec.title_raw, str):
            errors.append(f"[{path}] title_raw phải là chuỗi")
        elif not is_root:
            if _is_references_heading(sec.title_raw):
                errors.append(
                    f"[{path}] Section References/Bibliography không được nằm trong cây: {sec.title_raw!r}"
                )
            if _has_unescaped_comment(sec.title_raw):
                errors.append(f"[{path}] title_raw còn chứa comment LaTeX chưa xóa")

        if type(sec.starred) is not bool:
            errors.append(f"[{path}] starred phải là bool")

        span_ok = _check_span(
            sec.span,
            path,
            errors,
            allow_empty=is_root,
            max_len=max_len,
        )

        if not isinstance(sec.children, list):
            errors.append(f"[{path}] children phải là list")
            return

        prev_end = sec.span[0] if span_ok else 0
        parent_depth = SECTION_DEPTH[sec.kind]

        for idx, child in enumerate(sec.children):
            cpath = f"{path}.children[{idx}]"
            if isinstance(child, Section):
                if child.kind not in SECTION_DEPTH:
                    errors.append(f"[{cpath}] Section.kind không hợp lệ: {child.kind!r}")
                else:
                    child_depth = SECTION_DEPTH[child.kind]
                    if child_depth <= parent_depth:
                        errors.append(
                            f"[{cpath}] Cấp mục con ({child.kind}) phải sâu hơn cấp cha ({sec.kind})"
                        )
                if _check_span(child.span, cpath, errors, allow_empty=False, max_len=max_len) and span_ok:
                    if child.span[0] < prev_end:
                        errors.append(
                            f"[{cpath}] span {child.span} chồng lấn hoặc ngược thứ tự đọc (trước đó kết thúc ở {prev_end})"
                        )
                    if child.span[0] < sec.span[0] or child.span[1] > sec.span[1]:
                        errors.append(
                            f"[{cpath}] span {child.span} nằm ngoài span của cha {sec.span}"
                        )
                    prev_end = max(prev_end, child.span[1])
                walk_section(child, cpath, is_root=False)
            elif isinstance(child, Block):
                if child.type not in BLOCK_TYPES:
                    errors.append(f"[{cpath}] Block.type không hợp lệ: {child.type!r}")
                if child.type == "env":
                    if not isinstance(child.env, str) or not child.env.strip():
                        errors.append(f"[{cpath}] Block.type='env' phải có tên env khác rỗng")
                    elif child.env.strip() == "thebibliography":
                        errors.append(
                            f"[{cpath}] Môi trường thebibliography phải chuyển sang [B'] và dropped, không nằm trong cây"
                        )
                else:
                    if child.env is not None:
                        errors.append(
                            f"[{cpath}] Block.type={child.type!r} nhưng env={child.env!r} khác None"
                        )
                if not isinstance(child.raw, str) or not child.raw:
                    errors.append(f"[{cpath}] Block.raw phải là chuỗi khác rỗng")
                else:
                    if "\\begin{thebibliography}" in child.raw:
                        errors.append(f"[{cpath}] Block.raw chứa \\begin{{thebibliography}}")
                    if child.env not in {"verbatim", "verbatim*", "Verbatim", "lstlisting", "minted"}:
                        if _has_unescaped_comment(child.raw):
                            errors.append(f"[{cpath}] Block.raw còn chứa comment LaTeX chưa thay bằng khoảng trắng")
                if _check_span(child.span, cpath, errors, allow_empty=False, max_len=max_len):
                    if isinstance(child.raw, str) and len(child.raw) != (child.span[1] - child.span[0]):
                        errors.append(
                            f"[{cpath}] len(Block.raw)={len(child.raw)} khác độ dài span "
                            f"{child.span[1] - child.span[0]}"
                        )
                    if span_ok:
                        if child.span[0] < prev_end:
                            errors.append(
                                f"[{cpath}] span {child.span} chồng lấn hoặc ngược thứ tự đọc (trước đó kết thúc ở {prev_end})"
                            )
                        if child.span[0] < sec.span[0] or child.span[1] > sec.span[1]:
                            errors.append(
                                f"[{cpath}] span {child.span} nằm ngoài span của cha {sec.span}"
                            )
                        prev_end = max(prev_end, child.span[1])
            else:
                errors.append(
                    f"[{cpath}] StructureTree chỉ chứa Section hoặc Block, nhận {type(child).__name__}"
                )

    walk_section(tree.root, "B.root", is_root=True)
    return _finish(errors, raise_on_error)


def validate_B_prime(
    bib: BibSource,
    allowed_bib_files: set[str] | None = None,
    *,
    raise_on_error: bool = True,
) -> list[str]:
    """Kiểm tra bất biến điểm giao [B'] BibSource (M2.2 -> M2.4b)."""
    errors: list[str] = []
    if not isinstance(bib, BibSource):
        return _finish(["[B'] bib phải là BibSource"], raise_on_error)

    _check_id_and_version(bib.arxiv_id, bib.version, "B'", errors)

    if not isinstance(bib.bib_files, dict):
        errors.append("[B'] bib_files phải là dict[str, str]")
    else:
        for name, content in bib.bib_files.items():
            if not isinstance(name, str) or not name.strip():
                errors.append(f"[B'] tên file trong bib_files không hợp lệ: {name!r}")
            if not isinstance(content, str):
                errors.append(f"[B'] nội dung bib_files[{name!r}] phải là chuỗi")
            if allowed_bib_files is not None and name not in allowed_bib_files:
                errors.append(f"[B'] bib_files[{name!r}] không nằm trong receipt của Version")

    if not isinstance(bib.missing_bib, list) or not all(
        isinstance(x, str) and x.strip() for x in bib.missing_bib
    ):
        errors.append("[B'] missing_bib phải là list[str] gồm các tên khác rỗng")
    elif isinstance(bib.bib_files, dict):
        overlap = set(bib.bib_files) & set(bib.missing_bib)
        if overlap:
            errors.append(f"[B'] bib_files và missing_bib giao nhau: {sorted(overlap)}")

    if not isinstance(bib.bibitems_raw, list) or not all(
        isinstance(item, str) and item.strip() for item in bib.bibitems_raw
    ):
        errors.append("[B'] bibitems_raw phải là list[str] gồm các mục \\bibitem khác rỗng")

    if not isinstance(bib.cite_keys_used, list):
        errors.append("[B'] cite_keys_used phải là list[str]")
    else:
        for idx, key in enumerate(bib.cite_keys_used):
            if not isinstance(key, str) or not key.strip():
                errors.append(f"[B'] cite_keys_used[{idx}] phải là chuỗi khác rỗng")
                continue
            if "," in key or any(ch.isspace() for ch in key):
                errors.append(
                    f"[B'] cite_keys_used[{idx}]={key!r} chưa tách danh sách nhiều key hoặc còn khoảng trắng"
                )

    return _finish(errors, raise_on_error)


validate_Bp = validate_B_prime


def validate_C(
    tree: LeafTree,
    structure_tree: StructureTree | None = None,
    *,
    raise_on_error: bool = True,
) -> list[str]:
    """Kiểm tra bất biến điểm giao [C] LeafTree (M2.3 -> M2.5)."""
    errors: list[str] = []
    if not isinstance(tree, LeafTree):
        return _finish(["[C] tree phải là LeafTree"], raise_on_error)

    _check_id_and_version(tree.arxiv_id, tree.version, "C", errors)
    if not isinstance(tree.leaves_version, str) or not tree.leaves_version.strip():
        errors.append("[C] leaves_version phải là chuỗi khác rỗng")

    _check_dropped(tree.dropped, "C", None, errors)

    if not isinstance(tree.root, Section):
        errors.append("[C] root phải là Section")
        return _finish(errors, raise_on_error)
    if tree.root.kind != "document":
        errors.append(f"[C] root.kind phải là 'document', nhận {tree.root.kind!r}")
    if tree.root.title_raw != "":
        errors.append(f"[C] root.title_raw phải là '', nhận {tree.root.title_raw!r}")
    if tree.root.starred is not False:
        errors.append("[C] root.starred phải là False")

    def walk_leaf(node: Leaf, path: str) -> None:
        if node.kind not in LEAF_KINDS:
            errors.append(f"[{path}] Leaf.kind không hợp lệ: {node.kind!r}")
        if not isinstance(node.raw, str) or not node.raw.strip():
            errors.append(f"[{path}] Leaf.raw phải là chuỗi có nội dung")
        _check_span(node.span, path, errors, allow_empty=False)

    def walk_list(node: ListNode, parent_kind: str, path: str) -> None:
        if node.kind not in LIST_KINDS:
            errors.append(f"[{path}] ListNode.kind không hợp lệ: {node.kind!r}")
            return
        span_ok = _check_span(node.span, path, errors, allow_empty=False)
        if not isinstance(node.children, list):
            errors.append(f"[{path}] ListNode.children phải là list")
            return

        if node.kind == "itemize":
            if parent_kind == "itemize":
                errors.append(f"[{path}] 'itemize' không thể là con trực tiếp của 'itemize' (phải qua 'item')")
            if not node.children:
                errors.append(f"[{path}] 'itemize' phải có ít nhất một con 'item'")
            prev_end = node.span[0] if span_ok else 0
            for idx, child in enumerate(node.children):
                cpath = f"{path}.children[{idx}]"
                if not isinstance(child, ListNode) or child.kind != "item":
                    errors.append(
                        f"[{cpath}] Con trực tiếp của 'itemize' chỉ được là ListNode(kind='item')"
                    )
                    continue
                if _check_span(child.span, cpath, errors, allow_empty=False) and span_ok:
                    if child.span[0] < prev_end:
                        errors.append(f"[{cpath}] span {child.span} chồng lấn hoặc ngược thứ tự đọc")
                    if child.span[0] < node.span[0] or child.span[1] > node.span[1]:
                        errors.append(f"[{cpath}] span {child.span} nằm ngoài span của cha {node.span}")
                    prev_end = max(prev_end, child.span[1])
                walk_list(child, "itemize", cpath)
        else:  # node.kind == "item"
            if parent_kind != "itemize":
                errors.append(f"[{path}] Cha của 'item' bắt buộc là 'itemize', nhận {parent_kind!r}")
            if not node.children:
                errors.append(f"[{path}] 'item' phải có ít nhất một node con")
            prev_end = node.span[0] if span_ok else 0
            for idx, child in enumerate(node.children):
                cpath = f"{path}.children[{idx}]"
                if isinstance(child, Leaf):
                    walk_leaf(child, cpath)
                elif isinstance(child, ListNode):
                    if child.kind != "itemize":
                        errors.append(f"[{cpath}] ListNode con của 'item' phải có kind='itemize'")
                    walk_list(child, "item", cpath)
                elif isinstance(child, Block):
                    errors.append(f"[{cpath}] Sau M2.3 không được còn Block trong cây")
                    continue
                else:
                    errors.append(
                        f"[{cpath}] Con của 'item' chỉ được là Leaf hoặc ListNode(kind='itemize'), "
                        f"nhận {type(child).__name__}"
                    )
                    continue
                if _check_span(child.span, cpath, errors, allow_empty=False) and span_ok:
                    if child.span[0] < prev_end:
                        errors.append(f"[{cpath}] span {child.span} chồng lấn hoặc ngược thứ tự đọc")
                    if child.span[0] < node.span[0] or child.span[1] > node.span[1]:
                        errors.append(f"[{cpath}] span {child.span} nằm ngoài span của cha {node.span}")
                    prev_end = max(prev_end, child.span[1])

    def walk_section(sec: Section, path: str, is_root: bool) -> None:
        if sec.kind not in SECTION_DEPTH:
            errors.append(f"[{path}] Section.kind không hợp lệ: {sec.kind!r}")
            return
        if not isinstance(sec.title_raw, str):
            errors.append(f"[{path}] title_raw phải là chuỗi")
        elif not is_root and _is_references_heading(sec.title_raw):
            errors.append(
                f"[{path}] Section References/Bibliography không được nằm trong cây: {sec.title_raw!r}"
            )
        if type(sec.starred) is not bool:
            errors.append(f"[{path}] starred phải là bool")

        span_ok = _check_span(sec.span, path, errors, allow_empty=is_root)
        if not isinstance(sec.children, list):
            errors.append(f"[{path}] children phải là list")
            return

        prev_end = sec.span[0] if span_ok else 0
        parent_depth = SECTION_DEPTH[sec.kind]

        for idx, child in enumerate(sec.children):
            cpath = f"{path}.children[{idx}]"
            if isinstance(child, Block):
                errors.append(f"[{cpath}] Sau M2.3 không được còn Block trong LeafTree")
                continue
            if isinstance(child, Section):
                if child.kind not in SECTION_DEPTH:
                    errors.append(f"[{cpath}] Section.kind không hợp lệ: {child.kind!r}")
                elif SECTION_DEPTH[child.kind] <= parent_depth:
                    errors.append(
                        f"[{cpath}] Cấp mục con ({child.kind}) phải sâu hơn cấp cha ({sec.kind})"
                    )
                walk_section(child, cpath, is_root=False)
            elif isinstance(child, ListNode):
                if child.kind != "itemize":
                    errors.append(
                        f"[{cpath}] ListNode trực tiếp dưới Section phải là 'itemize', nhận {child.kind!r}"
                    )
                walk_list(child, sec.kind, cpath)
            elif isinstance(child, Leaf):
                walk_leaf(child, cpath)
            else:
                errors.append(f"[{cpath}] Node không hợp lệ trong LeafTree: {type(child).__name__}")
                continue

            if _check_span(child.span, cpath, errors, allow_empty=False) and span_ok:
                if child.span[0] < prev_end:
                    errors.append(f"[{cpath}] span {child.span} chồng lấn hoặc ngược thứ tự đọc")
                if child.span[0] < sec.span[0] or child.span[1] > sec.span[1]:
                    errors.append(f"[{cpath}] span {child.span} nằm ngoài span của cha {sec.span}")
                prev_end = max(prev_end, child.span[1])

    walk_section(tree.root, "C.root", is_root=True)

    if structure_tree is not None and isinstance(structure_tree, StructureTree):
        _check_no_lost_text(structure_tree.root, tree.root, "C.root", errors)

    return _finish(errors, raise_on_error)


def _collect_leaves_in_span(
    sec: Section, start: int, end: int
) -> list[Leaf]:
    leaves: list[Leaf] = []

    def visit(node: Section | ListNode | Leaf | Block) -> None:
        if isinstance(node, Leaf):
            if node.span[0] >= start and node.span[1] <= end:
                leaves.append(node)
        elif isinstance(node, (Section, ListNode)):
            for child in node.children:
                visit(child)

    visit(sec)
    return leaves


def _strip_ws(text: str) -> str:
    return "".join(text.split())


def _check_no_lost_text(
    struct_sec: Section, leaf_root: Section, path: str, errors: list[str]
) -> None:
    """Kiểm 'không mất chữ' cho các Block text/display_math/figure."""
    for idx, child in enumerate(struct_sec.children):
        cpath = f"{path}.children[{idx}]"
        if isinstance(child, Section):
            _check_no_lost_text(child, leaf_root, cpath, errors)
        elif isinstance(child, Block):
            if child.type == "env" and child.env in {"itemize", "enumerate", "description"}:
                continue
            leaves = _collect_leaves_in_span(leaf_root, child.span[0], child.span[1])
            joined = _strip_ws("".join(leaf.raw for leaf in leaves))
            expected = _strip_ws(child.raw)
            if joined != expected:
                errors.append(
                    f"[{cpath}] Mất hoặc lệch chữ khi tách Block tại span {child.span}: "
                    f"expected={expected[:40]!r}, got={joined[:40]!r}"
                )


def validate_D(
    result: BibResult,
    bib_sources: list[BibSource] | None = None,
    *,
    raise_on_error: bool = True,
) -> list[str]:
    """Kiểm tra bất biến điểm giao [D] BibResult (M2.4b -> M2.5)."""
    errors: list[str] = []
    if not isinstance(result, BibResult):
        return _finish(["[D] result phải là BibResult"], raise_on_error)

    try:
        require_id(result.arxiv_id)
    except ValueError as exc:
        errors.append(f"[D] {exc}")

    if not isinstance(result.bibtex_version, str) or not result.bibtex_version.strip():
        errors.append("[D] bibtex_version phải là chuỗi khác rỗng")

    if not isinstance(result.entries, list):
        errors.append("[D] entries phải là list[dict]")
        return _finish(errors, raise_on_error)

    records: list[dict[str, Any]] = []
    entry_keys: set[str] = set()
    year_by_key: dict[str, Any] = {}

    for idx, entry in enumerate(result.entries):
        if not isinstance(entry, dict):
            errors.append(f"[D] entries[{idx}] phải là dict")
            continue
        ckey = entry.get("citation_key")
        if not isinstance(ckey, str) or not ckey.strip():
            errors.append(f"[D] entries[{idx}].citation_key phải là chuỗi khác rỗng")
        else:
            if ckey in entry_keys:
                errors.append(f"[D] citation_key bị trùng trong entries: {ckey!r}")
            entry_keys.add(ckey)

        etype = entry.get("entry_type")
        if not isinstance(etype, str) or not etype.strip():
            errors.append(f"[D] entries[{idx}].entry_type phải là chuỗi khác rỗng")

        year = entry.get("year")
        if year is not None:
            if type(year) is not int or not (1000 <= year <= 2999):
                errors.append(
                    f"[D] entries[{idx}].year phải là số nguyên 4 chữ số hợp lệ hoặc None, nhận {year!r}"
                )
        if isinstance(ckey, str):
            year_by_key[ckey] = year

        rec = dict(entry)
        if "arxiv_id" in rec and rec["arxiv_id"] != result.arxiv_id:
            errors.append(
                f"[D] entries[{idx}].arxiv_id={rec['arxiv_id']!r} lệch với result.arxiv_id={result.arxiv_id!r}"
            )
        rec["arxiv_id"] = result.arxiv_id
        records.append(rec)

    if not errors and records:
        try:
            from_records(records, "bibtex")
        except ValueError as exc:
            errors.append(f"[D] entries không khớp schema bibtex: {exc}")

    if not isinstance(result.raw_years, dict):
        errors.append("[D] raw_years phải là dict[str, str]")
    else:
        for k, raw_val in result.raw_years.items():
            if not isinstance(k, str) or not k.strip() or not isinstance(raw_val, str) or not raw_val.strip():
                errors.append(f"[D] raw_years[{k!r}] phải ánh xạ key sang chuỗi năm gốc khác rỗng")
            if k in year_by_key and year_by_key[k] is not None:
                errors.append(
                    f"[D] citation_key {k!r} có trong raw_years nhưng entries.year={year_by_key[k]!r} khác None"
                )

    if not isinstance(result.key_map, dict):
        errors.append("[D] key_map phải là dict[str, dict[str, str]]")
    else:
        for ver_str, mapping in result.key_map.items():
            if not isinstance(ver_str, str) or not ver_str.isdigit() or int(ver_str) < 1:
                errors.append(f"[D] khóa version trong key_map phải là chuỗi số nguyên >= 1, nhận {ver_str!r}")
            if not isinstance(mapping, dict):
                errors.append(f"[D] key_map[{ver_str!r}] phải là dict[str, str]")
                continue
            for orig_key, chosen_key in mapping.items():
                if not isinstance(orig_key, str) or not orig_key.strip():
                    errors.append(f"[D] key_map[{ver_str!r}] chứa key gốc rỗng")
                if not isinstance(chosen_key, str) or not chosen_key.strip():
                    errors.append(f"[D] key_map[{ver_str!r}][{orig_key!r}] ánh xạ tới key rỗng")
                elif chosen_key not in entry_keys:
                    errors.append(
                        f"[D] key_map[{ver_str!r}][{orig_key!r}] -> {chosen_key!r} không có trong entries"
                    )

    if not isinstance(result.stats, dict):
        errors.append("[D] stats phải là dict")

    if bib_sources is not None:
        for src in bib_sources:
            ver_key = str(src.version)
            if ver_key not in result.key_map:
                errors.append(f"[D] thiếu key_map cho version {ver_key!r}")
                continue
            ver_map = result.key_map[ver_key]
            for used_key in src.cite_keys_used:
                if used_key not in ver_map:
                    errors.append(
                        f"[D] cite_keys_used {used_key!r} của version {ver_key} thiếu trong key_map[{ver_key!r}]"
                    )

    return _finish(errors, raise_on_error)


def compute_element_id(
    arxiv_id: str,
    kind: str,
    content: str,
    child_ids: Sequence[str] | None = None,
) -> str:
    """Băm cây con tất định theo hợp đồng C1: `<publication_key>#<kind>-<16 hex sha256>`.

    - Lá (`sentence`, `formula`, `figure`): băm `(kind, content)`.
    - Nút cấu trúc (`document`, `section`..., `itemize`, `item`): băm `(kind, content, list(child_ids))`.
    """
    require_id(arxiv_id)
    if kind in LEAF_KINDS:
        payload = [kind, content]
    else:
        payload = [kind, content, list(child_ids or ())]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest16 = hashlib.sha256(encoded).hexdigest()[:16]
    return make_element_id(arxiv_id, f"{kind}-{digest16}")


__all__ = [
    "TYPES_VERSION",
    "SECTION_KINDS",
    "SECTION_DEPTH",
    "BLOCK_TYPES",
    "LEAF_KINDS",
    "LIST_KINDS",
    "Issue",
    "Span",
    "SourceBundle",
    "source_bundle_from_dict",
    "Block",
    "Leaf",
    "ListNode",
    "Section",
    "StructureTree",
    "BibSource",
    "LeafTree",
    "BibResult",
    "validate_A",
    "validate_B",
    "validate_B_prime",
    "validate_Bp",
    "validate_C",
    "validate_D",
    "compute_element_id",
]
