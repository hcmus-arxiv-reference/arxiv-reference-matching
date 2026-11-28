"""Read and merge bibliography entries of one Publication under the M2.4b contract.

Sources: docs/m2-interfaces.md, docs/data-contract.md (C6), and BibtexParser's
https://bibtexparser.readthedocs.io/en/main/customize.html for the parse stack.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
import re
from typing import TYPE_CHECKING
import unicodedata

import bibtexparser
from bibtexparser import middlewares
from bibtexparser.model import DuplicateBlockKeyBlock, DuplicateFieldKeyBlock, Entry, ImplicitComment
from pylatexenc.latex2text import LatexNodes2Text, MacroTextSpec, get_default_latex_context_db
from pylatexenc.latexwalker import get_default_latex_context_db as get_parser_context
from pylatexenc.macrospec import MacroSpec

from src.common.schema import require_id
from .normalize import _group_end, _space_end, normalize
from .types import normalize_cite_key

if TYPE_CHECKING:
    from src.parse.types import BibResult, BibSource


BIBTEX_VERSION = "8"
# pylatexenc 2.10 has a text replacement for href, but no default argument
# specification. Register both so linked titles and missing arguments are safe.
_BIB_PARSER = get_parser_context()
_BIB_PARSER.add_context_category("bibtex-links", macros=[MacroSpec("href", "{{")], prepend=True)
_BIB_CONTEXT = get_default_latex_context_db()
_BIB_CONTEXT.add_context_category("bibtex-links", macros=[
    MacroTextSpec("href", lambda node, l2tobj:
                  l2tobj.node_arg_to_text(node, 1) or l2tobj.node_arg_to_text(node, 0)),
], prepend=True)
_BIB_TEXT = LatexNodes2Text(math_mode="verbatim", latex_context=_BIB_CONTEXT)
_DOI = re.compile(r"\b10\.\d{4,9}/[^\s{}<>\"\\]+", re.I)
_URL = re.compile(r"https?://[^\s{}<>\"\\]+", re.I)
_ARXIV = r"(?:\d{4}\.\d{4,5}|[a-z][a-z.\-]*/\d{7})"
_ARXIV_LINK = re.compile(rf"(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)({_ARXIV})(?:v\d+)?", re.I)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_BIBITEM = re.compile(r"\s*\\bibitem(?![A-Za-z@])")
_BIBINFO = re.compile(r"\\bibinfo(?![A-Za-z@])")
_TITLE_QUOTE = re.compile(r"``(.+?)''|“(.+?)”|(?<!\\)\"((?:\\.|[^\"\\])+?)\"")
_TITLE_STYLE = re.compile(r"\\(?:emph|textit|textsl)(?![A-Za-z@])")
_TITLE_DECLARATION = re.compile(r"\\(?:it|em|sl)(?![A-Za-z@])\s*")
_COMMA_AUTHOR = re.compile(r"(?:and\s+)?([^,{}\d]+,\s*(?:[A-Z]\.\s*~?\s*)+),\s*")
_BIBITEM_TOKENS = re.compile(r"\\(?:[A-Za-z@]+|.)|\$\$|[{}$,]|\.(?=\s|$)")
_PERIOD_WORD = re.compile(r"(?:e\.g|i\.e|[^\W\d_]+)$", re.I)
_INITIAL = re.compile(r"(?<!\w)(?:[A-Z]|Ya|Yu|Ch|Th)\.")
_NAME_PARTICLES = {"and", "de", "del", "den", "der", "di", "du", "et", "al", "la", "le", "van", "von"}
_VOLUME_STYLE = re.compile(r"(?:\{\s*\\bf\s+|\\textbf\s*\{)\s*\d")
_TRAILING_YEAR = re.compile(r"\s*[,.(]?\s*(?:19|20)\d{2}\b[\s).,]*$")


@dataclass
class _Candidate:
    version: int
    key: str
    origin: str
    fields: dict
    ref_arxiv: str | None
    raw_year: str | None


def _value(fields: dict, name: str) -> str | None:
    value = fields.get(name)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _first_match(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text)
    return match.group().rstrip(".,;:") if match else None


def _arxiv_ref(fields: dict) -> str | None:
    for name in ("arxiv", "arxivid", "eprint"):
        value = _value(fields, name)
        archive = _value(fields, "archiveprefix")
        if name == "eprint" and archive and archive.casefold() != "arxiv":
            continue
        if value and (match := re.fullmatch(rf"({_ARXIV})(?:v\d+)?", value, re.I)):
            return match[1].casefold()
    if match := _ARXIV_LINK.search(_value(fields, "url") or ""):
        return match[1].casefold()
    return None


def _candidate(version: int, key: str, origin: str, fields: dict) -> _Candidate:
    raw_year = _value(fields, "year")
    # The shared BibResult contract accepts years from 1000 through 2999.
    year = int(raw_year) if raw_year and re.fullmatch(r"[12]\d{3}", raw_year) else None
    authors = fields.get("author")
    if isinstance(authors, list):
        authors = [text for author in authors if (text := _clean_bib_text(author))] or None
    else:
        authors = None
    doi = _first_match(_DOI, _value(fields, "doi") or _value(fields, "url") or "")
    return _Candidate(version, key, origin, {
        "entry_type": _value(fields, "entry_type"),
        "title": _clean_bib_text(_value(fields, "title")),
        "authors": authors,
        "year": year,
        "doi": doi.casefold() if doi else None,
        "journal": _clean_bib_text(_value(fields, "journal") or _value(fields, "booktitle")),
        "url": _value(fields, "url"),
    }, _arxiv_ref(fields), raw_year if year is None else None)


def _clean_bib_text(text: str | None) -> str | None:
    """Decode prose accents/grouping from both sources, preserving math verbatim.

    pylatexenc is installed by bibtexparser 2.1.0. Conversion documentation:
    https://pylatexenc.readthedocs.io/en/latest/latex2text/
    """
    if text is None:
        return None
    decoded = _BIB_TEXT.latex_to_text(normalize("sentence", text), latex_context=_BIB_PARSER)
    return " ".join(decoded.split()) or None


def _expression_parts(value: str) -> list[str]:
    """Split BibTeX's # operator outside literal braces and quotes."""
    parts = []
    start = depth = 0
    quoted = escaped = False
    for i, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == '"' and depth == 0:
            quoted = not quoted
        elif char == "#" and depth == 0 and not quoted:
            parts.append(value[start:i].strip())
            start = i + 1
    parts.append(value[start:].strip())
    return parts


