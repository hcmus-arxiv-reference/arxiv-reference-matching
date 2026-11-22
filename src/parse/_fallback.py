"""Các hàm thay thế tạm thời cho các gói M2 chưa merge vào `main` (normalize, bibtex).

Module này chỉ được dùng khi người gọi bật cờ tường minh (`allow_fallback=True` hoặc
`--allow-fallback`), và mọi lần sử dụng đều được ghi vào log từng Version cùng file metrics.
Sau khi PR #44 (Normalize + BibTeX) merge vào `main`, module này sẽ bị xóa.

Nguồn tham khảo lệnh định dạng LaTeX:
- LaTeX2e Unofficial Reference Manual (https://latexref.xyz/)
- Gói booktabs (https://ctan.org/pkg/booktabs)
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from src.parse.types import (
    BibResult,
    BibSource,
)

FALLBACK_BIBTEX_VERSION = "fallback-3"
FALLBACK_NORMALIZE_VERSION = "fallback-1"

# Bảng hằng số các lệnh định dạng vô nghĩa bị loại bỏ khi chuẩn hóa dự phòng
FORMATTING_COMMANDS: tuple[str, ...] = (
    r"\centering",
    r"\raggedright",
    r"\raggedleft",
    r"\noindent",
    r"\indent",
    r"\small",
    r"\footnotesize",
    r"\scriptsize",
    r"\tiny",
    r"\large",
    r"\Large",
    r"\LARGE",
    r"\huge",
    r"\Huge",
    r"\normalsize",
    r"\toprule",
    r"\midrule",
    r"\bottomrule",
    r"\hline",
    r"\newpage",
    r"\clearpage",
    r"\pagebreak",
    r"\linebreak",
    r"\allowbreak",
    r"\smallskip",
    r"\medskip",
    r"\bigskip",
    r"\vfill",
    r"\hfill",
)

_FORMATTING_WITH_ARG_RE = re.compile(
    r"\\(?:vspace|hspace|vskip|hskip|cline)\*?\s*\{[^{}]*\}"
)
_FLOAT_OPT_RE = re.compile(
    r"(\\begin\{(?:figure|table)\*?\})\s*\[[!htbpH\s]+\]"
)
_INLINE_PAREN_MATH_RE = re.compile(r"\\\((.*?)\\\)", re.DOTALL)
_INLINE_ENV_MATH_RE = re.compile(
    r"\\begin\{math\}(.*?)\\end\{math\}", re.DOTALL
)
_DISPLAY_DOLLAR_RE = re.compile(r"^\$\$(.*)\$\$$", re.DOTALL)
_DISPLAY_BRACKET_RE = re.compile(r"^\\\[(.*)\\\]$", re.DOTALL)
_DISPLAY_ENV_RE = re.compile(
    r"^\\begin\{(?:equation\*?|displaymath|align\*?|gather\*?|multline\*?|eqnarray\*?|flalign\*?)\}"
    r"(.*)"
    r"\\end\{(?:equation\*?|displaymath|align\*?|gather\*?|multline\*?|eqnarray\*?|flalign\*?)\}$",
    re.DOTALL,
)


def fallback_normalize(kind: str, raw: str) -> str:
    """Hàm chuẩn hóa dự phòng tuân thủ bất biến M2.4a khi gói Normalize chưa merge.

    - Bỏ lệnh định dạng vô nghĩa trong FORMATTING_COMMANDS và tùy chọn vị trí float [htbp].
    - Đưa toán inline \\(...\\), \\begin{math}...\\end{math} về $...$.
    - Đưa toán khối (formula) về \\begin{equation}...\\end{equation}.
    - Gom khoảng trắng và đảm bảo tính idempotent.
    """
    if kind in ("document", "itemize", "item"):
        return ""
    text = raw
    text = _FLOAT_OPT_RE.sub(r"\1", text)
    text = _FORMATTING_WITH_ARG_RE.sub(" ", text)
    for cmd in FORMATTING_COMMANDS:
        text = re.sub(re.escape(cmd) + r"(?![a-zA-Z])", " ", text)

    text = _INLINE_PAREN_MATH_RE.sub(lambda m: f"${m.group(1).strip()}$", text)
    text = _INLINE_ENV_MATH_RE.sub(lambda m: f"${m.group(1).strip()}$", text)

    if kind == "formula":
        stripped = text.strip()
        for pattern in (_DISPLAY_DOLLAR_RE, _DISPLAY_BRACKET_RE, _DISPLAY_ENV_RE):
            m = pattern.match(stripped)
            if m is not None:
                inner = m.group(1).strip()
                text = f"\\begin{{equation}}{inner}\\end{{equation}}"
                break
        else:
            text = f"\\begin{{equation}}{stripped}\\end{{equation}}"

    text = re.sub(r"\s+", " ", text).strip()
    return text


def fallback_merge_bibtex(arxiv_id: str, sources: Sequence[BibSource]) -> BibResult:
    """Bộ hợp nhất BibTeX dự phòng tuân thủ hợp đồng [D] và C6 khi gói M2.4b chưa merge."""
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
    key_collisions = 0
    for _, group in sorted(groups.items()):
        max_ver = max(c[0] for c in group)
        base_key = min(c[1] for c in group if c[0] == max_ver)
        chosen_key = base_key
        if chosen_key in entries_by_key:
            key_collisions += 1
            suffix = 2
            while f"{base_key}__dup{suffix}" in entries_by_key:
                suffix += 1
            chosen_key = f"{base_key}__dup{suffix}"
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
                other = [chosen for (_, k), chosen in key_alias.items() if k == used]
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
            "key_collisions": key_collisions,
        },
        bibtex_version=FALLBACK_BIBTEX_VERSION,
    )
