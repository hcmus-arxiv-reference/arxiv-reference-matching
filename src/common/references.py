"""The S2 citation list of one Publication and the References derived from it.

Terms (``CONTEXT.md``): the *S2 citation list* is every ``citedPaper`` row that
Semantic Scholar returns for a Publication, including rows without an arXiv ID;
the cache keeps it whole (Crawling statement, ADR 0002). A *Reference* is a row
with an arXiv ID, deduplicated by ``ref_arxiv_id``, as written to the
``references`` table. Every count of either set is defined here once.

Field source: https://api.semanticscholar.org/graph/v1/swagger.json
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from src.common.schema import from_records, is_iso_date, require_id


def _cited(raw: dict) -> dict:
    return raw.get("citedPaper") or {}


def _arxiv_id(raw: dict) -> str | None:
    return (_cited(raw).get("externalIds") or {}).get("ArXiv") or None


def _publication_date(paper: dict) -> str | None:
    value = paper.get("publicationDate")
    return value if isinstance(value, str) and is_iso_date(value) else None


def reference_rows(arxiv_id: str, raw_rows: list[dict]) -> list[dict]:
    """Map raw S2 rows to ``references`` rows.

    Deduplicate arXiv-keyed candidates. ``ref_submission_date`` is the S2
    ``publicationDate`` (allowed by the instructor, 2026-11-10); a missing or
    non-ISO value stays null instead of failing the export.
    """
    require_id(arxiv_id)
    rows = {}
    for raw in raw_rows:
        identifier = _arxiv_id(raw)
        if not identifier:
            continue
        paper = _cited(raw)
        ref_id = require_id(re.sub(r"v\d+$", "", identifier))
        row = {"arxiv_id": arxiv_id, "ref_arxiv_id": ref_id,
               "ref_title": paper.get("title"),
               "ref_authors": [a["name"] for a in (paper.get("authors") or []) if a.get("name")],
               "ref_submission_date": _publication_date(paper), "ref_s2_id": paper.get("paperId")}
        if ref_id in rows:
            # Preserve first supplied nonempty values, fill missing values only.
            row = {k: rows[ref_id][k] or v for k, v in row.items()}
        rows[ref_id] = row
    result = [rows[k] for k in sorted(rows)]
    from_records(result, "references")
    return result


@dataclass(frozen=True)
class CitationList:
    """Validated S2 citation list of one Publication. Build it with ``from_raw``."""
    arxiv_id: str
    raw: tuple[dict, ...]
    references: tuple[dict, ...] = field(repr=False)

    @classmethod
    def from_raw(cls, arxiv_id: str, raw_rows: list[dict]) -> CitationList:
        """Validate once; raise ValueError if the rows cannot become ``references`` rows."""
        if not isinstance(raw_rows, list) or any(not isinstance(r, dict) for r in raw_rows):
            raise ValueError("S2 citation list must be a list of objects")
        return cls(arxiv_id, tuple(raw_rows), tuple(reference_rows(arxiv_id, raw_rows)))

    @property
    def total(self) -> int:
        """Every raw row, with or without an arXiv ID."""
        return len(self.raw)

    @property
    def with_arxiv_id(self) -> int:
        """Raw rows with ``citedPaper.externalIds.ArXiv``, counted **before** deduplication."""
        return sum(_arxiv_id(r) is not None for r in self.raw)

    @property
    def legacy_ids(self) -> int:
        """References whose ID has the old form, such as ``hep-th/9901001``."""
        return sum("/" in r["ref_arxiv_id"] for r in self.references)