class _ResolveStrings(middlewares.LibraryMiddleware):
    """Expand @string aliases and concatenation before stripping delimiters."""

    def transform(self, library):
        strings = {key.casefold(): block.value for key, block in library.strings_dict.items()}

        @lru_cache(maxsize=None)
        def expand(expression: str, active: frozenset[str]) -> str | None:
            parts = []
            length = 0
            for term in _expression_parts(expression):
                key = term.casefold()
                if len(term) >= 2 and (term[0], term[-1]) in {('{', '}'), ('"', '"')}:
                    value = term[1:-1]
                elif key in strings:
                    if key in active or len(active) >= 32:
                        return None
                    value = expand(strings[key], active | {key})
                    if value is None:
                        return None
                else:
                    value = term
                length += len(value)
                if length > 1024 * 1024:
                    return None
                parts.append(value)
            return "".join(parts)

        for entry in library.entries:
            for field in entry.fields:
                value = field.value
                if isinstance(value, str) and (value.casefold() in strings or len(_expression_parts(value)) > 1):
                    resolved = expand(value, frozenset())
                    if resolved is not None:
                        field.value = "{" + resolved + "}"
        return library


def _parse_bib(text: str):
    # Pin the parse stack to avoid changes in library defaults affecting output.
    return bibtexparser.parse_string(text, parse_stack=[
        _ResolveStrings(),
        middlewares.RemoveEnclosingMiddleware(),
        middlewares.SeparateCoAuthors(),
    ])


