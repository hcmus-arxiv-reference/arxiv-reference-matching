"""Build M2 heading and bibliography outputs using Source's literal TeX scanner."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import re

from src.common.corpus import verified_source
from src.parse.source import SourceBundle, _group, _scan
from src.parse.types import (
    SECTION_DEPTH, BibSource, Block, Section, StructureTree, _is_references_heading,
)

STRUCTURE_VERSION = "2"


def _clean(text, tokens):
    """Blank comments while preserving offsets and literal examples."""
    pieces = []
    cursor = 0
    pattern = re.compile(r"\\[^\n]|%[^\n]*")

    def blank(match):
        value = match.group()
        return " " * len(value) if value.startswith("%") else value

    for token in tokens:
        if token.name in {"literal", "opaque_env"}:
            pieces.append(pattern.sub(blank, text[cursor:token.start]))
            pieces.append(text[token.start:token.end])
            cursor = token.end
    pieces.append(pattern.sub(blank, text[cursor:]))
    return "".join(pieces)


def _argument(text, end):
    starred = text.startswith("*", end)
    pos = end + int(starred)
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if not text.startswith("[", pos):
            break
        _, pos = _group(text, pos, "[")
    value, end = _group(text, pos)
    return value, end, starred


def build_structure(bundle: SourceBundle, arxiv_id: str, version: int,
                    directory: Path | None = None) -> tuple[StructureTree, BibSource]:
    """Parse one assembled Version. Only receipt-listed bibliography files are read."""
    if bundle.status == "error":
        raise ValueError("Cannot build structure for a failed SourceBundle")
    bib = BibSource(arxiv_id, version)
    root = Section("document", "", False, (0, 0))
    tree = StructureTree(arxiv_id, version, root)
    if bundle.status == "empty_non_tex":
        return tree, bib

    tokens = []
    scan = _scan(bundle.text, bundle.root or "", tokens)
    tree.issues = [asdict(issue) for issue in scan.issues]
    text = _clean(bundle.text, tokens)
    begin = next((t for t in tokens if (t.name, t.argument) == ("begin", "document")), None)
    if begin is None:
        raise ValueError("Missing active document environment")
    if not scan.ends_document:
        raise ValueError("Missing active end of document")
    start = begin.end + int(text.startswith("\n", begin.end))
    stop = next((t.start for t in tokens if (t.name, t.argument) == ("end", "document")
                 and t.start >= start), len(text))
    root.span = start, stop
    tree.dropped.append({"reason": "preamble", "span": [0, start]})
    stack = [root]
    cursor = start
    ref_start = ref_depth = None
    envs = []
    ends = {}
    items = {}
    math = {}
    bibliography = None
    item_start = None
    resources = []
    for t in tokens:
        if t.start >= stop:
            break
        if t.name in {"bibliography", "addbibresource"}:
            value, _, _ = _argument(text, t.end)
            resources.extend(key.strip() for key in value.split(",") if key.strip())
        if t.start < start:
            continue
        if t.name == "begin":
            envs.append(t)
            if t.argument == "thebibliography":
                bibliography = t
                item_start = None
        elif t.name == "end" and envs and t.argument == envs[-1].argument:
            opener = envs.pop()
            ends[opener.start] = t.end
            if opener == bibliography:
                if item_start is not None:
                    bib.bibitems_raw.append(text[item_start:t.start])
                bibliography = None
                item_start = None
        elif bibliography is not None and t.name == "bibitem":
            if item_start is not None:
                bib.bibitems_raw.append(text[item_start:t.start])
            item_start = t.start
        elif bibliography is None and t.name.lower() in {
            "cite", "citep", "citet", "citealp", "citealt", "citeauthor", "citeyear",
            "citeyearpar", "citenum", "parencite", "textcite", "autocite", "footcite",
            "fullcite", "supercite",
        }:
            try:
                keys, _, _ = _argument(text, t.end)
            except ValueError:
                continue
            items[t.start] = [k.strip() for k in keys.split(",") if k.strip()]
        elif t.name in {"$$", "[", "]"}:
            key = "$$" if t.name == "$$" else "["
            if key in math and t.name in {"$$", "]"}:
                ends[math.pop(key)] = t.end
            elif t.name != "]":
                math[key] = t.start

    if resources:
        verified = verified_source(Path(directory)) if directory is not None else None
        if directory is not None and verified is None:
            raise ValueError("Invalid bibliography source receipt")
        for key in resources:
            name = key if key.lower().endswith(".bib") else key + ".bib"
            path = (Path(bundle.root or "").parent / name).as_posix()
            if verified and path in verified.bib_files:
                data = (verified.path / path).read_bytes()
                try:
                    bib.bib_files[path] = data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    bib.bib_files[path] = data.decode("latin-1")
            elif name not in bib.missing_bib:
                bib.missing_bib.append(name)

    def flush(end):
        if ref_start is None and text[cursor:end].strip():
            stack[-1].children.append(Block("text", None, text[cursor:end], (cursor, end)))

    def close(depth, end):
        while len(stack) > 1 and SECTION_DEPTH[stack[-1].kind] >= depth:
            node = stack.pop()
            node.span = node.span[0], end

    def drop(reason, a, b):
        tree.dropped.append({"reason": reason, "span": [a, b]})

    for t in tokens:
        if t.start < cursor or t.start >= stop:
            continue
        heading = t.name in SECTION_DEPTH and t.name != "document"
        # A control word used as an argument (e.g. titlespacing) has no title.
        if heading and not text[t.end:].lstrip().startswith(("{", "[", "*")):
            continue
        if ref_start is not None:
            if t.name != "appendix" and not (heading and SECTION_DEPTH[t.name] <= ref_depth):
                continue
            drop("references", ref_start, t.start)
            ref_start = None
            cursor = t.start
        if heading:
            title, end, star = _argument(text, t.end)
            flush(t.start)
            depth = SECTION_DEPTH[t.name]
            close(depth, t.start)
            cursor = end + int(text.startswith("\n", end))
            if _is_references_heading(title):
                ref_start, ref_depth = t.start, depth
            else:
                node = Section(t.name, title, star, (t.start, stop))
                stack[-1].children.append(node)
                stack.append(node)
        elif t.name == "appendix":
            flush(t.start)
            close(1, t.start)
            cursor = t.end + int(text.startswith("\n", t.end))
            drop("appendix_marker", t.start, cursor)
        elif t.name in {"begin", "opaque_env", "$$", "["}:
            if t.name == "begin" and t.argument in {"CJK", "CJK*", "appendix", "appendices"}:
                continue
            end = t.end if t.name == "opaque_env" else ends.get(t.start)
            if end is None:
                continue
            flush(t.start)
            cursor = end
            if t.argument == "thebibliography":
                drop("references", t.start, end)
            elif t.argument == "comment":
                drop("comment", t.start, end)
            else:
                kind = "env" if t.argument else "display_math"
                stack[-1].children.append(Block(kind, t.argument or None, text[t.start:end],
                                                (t.start, end)))
        elif t.name in {"bibliography", "addbibresource", "printbibliography"}:
            flush(t.start)
            cursor = t.end if t.name == "printbibliography" else _argument(text, t.end)[1]
            drop("references", t.start, cursor)
    flush(stop)
    if ref_start is not None:
        drop("references", ref_start, stop)
    close(1, stop)
    excluded = iter(d for d in tree.dropped if d["reason"] == "references")
    region = next(excluded, None)
    for pos, keys in items.items():
        while region and region["span"][1] <= pos:
            region = next(excluded, None)
        if not region or pos < region["span"][0]:
            bib.cite_keys_used.extend(keys)
    return tree, bib
