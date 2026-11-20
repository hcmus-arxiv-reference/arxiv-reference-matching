"""Pick the manual-labelling Publications of one Range and write their label sheets (M3).

Implements ``docs/m3-gan-nhan.md`` sections 3 and 5:

* a Publication is eligible when its newest Version with TeX cites 20-60 BibTeX
  entries that exist in its ``.bib``/``\\bibitem`` and it has at least 10
  ``references`` rows;
* Publications are tried in a seeded random order (seed 20261120), so the choice is
  reproducible and nobody picks easy papers;
* each chosen Publication (spares only in selection-*.json) gets one sheet row per cited entry, with the raw entry
  text and the three closest candidates by title-token overlap as hints.

The labeller fills ``ref_arxiv_id`` (empty = no match) and ``confidence`` in the
sheet, then runs ``scripts/m3_check_labels.py`` before uploading.

Data sources (no network for the first):
  --data-dir data/crawl-smoke   local corpus in the ``src/crawl`` layout
  --hf-member hai               team HF dataset: tables/<member>/ and raw/<member>/<key>/
                                (only the raw folders of tried Publications are downloaded)

Example:
  python scripts/m3_label_sheet.py --hf-member hai --labeler bao --out labels-work
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.corpus import FileCorpus, verified_source  # noqa: E402
from src.common.schema import publication_key, require_id  # noqa: E402
from src.parse.source import assemble_source  # noqa: E402
from src.parse.structure import build_structure  # noqa: E402

SEED = 20261120
MIN_ENTRIES, MAX_ENTRIES, MIN_REFS = 20, 60, 10
LABEL_COLUMNS = ["arxiv_id", "citation_key", "ref_arxiv_id", "confidence", "labeler", "note"]
HINTS = 3
HINT_COLUMNS = ["entry"] + [f"{name}_{i}" for i in range(1, HINTS + 1) for name in ("hint", "score", "hint_title")]
ENTRY_CHARS = 400

_BIB_HEAD = re.compile(r"@\s*([A-Za-z]+)\s*([{(])\s*([^,\s{}()]+)\s*,")
_BIBITEM_HEAD = re.compile(r"\s*\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_ARXIV_IN_TEXT = re.compile(r"(\d{4}\.\d{4,5}|[a-z][a-z.\-]*/\d{7})(?:v\d+)?", re.I)
_WORD = re.compile(r"[^\W_]+")
_STOP = {"the", "and", "for", "with", "from", "via", "its", "are", "using", "into", "over", "towards", "toward", "based"}


# ---------------------------------------------------------------- entry text

def _closing(text: str, start: int, opening: str) -> int:
    """Index after the delimiter that closes ``text[start]`` (``{`` or ``(``); len(text) if unbalanced."""
    close = "}" if opening == "{" else ")"
    depth = 0
    for i in range(start, len(text)):
        char = text[i]
        if char == opening:
            depth += 1
        elif char == close:
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


def bib_entries(bib_files: dict[str, str]) -> dict[str, str]:
    """``key -> raw entry`` for every entry of a Version's ``.bib`` files; the first copy wins, as in BibTeX."""
    entries: dict[str, str] = {}
    for name in sorted(bib_files):
        text = bib_files[name]
        for match in _BIB_HEAD.finditer(text):
            if match[1].lower() in {"string", "comment", "preamble"} or match[3] in entries:
                continue
            entries[match[3]] = text[match.start():_closing(text, match.start(2), match[2])]
    return entries


def bibitem_entries(bibitems_raw: list[str]) -> dict[str, str]:
    """``key -> raw text`` of ``\\bibitem`` blocks; the first copy wins."""
    entries: dict[str, str] = {}
    for raw in bibitems_raw:
        match = _BIBITEM_HEAD.match(raw)
        if match and (key := match[1].strip()) and key not in entries:
            entries[key] = raw[match.end():]
    return entries


def _one_line(text: str, limit: int = ENTRY_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ---------------------------------------------------------------- candidates

def _tokens(text: str) -> set[str]:
    text = re.sub(r"\\[A-Za-z@]+|[{}$]", " ", text or "").casefold()
    return {w for w in _WORD.findall(text) if len(w) >= 3 and w not in _STOP}


def hints(entry: str, references: list[dict], k: int = HINTS) -> list[tuple[str, float, str]]:
    """Rank candidates for one entry: an arXiv ID written in the entry scores 1.0,
    otherwise the share of the candidate title's tokens found in the entry text.
    This is only a labelling hint, never a label."""
    written = {m[1].casefold() for m in _ARXIV_IN_TEXT.finditer(entry)}
    words = _tokens(entry)
    scored = []
    for ref in references:
        rid = ref["ref_arxiv_id"]
        title_words = _tokens(ref.get("ref_title") or "")
        if rid.casefold() in written:
            score = 1.0
        elif title_words:
            score = len(title_words & words) / len(title_words)
        else:
            score = 0.0
        scored.append((round(score, 2), rid, ref.get("ref_title") or ""))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [(rid, score, title) for score, rid, title in scored[:k] if score > 0]


# ---------------------------------------------------------------- one Publication

def newest_tex_version(publication_dir: Path) -> tuple[int, Path] | None:
    """Newest Version whose receipt is verified and has TeX (status ``success``)."""
    versions = []
    for path in publication_dir.glob("v*"):
        if path.is_dir() and path.name[1:].isdigit():
            versions.append((int(path.name[1:]), path))
    for number, path in sorted(versions, reverse=True):
        source = verified_source(path)
        if source is not None and source.status == "success":
            return number, path
    return None


def cited_entries(arxiv_id: str, publication_dir: Path) -> tuple[list[tuple[str, str]], dict]:
    """Cited entries of the newest TeX Version as ``(citation_key, raw text)``, in citation order.

    Keys come straight from the source, which is what C6 keeps for the newest
    Version (docs/data-contract.md 4.2). Cited keys with no entry are reported, not returned.
    """
    found = newest_tex_version(publication_dir)
    if found is None:
        return [], {"reason": "no_tex_version"}
    version, path = found
    bundle = assemble_source(path, require_receipt=True)
    if bundle.status not in {"ready", "needs_review"}:
        return [], {"reason": f"source_{bundle.status}", "version": version}
    try:
        _, bib = build_structure(bundle, arxiv_id, version, path)
    except ValueError as error:
        return [], {"reason": "structure_error", "version": version, "error": str(error)}
    texts = bib_entries(bib.bib_files)
    for key, text in bibitem_entries(bib.bibitems_raw).items():
        texts.setdefault(key, text)
    keys = list(dict.fromkeys(bib.cite_keys_used))
    rows = [(key, texts[key]) for key in keys if key in texts]
    return rows, {"version": version, "cited": len(keys), "with_entry": len(rows),
                  "missing_entry": len(keys) - len(rows), "missing_bib": list(bib.missing_bib)}


# ---------------------------------------------------------------- data sources

class LocalSource:
    """A local corpus in the ``src/crawl`` layout (``metadata/``, ``references/``, ``raw/``)."""

    def __init__(self, data_dir: Path) -> None:
        self.corpus = FileCorpus(data_dir)
        self.refs: dict[str, list[dict]] = {}
        for path in sorted((data_dir / "references").glob("*.json")):
            arxiv_id = json.loads(path.read_text())["arxiv_id"]
            try:
                self.refs[arxiv_id] = list(self.corpus.read_references(arxiv_id).references)
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def ids(self) -> list[str]:
        return sorted(self.refs)

    def references(self, arxiv_id: str) -> list[dict]:
        return self.refs.get(arxiv_id, [])

    def publication_dir(self, arxiv_id: str) -> Path | None:
        """Only complete Publications (files are the source of truth, ADR 0002)."""
        if not self.corpus.publication(arxiv_id).complete:
            return None
        return self.corpus.source_root / publication_key(arxiv_id)


class HfSource:
    """One member's Range on the team HF dataset; raw folders are fetched on demand."""

    def __init__(self, member: str, cache: Path) -> None:
        import pyarrow.parquet as pq

        from src.common.config import get_settings
        from src.common.hf_io import download_table

        self.member, self.cache = member, cache
        self.settings = get_settings()
        papers = pq.read_table(download_table(self.settings, member, "papers", cache), columns=["arxiv_id"])
        self.papers = set(papers.column("arxiv_id").to_pylist())
        table = pq.read_table(download_table(self.settings, member, "references", cache),
                              columns=["arxiv_id", "ref_arxiv_id", "ref_title"])
        self.refs: dict[str, list[dict]] = defaultdict(list)
        for row in table.to_pylist():
            self.refs[row["arxiv_id"]].append(row)

    def ids(self) -> list[str]:
        return sorted(self.papers)

    def references(self, arxiv_id: str) -> list[dict]:
        return self.refs.get(arxiv_id, [])

    def publication_dir(self, arxiv_id: str) -> Path | None:
        from src.common.hf_io import download_dir

        return download_dir(self.settings, f"raw/{self.member}/{publication_key(arxiv_id)}", self.cache)


# ---------------------------------------------------------------- selection

def select(source, count: int, spare: int, seed: int = SEED, exclude: set[str] = frozenset(),
           log=print) -> tuple[list[dict], list[dict]]:
    """Try Publications in seeded random order until ``count + spare`` are eligible.

    Only Publications with enough ``references`` rows are tried, so the HF source
    downloads raw folders for a handful of Publications, not the whole Range.
    """
    order = [i for i in source.ids() if len(source.references(i)) >= MIN_REFS]
    random.Random(seed).shuffle(order)
    # Exclude after shuffling, so an exclusion never reorders the rest: the spare moves up.
    order = [i for i in order if i not in exclude]
    chosen, tried = [], []
    for arxiv_id in order:
        if len(chosen) == count + spare:
            break
        directory = source.publication_dir(arxiv_id)
        if directory is None:
            tried.append({"arxiv_id": arxiv_id, "reason": "not_complete"})
            continue
        rows, info = cited_entries(arxiv_id, directory)
        info = {"arxiv_id": arxiv_id, "references": len(source.references(arxiv_id)), **info}
        n = len(rows)
        if "reason" not in info and not MIN_ENTRIES <= n <= MAX_ENTRIES:
            info["reason"] = f"entries_{'below' if n < MIN_ENTRIES else 'above'}_range"
        tried.append(info)
        if "reason" in info:
            continue
        chosen.append({**info, "rows": rows})
        log(f"  chọn {arxiv_id}: {n} entry, {info['references']} references")
    return chosen, tried


def write_sheet(path: Path, chosen: list[dict], references: dict[str, list[dict]], labeler: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS + HINT_COLUMNS)
        writer.writeheader()
        for pub in chosen:
            for key, text in pub["rows"]:
                row = {"arxiv_id": pub["arxiv_id"], "citation_key": key, "ref_arxiv_id": "",
                       "confidence": "", "labeler": labeler,
                       "note": "", "entry": _one_line(text)}
                for i, (rid, score, title) in enumerate(hints(text, references[pub["arxiv_id"]]), 1):
                    row.update({f"hint_{i}": rid, f"score_{i}": score, f"hint_title_{i}": _one_line(title, 160)})
                writer.writerow(row)
                count += 1
    return count


def write_candidates(directory: Path, arxiv_id: str, references: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{publication_key(arxiv_id)}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ref_arxiv_id", "ref_title", "ref_authors", "ref_submission_date"])
        for ref in sorted(references, key=lambda r: r["ref_arxiv_id"]):
            authors = ref.get("ref_authors") or []
            writer.writerow([ref["ref_arxiv_id"], ref.get("ref_title") or "",
                             "; ".join(authors) if isinstance(authors, list) else authors,
                             ref.get("ref_submission_date") or ""])


def main(argv: list[str] | None = None, source=None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    where = parser.add_mutually_exclusive_group(required=source is None)
    where.add_argument("--data-dir", type=Path, help="local corpus (src/crawl layout)")
    where.add_argument("--hf-member", help="member whose Range on the team HF dataset is used")
    parser.add_argument("--labeler", required=True, help="who labels: bao, lieu, minh, nghiem")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--spare", type=int, default=1)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--exclude", type=Path, help="text file of arXiv IDs not to choose (e.g. already labelled)")
    args = parser.parse_args(argv)

    if source is None:
        source = (LocalSource(args.data_dir) if args.data_dir
                  else HfSource(args.hf_member, args.out / ".hf-cache"))
    exclude = set()
    if args.exclude:
        exclude = {require_id(line.strip()) for line in args.exclude.read_text().splitlines() if line.strip()}

    chosen, tried = select(source, args.count, args.spare, args.seed, exclude)
    if len(chosen) < args.count:
        raise SystemExit(f"Chỉ tìm được {len(chosen)} bài đủ điều kiện, cần {args.count}. Xem selection.json.")
    # Spares are listed in selection.json, not put in the sheet. To replace a bad
    # Publication, rerun with it in --exclude: the seeded order then takes the spare.
    labelled, spares = chosen[:args.count], chosen[args.count:]
    refs = {pub["arxiv_id"]: source.references(pub["arxiv_id"]) for pub in labelled}
    range_name = args.hf_member or (args.data_dir.name if args.data_dir else "local")
    sheet = args.out / f"labels-{args.labeler}-{range_name}.csv"
    rows = write_sheet(sheet, labelled, refs, args.labeler)
    for arxiv_id, references in refs.items():
        write_candidates(args.out / "candidates", arxiv_id, references)
    summary = {
        "seed": args.seed, "criteria": {"entries": [MIN_ENTRIES, MAX_ENTRIES], "min_references": MIN_REFS},
        "labeler": args.labeler, "range": range_name, "sheet": sheet.name, "rows": rows,
        "chosen": [{k: v for k, v in p.items() if k != "rows"} for p in labelled],
        "spares": [{k: v for k, v in p.items() if k != "rows"} for p in spares],
        "tried": tried,
    }
    (args.out / f"selection-{args.labeler}-{range_name}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{sheet}: {rows} dòng, {len(labelled)} bài, {len(spares)} dự phòng ghi trong selection "
          f"(đã thử {len(tried)} bài). Danh sách ứng viên: {args.out / 'candidates'}/")
    return summary


if __name__ == "__main__":
    main()