def _bib_candidates(version: int, bib_files: dict[str, str], issues: list[dict]) -> list[_Candidate]:
    if not bib_files:
        return []
    # A Version's bibliography files can share macros and crossrefs.
    library = _parse_bib("\n".join(bib_files[name] for name in sorted(bib_files)))
    entries = list(library.entries)
    entries.extend(_recover_entries(library, version, issues))

    by_key = {}
    rows = []
    for entry in entries:
        if not entry.key.strip():
            issues.append({"version": version, "code": "empty_key", "line": entry.start_line})
            continue
        fields = {name.casefold(): field.value for name, field in entry.fields_dict.items()}
        fields["entry_type"] = entry.entry_type.casefold()
        by_key.setdefault(entry.key, fields)
        rows.append((entry.key, fields))

    result = []
    for key, row in rows:
        fields = dict(row)
        seen = {key}
        parent = _value(fields, "crossref")
        while parent:
            if parent in seen or parent not in by_key:
                issues.append({"version": version, "key": key, "parent": parent,
                               "code": "cyclic_crossref" if parent in seen else "missing_crossref"})
                break
            seen.add(parent)
            inherited = by_key[parent]
            # Parent identity fields (title, DOI, authors, URL) belong to the
            # container. Copying them could merge the child with its parent.
            for name in ("year", "journal", "booktitle"):
                if not fields.get(name) and inherited.get(name):
                    fields[name] = inherited[name]
            parent = _value(inherited, "crossref")
        result.append(_candidate(version, key, "bib", fields))
    return result


def _recover_entries(library, version: int, issues: list[dict]) -> list[Entry]:
    """Recover duplicate fields and multiline headers from unparsed blocks.

    Only implicit comments are considered for header repair, so field values
    inside successfully parsed entries retain their original text. Duplicate
    fields use the last occurrence, with conflicting values retained in logs.
    """
    macros = "\n".join(item.raw for item in library.strings if item.raw)
    pending = list(library.failed_blocks) + [block for block in library.comments if isinstance(block, ImplicitComment)]
    recovered = []
    seen = set()
    for block in pending:
        marker = (type(block).__name__, block.raw)
        if marker in seen:
            continue
        seen.add(marker)
        raw = block.raw or ""
        if isinstance(block, ImplicitComment):
            fixed = re.sub(r"^\s*(@[A-Za-z]+)[ \t]*\r?\n\s*(?=[{(])", r"\1", raw, count=1)
            if fixed == raw:
                continue
            raw = fixed
            issues.append({"version": version, "code": "multiline_entry_header", "line": block.start_line})
        else:
            issues.append({"version": version, "code": type(block).__name__, "line": block.start_line})
            if not isinstance(block, (DuplicateBlockKeyBlock, DuplicateFieldKeyBlock)):
                continue
            entry = block.ignore_error_block
            if not isinstance(entry, Entry):
                continue
            if isinstance(block, DuplicateFieldKeyBlock):
                fields = {}
                for field in entry.fields:
                    name = field.key.casefold()
                    if name in fields and fields[name] != field.value:
                        issues.append({"version": version, "key": entry.key, "code": "duplicate_field_conflict",
                                       "field": name, "chosen": field.value, "previous": fields[name]})
                    fields[name] = field.value
                raw = "@" + entry.entry_type + "{" + entry.key + ",\n" + ",\n".join(
                    name + " = " + value for name, value in fields.items()) + "\n}"
        parsed = _parse_bib(macros + "\n" + raw)
        recovered.extend(parsed.entries)
        pending.extend(parsed.failed_blocks)
        pending.extend(block for block in parsed.comments if isinstance(block, ImplicitComment))
    return recovered


