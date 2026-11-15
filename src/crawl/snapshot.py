"""Discovery from the arXiv metadata snapshot instead of the arXiv API.

Source: Kaggle dataset ``Cornell-University/arxiv`` (file
``arxiv-metadata-oai-snapshot.json``, one JSON object per line, refreshed by
arXiv about weekly), https://www.kaggle.com/datasets/Cornell-University/arxiv.
Each line has ``id``, ``title``, ``authors_parsed`` ([last, first, suffix]),
``journal-ref`` and ``versions`` ([{"version": "v1", "created": RFC 2822 date}]).

Why (Colab trial 15/11/2026): ``/api/query`` answered 43 of 55 Discovery
queries with 429 while ``/src/`` downloads ran at 7 MB/s. Reading metadata and
Version dates from the snapshot removes about 973 API requests per Range
(100 batches + per-Version date lookups); only IDs missing from the snapshot
still go to the API.

The extract (``extract_snapshot``) keeps only the requested IDs, so each crawl
reads a few MB instead of the 4–5 GB snapshot. Its header records the source
file's sha256 and the latest ``update_date``: that date is the Version
coverage cut-off of the crawl (a Version added later is not in the snapshot).
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata
import zipfile
from typing import IO, Iterable, Iterator

from src.common.corpus import Publication, validate_publication
from .storage import require_id

SNAPSHOT_MEMBER = "arxiv-metadata-oai-snapshot.json"

# TeX accent command -> Unicode combining mark (authors in older records use TeX).
_ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303",
            "=": "\u0304", ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b",
            "c": "\u0327", "k": "\u0328", "r": "\u030a"}
_LETTERS = {"o": "ø", "O": "Ø", "ss": "ß", "l": "ł", "L": "Ł", "aa": "å", "AA": "Å",
            "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "i": "ı", "j": "ȷ"}
_ACCENT_RE = re.compile(r"""\\([`'^"~=.]|[uvHckr](?![a-zA-Z]))\s*(?:\{\s*(\\?[a-zA-Z])\s*\}|(\\?[a-zA-Z]))""")
_LETTER_RE = re.compile(r"\\(ss|aa|AA|ae|AE|oe|OE|[oOlLij])(?![a-zA-Z])")


def detex(text: str) -> str:
    """Decode common TeX accents (``\\'e``, ``{\\"o}``, ``\\c{c}``, ``{\\o}``) to NFC Unicode."""
    def accent(match: re.Match) -> str:
        base = match[2] or match[3]
        if base.startswith("\\"):
            base = _LETTERS.get(base[1:], base[1:])
        return base + _ACCENTS[match[1]]
    text = _ACCENT_RE.sub(accent, text)
    text = _LETTER_RE.sub(lambda m: _LETTERS[m[1]], text)
    text = re.sub(r"(?<!\\)[{}]", "", text)
    return unicodedata.normalize("NFC", " ".join(text.split()))


_GREEK = {name: chr(code) for name, code in (
    ("alpha", 0x3B1), ("beta", 0x3B2), ("gamma", 0x3B3), ("delta", 0x3B4), ("epsilon", 0x3B5),
    ("zeta", 0x3B6), ("eta", 0x3B7), ("theta", 0x3B8), ("iota", 0x3B9), ("kappa", 0x3BA),
    ("lambda", 0x3BB), ("mu", 0x3BC), ("nu", 0x3BD), ("xi", 0x3BE), ("pi", 0x3C0), ("rho", 0x3C1),
    ("sigma", 0x3C3), ("tau", 0x3C4), ("upsilon", 0x3C5), ("phi", 0x3C6), ("chi", 0x3C7),
    ("psi", 0x3C8), ("omega", 0x3C9), ("Gamma", 0x393), ("Delta", 0x394), ("Theta", 0x398),
    ("Lambda", 0x39B), ("Xi", 0x39E), ("Pi", 0x3A0), ("Sigma", 0x3A3), ("Upsilon", 0x3A5),
    ("Phi", 0x3A6), ("Psi", 0x3A8), ("Omega", 0x3A9))}   # the API keeps \\varphi etc. as TeX
_GREEK_NAMES = "|".join(sorted(_GREEK, key=len, reverse=True))
# "{\\mu}" -> "μ" (the braces go); "\\mu x" -> "μx" (one following space goes), as the API shows.
_GREEK_RE = re.compile(r"\{\\(%s)\}|\\(%s)(?![a-zA-Z]) ?" % (_GREEK_NAMES, _GREEK_NAMES))


def tex_to_unicode(text: str | None) -> str | None:
    """Accents and Greek letters to Unicode, other TeX (math, braces) kept, like the arXiv API.

    The API shows ``$\\alpha$-Decay`` as ``$α$-Decay`` and ``Fr\\'echet`` as ``Fréchet``;
    the snapshot keeps the TeX. Compared on Range Bảo, 15/11/2026.
    """
    if text is None:
        return None
    def accent(match: re.Match) -> str:
        base = match[2] or match[3]
        if base.startswith("\\"):
            base = _LETTERS.get(base[1:], base[1:])
        return base + _ACCENTS[match[1]]
    text = _ACCENT_RE.sub(accent, text)
    text = _GREEK_RE.sub(lambda m: _GREEK[m[1] or m[2]], text)
    text = _LETTER_RE.sub(lambda m: _LETTERS[m[1]], text)
    return unicodedata.normalize("NFC", " ".join(text.split()))


def _iso(rfc2822: str) -> str:
    return parsedate_to_datetime(rfc2822).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None


def parse_record(record: dict) -> Publication:
    """One snapshot line -> Publication in the same format as the API Discovery."""
    arxiv_id = require_id(record["id"])
    versions = record["versions"]
    numbers = [int(v["version"].lstrip("v")) for v in versions]
    if not numbers or numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"{arxiv_id}: Version list not v1..vN")
    dates = [_iso(v["created"]) for v in versions]
    authors = []
    for parts in record.get("authors_parsed") or []:
        last, first, suffix = (list(parts) + ["", "", ""])[:3]
        name = detex(" ".join(p for p in (first, last, suffix) if p))
        if name:
            authors.append(name)
    publication = Publication(arxiv_id, tex_to_unicode(_clean(record.get("title"))), authors, dates[0],
                              dates[1:], tex_to_unicode(_clean(record.get("journal-ref"))), len(dates))
    validate_publication(publication, arxiv_id)
    return publication


def _open_lines(path: Path) -> IO[str]:
    """Text stream of the snapshot: Kaggle's .zip, a .gz, or the plain .json."""
    if path.suffix == ".zip":
        archive = zipfile.ZipFile(path)
        name = SNAPSHOT_MEMBER if SNAPSHOT_MEMBER in archive.namelist() else archive.namelist()[0]
        return io.TextIOWrapper(archive.open(name), encoding="utf-8")
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_records(path: Path, wanted: set[str]) -> Iterator[dict]:
    """Snapshot lines whose ``id`` is in ``wanted``; the ID is checked before parsing JSON."""
    with _open_lines(path) as lines:
        for line in lines:
            # "id" is the first key of every line; skip the JSON parse for the other ~2.8 M lines.
            head = line[:40]
            start = head.find('"id"')
            if start < 0:
                continue
            quote = head.find('"', head.find(":", start) + 1)
            identifier = head[quote + 1:head.find('"', quote + 1)]
            if identifier in wanted:
                yield json.loads(line)


def extract_snapshot(snapshot: Path, ids: Iterable[str], out: Path) -> dict:
    """Write the Publications of ``ids`` found in ``snapshot`` to ``out`` (.json or .json.gz)."""
    wanted = {require_id(i) for i in ids}
    publications, invalid, latest = {}, {}, ""
    for record in iter_records(snapshot, wanted):
        latest = max(latest, record.get("update_date") or "")
        try:
            publications[record["id"]] = asdict(parse_record(record))
        except (ValueError, KeyError, TypeError) as error:
            invalid[record["id"]] = str(error)
    header = {"source": snapshot.name, "source_sha256": _sha256(snapshot),
              "latest_update_date": latest or None,
              "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "requested": len(wanted), "found": len(publications),
              "missing": len(wanted) - len(publications) - len(invalid), "invalid": invalid}
    body = json.dumps({"format": 1, "snapshot": header, "publications": publications},
                      ensure_ascii=False, sort_keys=True).encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(body, mtime=0) if out.suffix == ".gz" else body)
    return header


def load_snapshot(path: Path) -> tuple[dict, dict[str, Publication]]:
    """Header and Publications of an extract written by ``extract_snapshot``."""
    raw = path.read_bytes()
    data = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    if data.get("format") != 1:
        raise ValueError("Unknown snapshot extract format")
    return data["snapshot"], {k: Publication(**v) for k, v in data["publications"].items()}


class SnapshotDiscovery:
    """Discovery từ snapshot metadata: Publication có trong extract thì không gọi API.

    ID không có trong extract đi qua ``fallback`` (Discovery theo lô qua API), kể cả
    prefetch theo lô của Engine (``batch_size``, ``prefetch``).
    """

    def __init__(self, publications: dict[str, Publication], fallback) -> None:
        self.publications, self.fallback = publications, fallback
        self.hits = self.misses = 0

    @property
    def batch_size(self) -> int:
        return getattr(self.fallback, "batch_size", 0)

    def prefetch(self, identifiers) -> None:
        missing = [i for i in identifiers if i not in self.publications]
        if missing and hasattr(self.fallback, "prefetch"):
            self.fallback.prefetch(missing)

    def discover(self, arxiv_id: str) -> Publication:
        publication = self.publications.get(require_id(arxiv_id))
        if publication is not None:
            self.hits += 1
            return publication
        self.misses += 1
        return self.fallback.discover(arxiv_id)