def _styled_title(text: str) -> tuple[str, int] | None:
    """Read a leading scoped LaTeX emphasis without consuming the venue."""
    if styled := _TITLE_STYLE.match(text):
        start = _space_end(text, styled.end())
        if end := _group_end(text, start, "{"):
            return text[start + 1:end - 1], end
    if text.startswith("{"):
        declaration = _TITLE_DECLARATION.match(text, _space_end(text, 1))
        if declaration and (end := _group_end(text, 0, "{")):
            return text[declaration.end():end - 1].removesuffix(r"\/"), end
    return None


def _title_text(title: str) -> str | None:
    title = title.strip(" .,\"\x60'")
    if styled := _styled_title(title):
        content, end = styled
        if end == len(title):
            title = content.strip()
    elif title.startswith("{") and _group_end(title, 0, "{") == len(title):
        title = title[1:-1].strip()
    return title or None


def _bibinfo(body: str) -> dict[str, list[str]]:
    fields = defaultdict(list)
    for match in _BIBINFO.finditer(body):
        start = _space_end(body, match.end())
        key_end = _group_end(body, start, "{")
        if key_end is None:
            continue
        value_start = _space_end(body, key_end)
        value_end = _group_end(body, value_start, "{")
        if value_end is not None:
            fields[body[start + 1:key_end - 1].strip()].append(body[value_start + 1:value_end - 1].strip())
    return fields


def _bibitem_separators(text: str) -> list[int]:
    """Find punctuation between fields, outside LaTeX arguments and math."""
    depth = 0
    math = ""
    separators = []
    for match in _BIBITEM_TOKENS.finditer(text):
        token = match[0]
        if token in ("$", "$$"):
            if not math or math == token:
                math = "" if math else token
        elif token == "{":
            depth += 1
        elif token == "}":
            depth -= 1
        elif not depth and not math and token in (",", "."):
            pos = match.start()
            if token == "." and (word := _PERIOD_WORD.search(text, max(0, pos - 8), pos)):
                if _INITIAL.fullmatch(word[0] + ".") or word[0].casefold() in {"al", "vs", "e.g", "i.e"}:
                    continue
            separators.append(pos)
    return separators


def _looks_like_names(text: str) -> bool:
    # Fold LaTeX name accents and explicit spaces for this boundary check only.
    text = text.replace(r"\ ", " ").replace("~", " ")
    text = re.sub(r"\\(?:[A-Za-z@]+[ \t]?|.)", "", text)
    text = text.replace("{", "").replace("}", "")
    words = re.findall(r"[^\W\d_]+", text)
    return bool(words) and not re.search(r"\d", text) and all(
        word[0].isupper() or word.casefold() in _NAME_PARTICLES for word in words
    )


def _plain_bibitem_fields(body: str) -> tuple[str, list[str] | None]:
    names = []
    pos = 0
    while match := _COMMA_AUTHOR.match(body, pos):
        names.append(match[1].strip())
        pos = match.end()
    if names:
        return body[pos:], names

    separators = _bibitem_separators(body)
    for pos, next_pos in zip(separators, separators[1:] + [len(body)]):
        authors = body[:pos]
        if not _looks_like_names(authors):
            break
        following = body[pos + 1:next_pos].strip()
        if body[pos] == "," and _looks_like_names(following):
            # Initials or a final "and" identify another author in the list.
            # Without initials, allow surname-first lists such as "Doe, Jane".
            if following.casefold().startswith("and ") or _INITIAL.search(following) or not _INITIAL.search(authors):
                continue
        return body[pos + 1:].lstrip(), _split_authors(authors)
    return "", None


def _plain_title(text: str) -> str:
    if styled := _styled_title(text):
        title, end = styled
        suffix = text[end:].lstrip()
        if not suffix or suffix[0] in ".,;(":
            return title

    separators = _bibitem_separators(text)
    for pos in separators:
        suffix = text[pos + 1:].lstrip()
        if (styled := _styled_title(suffix)) and styled[0].strip():
            return text[:pos]

    if volume := _VOLUME_STYLE.search(text):
        # A comma before the bold volume separates a plain title from its
        # journal. A leading journal/volume with no title should stay empty.
        commas = [pos for pos in separators if pos < volume.start() and text[pos] == ","]
        return text[:commas[-1]] if commas else ""

    stop = next((pos for pos in separators if text[pos] == "."), len(text))
    return _TRAILING_YEAR.sub("", text[:stop])


def _split_authors(text: str) -> list[str] | None:
    names = re.split(r"\s+and\s+|\s*;\s*", text, flags=re.I)
    return [name.strip(" ,") for name in names if name.strip(" ,")] or None


def _bibitem_parts(body: str) -> tuple[str | None, list[str] | None]:
    if quote := _TITLE_QUOTE.search(body):
        author_text = body[:quote.start()]
        title = next(group for group in quote.groups() if group is not None)
    elif len(blocks := re.split(r"\\newblock(?![A-Za-z@])", body)) > 1:
        if blocks[0].strip():
            author_text, title = blocks[:2]
        elif len(blocks) > 3:
            # Some styles open the item with \newblock before the authors
            # (2508.04688): the empty text before it is not the author block.
            author_text, title = blocks[1:3]
        else:
            # "\newblock Authors. Title. \newblock Journal": the first block
            # holds both, so read it like an item without \newblock. When no
            # title is found there (e.g. "Lance, E.C.: Title"), keep the whole
            # block as the title, which still carries the title words.
            remainder, authors = _plain_bibitem_fields(blocks[1])
            if title := _title_text(_plain_title(remainder)):
                return title, authors
            author_text, title = blocks[:2]
    else:
        remainder, authors = _plain_bibitem_fields(body)
        return _title_text(_plain_title(remainder)), authors
    return _title_text(title), _split_authors(author_text)


def _bibitem_candidate(version: int, text: str) -> _Candidate | None:
    head = _BIBITEM.match(text)
    if not head:
        return None
    start = _group_end(text, head.end(), "[") or head.end()
    start = _space_end(text, start)
    end = _group_end(text, start, "{")
    if end is None or not (key := normalize_cite_key(text[start + 1:end - 1])):
        return None
    body = normalize("sentence", text[end:])
    doi, url = _first_match(_DOI, body), _first_match(_URL, body)
    arxiv = _ARXIV_LINK.search(body)
    prose = _ARXIV_LINK.sub("", _DOI.sub("", _URL.sub("", body)))
    years = _YEAR.findall(prose)
    explicit = _bibinfo(body)
    if explicit:
        # Structured styles sometimes intentionally omit a title. A journal
        # or a page number is not a useful substitute for a missing title.
        title = _title_text(next(iter(explicit.get("title", ())), ""))
        authors = explicit.get("author")
    else:
        title, authors = _bibitem_parts(prose)
    return _candidate(version, key, "bibitem", {
        "title": title, "author": authors,
        "year": next(iter(explicit.get("year", ())), years[-1] if years else None),
        "journal": next(iter(explicit.get("journal", ())), None),
        "doi": doi, "url": url, "arxiv": arxiv[1] if arxiv else None,
    })


_FIELDS = ("entry_type", "title", "authors", "year", "doi", "journal", "url")


def _priority(entry: _Candidate) -> tuple:
    return (-entry.version, entry.key, entry.origin != "bib")


def _title_key(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).casefold().replace("{", "").replace("}", "")
    return " ".join(re.findall(r"\w+", text))


def _groups(entries: list[_Candidate], issues: list[dict]) -> list[list[_Candidate]]:
    """Merge duplicate Version/key pairs, identifiers, then compatible same keys.

    Across Versions a reused key requires compatible DOI/arXiv identifiers and
    token Jaccard similarity >= 0.5 when both titles exist. Remaining entries
    can join by exact normalized title/year when identifiers agree.
    """
    parent = list(range(len(entries)))
    identifiers = [{"doi": {e.fields["doi"]} - {None}, "arxiv": {e.ref_arxiv} - {None}} for e in entries]

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(a: int, b: int) -> None:
        a, b = root(a), root(b)
        if a != b:
            parent[b] = a
            for name in ("doi", "arxiv"):
                identifiers[a][name].update(identifiers[b][name])

    version_keys = {}
    for i, entry in enumerate(entries):
        join(version_keys.setdefault((entry.version, entry.key), i), i)

    strong, weak, same_keys = {}, defaultdict(list), defaultdict(list)
    for i, entry in enumerate(entries):
        for name, value in (("doi", entry.fields["doi"]), ("arxiv", entry.ref_arxiv)):
            if value:
                join(strong.setdefault((name, value), i), i)
        title, year = entry.fields["title"], entry.fields["year"]
        if title and year and (normalized := _title_key(title)):
            weak[(normalized, year)].append(i)
        same_keys[entry.key].append(i)

    for indices in same_keys.values():
        representatives = []
        for i in indices:
            for previous in representatives:
                a, b = root(previous), root(i)
                if a == b:
                    break
                if any(len(identifiers[a][name] | identifiers[b][name]) > 1 for name in ("doi", "arxiv")):
                    continue
                left = set(_title_key(entries[previous].fields["title"] or "").split())
                right = set(_title_key(entries[i].fields["title"] or "").split())
                if left and right and len(left & right) / len(left | right) < 0.5:
                    continue
                join(a, b)
                break
            else:
                representatives.append(i)

    for (title, year), indices in sorted(weak.items()):
        roots = sorted({root(i) for i in indices})
        if len(roots) < 2:
            continue
        if any(len(set().union(*(identifiers[i][name] for i in roots))) > 1 for name in ("doi", "arxiv")):
            issues.append({"code": "ambiguous_title_year", "title": title, "year": year})
            continue
        for i in roots[1:]:
            join(roots[0], i)

    grouped = defaultdict(list)
    for i, entry in enumerate(entries):
        grouped[root(i)].append(entry)
    return sorted((sorted(group, key=_priority) for group in grouped.values()), key=lambda g: _priority(g[0]))


def merge_bibtex(arxiv_id: str, sources: list[BibSource]) -> BibResult:
    """Return cited BibTeX groups and a Version-scoped citation key map.

    Fill missing fields from other copies. On conflict, use the newest
    nonempty value, then the lexicographically smallest source key. Prefer a
    .bib value to a bibitem value on the same Version/key. Record conflicts
    and unresolved citations in stats for the integration log. C12 filters
    groups after merging, keeping all fields from their uncited copies.
    """
    from src.parse.types import BibResult

    require_id(arxiv_id)
    by_version = {}
    for source in sources:
        if source.arxiv_id != arxiv_id or type(source.version) is not int or source.version < 1:
            raise ValueError("Expected a positive Version of the requested Publication")
        if source.version in by_version:
            raise ValueError(f"Duplicate BibSource for Version {source.version}")
        by_version[source.version] = source

    candidates, issues = [], []
    for version, source in sorted(by_version.items()):
        candidates.extend(_bib_candidates(version, source.bib_files, issues))
        issues.extend({"version": version, "code": "missing_bib", "file": name}
                      for name in sorted(source.missing_bib))
        for text in source.bibitems_raw:
            entry = _bibitem_candidate(version, text)
            if entry:
                candidates.append(entry)
                if entry.fields["title"] is None:
                    issues.append({"version": version, "key": entry.key, "code": "missing_bibitem_title"})
            else:
                issues.append({"version": version, "code": "invalid_bibitem"})

    rows, conflicts, invalid_years, raw_years = [], [], [], {}
    key_targets = {}
    cited = {(source.version, key) for source in sources for key in source.cite_keys_used}
    cited_keys = {key for _, key in cited}
    groups = _groups(candidates, issues)
    groups_by_key = defaultdict(set)
    for index, group in enumerate(groups):
        for entry in group:
            groups_by_key[entry.key].add(index)
    filtered = 0
    canonical_by_group = {}
    used, reserved = set(), {entry.key for entry in candidates}
    for index, group in enumerate(groups):
        direct = any((entry.version, entry.key) in cited for entry in group)
        referenced_elsewhere = any(entry.key in cited_keys and len(groups_by_key[entry.key]) == 1 for entry in group)
        if not direct and not referenced_elsewhere:
            filtered += 1
            continue
        preferred = group[0].key
        canonical = preferred
        suffix = 2
        while canonical in used:
            canonical = f"{preferred}__{suffix}"
            suffix += 1
            while canonical in reserved:
                canonical = f"{preferred}__{suffix}"
                suffix += 1
        if canonical != preferred:
            issues.append({"code": "canonical_key_collision", "key": preferred, "chosen": canonical})
        used.add(canonical)
        canonical_by_group[index] = canonical
        row = {"arxiv_id": arxiv_id, "citation_key": canonical}
        for name in _FIELDS:
            available = [entry for entry in group if entry.fields[name] is not None]
            winner = available[0] if available else None
            row[name] = winner.fields[name] if winner else ("misc" if name == "entry_type" else None)
            alternatives = [{"version": entry.version, "key": entry.key, "value": entry.fields[name]}
                            for entry in available if entry.fields[name] != row[name]]
            if alternatives:
                conflicts.append({"citation_key": canonical, "field": name, "chosen": row[name],
                                  "chosen_version": winner.version, "alternatives": alternatives})
        rows.append(row)
        for entry in group:
            key_targets[(entry.version, entry.key)] = canonical
            if entry.raw_year is not None:
                if row["year"] is None:
                    raw_years.setdefault(canonical, entry.raw_year)
                invalid_years.append({"version": entry.version, "key": entry.key, "value": entry.raw_year})

    key_map, unresolved, cross_version = {}, [], []
    for version, source in sorted(by_version.items()):
        mapping = {}
        for key in dict.fromkeys(source.cite_keys_used):
            target = key_targets.get((version, key))
            matching_groups = groups_by_key.get(key, set())
            if target is None and len(matching_groups) == 1:
                index = next(iter(matching_groups))
                target = canonical_by_group[index]
                cross_version.append({"version": version, "key": key, "citation_key": target,
                                      "source_versions": sorted({entry.version for entry in groups[index] if entry.key == key})})
            if target is not None:
                mapping[key] = target
            else:
                unresolved.append({"version": version, "key": key,
                                   "reason": "missing_entry"})
                if len(matching_groups) > 1:
                    issues.append({"version": version, "key": key, "code": "ambiguous_cross_version_key"})
        key_map[str(version)] = mapping

    return BibResult(arxiv_id=arxiv_id, entries=sorted(rows, key=lambda row: row["citation_key"]),
        key_map=key_map, raw_years=raw_years, bibtex_version=BIBTEX_VERSION, stats={
            "entry_before": len(candidates), "entry_after": len(rows),
            "groups_before_filter": len(groups), "groups_filtered_out": filtered,
            "from_bib": sum(e.origin == "bib" for e in candidates),
            "from_bibitem": sum(e.origin == "bibitem" for e in candidates),
            "unresolved": len(unresolved), "unresolved_keys": unresolved,
            "cross_version_resolved": len(cross_version), "cross_version_keys": cross_version,
            "field_conflicts": len(conflicts), "conflicts": conflicts,
            "invalid_years": invalid_years, "issues": issues,
            "versions_without_bibliography": sum(not s.bib_files and not s.bibitems_raw and not s.missing_bib
                                                 for s in by_version.values()),
        })
