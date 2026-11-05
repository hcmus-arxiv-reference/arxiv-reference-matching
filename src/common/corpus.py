"""Read a crawled corpus from files only: verified Versions and complete Publications.

Definitions: ``docs/data-contract.md`` sections 3.2 and 3.3 (terms in ``CONTEXT.md``).
This module never reads the Manifest, never writes, and never contacts remote
services, so the Parser and Matching can use it on a corpus copied from any
machine. The crawl-time check against the Manifest lives in
``src.crawl.corpus.CorpusReader``, built on top of this module.

Layout (local): ``<data_dir>/metadata/<key>.json``, ``<data_dir>/references/<key>.json``
and ``<data_dir>/raw/<key>/v<n>/`` with ``source.json`` and the ``.tex/.bib`` files.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from src.common.schema import from_records, publication_key, require_id

SOURCE_OK = frozenset({"success", "non_tex"})


@dataclass(frozen=True)
class Publication:
    """Metadata of one Publication from Discovery (one row of ``papers`` plus ``versions``)."""
    arxiv_id: str
    title: str | None
    authors: list[str]
    submission_date: str | None
    revised_dates: list[str]
    venue: str | None
    versions: int


@dataclass(frozen=True)
class SourceResult:
    """Outcome of Source fetch for one Version, or a verified cache of it."""
    status: str
    path: Path
    checksum: str
    tex_files: tuple[str, ...]
    bib_files: tuple[str, ...]
    http_status: int = 200
    cached: bool = False


def safe_member(name: str) -> bool:
    """Relative POSIX path that cannot leave its Version directory."""
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified_source(path: Path) -> SourceResult | None:
    """Return the Version at ``path`` if it is a verified Version, else None.

    Only accept receipts whose exact TeX/BibTeX inventory and checksums still match.
    """
    try:
        if path.is_symlink():
            return None
        receipt = json.loads((path / "source.json").read_text())
        if (receipt["format"] != 1 or receipt["status"] not in SOURCE_OK
                or publication_key(require_id(receipt["arxiv_id"])) != path.parent.name
                or type(receipt["version"]) is not int or receipt["version"] < 1
                or f"v{receipt['version']}" != path.name):
            return None
        files = receipt["files"]
        if not isinstance(files, dict):
            return None
        found = {p.relative_to(path).as_posix() for p in path.rglob("*")
                 if p.suffix.lower() in {".tex", ".bib"} and p.is_file()}
        if found != set(files):
            return None
        for name, digest in files.items():
            if not safe_member(name):
                return None
            source = path / name
            if any(p.is_symlink() for p in (source, *source.parents)) or file_digest(source) != digest:
                return None
        tex = tuple(sorted(n for n in files if n.lower().endswith(".tex")))
        bib = tuple(sorted(n for n in files if n.lower().endswith(".bib")))
        if (receipt["status"] == "success") != bool(tex):
            return None
        return SourceResult(receipt["status"], path, receipt["checksum"], tex, bib, cached=True)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def validate_publication(publication: Publication, arxiv_id: str) -> None:
    """Raise ValueError unless the metadata is valid for ``arxiv_id``."""
    if publication.arxiv_id != arxiv_id or type(publication.versions) is not int or publication.versions < 1:
        raise ValueError("Invalid discovery identity/version count")
    if len(publication.revised_dates) != publication.versions - 1:
        raise ValueError("Incomplete revision dates")
    row = asdict(publication)
    row.pop("versions")
    from_records([row], "papers")


def reference_rows(arxiv_id: str, raw_rows: list[dict]) -> list[dict]:
    """Map raw Semantic Scholar rows to ``references`` rows.

    Deduplicate arXiv-keyed candidates; never treat publicationDate as submission.
    """
    require_id(arxiv_id)
    rows = {}
    for raw in raw_rows:
        paper = raw.get("citedPaper") or {}
        external = paper.get("externalIds") or {}
        identifier = external.get("ArXiv")
        if not identifier:
            continue
        ref_id = require_id(re.sub(r"v\d+$", "", identifier))
        row = {"arxiv_id": arxiv_id, "ref_arxiv_id": ref_id,
               "ref_title": paper.get("title"),
               "ref_authors": [a["name"] for a in (paper.get("authors") or []) if a.get("name")],
               "ref_submission_date": None, "ref_s2_id": paper.get("paperId")}
        if ref_id in rows:
            # Preserve first supplied nonempty values, fill missing values only.
            row = {k: rows[ref_id][k] or v for k, v in row.items()}
        rows[ref_id] = row
    result = [rows[k] for k in sorted(rows)]
    from_records(result, "references")
    return result


@dataclass(frozen=True)
class VersionState:
    """One expected Version of a Publication.

    ``task`` is the Manifest record when the caller checked against a Manifest
    (crawl layer), otherwise None. ``verified`` is decided by that caller.
    """
    version: int
    source: SourceResult | None
    verified: bool
    task: Any = None

    @property
    def non_tex(self) -> bool:
        return self.verified and self.source is not None and self.source.status == "non_tex"


@dataclass(frozen=True)
class PublicationState:
    """How much of a Publication is usable. Never raised; incompleteness is data."""
    arxiv_id: str
    publication: Publication | None
    versions: tuple[VersionState, ...]
    references_ok: bool

    @property
    def expected_versions(self) -> int:
        return self.publication.versions if self.publication else 0

    @property
    def verified_versions(self) -> int:
        return sum(v.verified for v in self.versions)

    @property
    def non_tex_versions(self) -> int:
        return sum(v.non_tex for v in self.versions)

    @property
    def sources_complete(self) -> bool:
        """Valid metadata and every Version from v1 is a verified Version."""
        return (self.publication is not None and len(self.versions) == self.publication.versions
                and all(v.verified for v in self.versions))

    @property
    def complete(self) -> bool:
        """Complete Publication: ``sources_complete`` and valid references."""
        return self.sources_complete and self.references_ok

    def sources(self) -> list[SourceResult]:
        """Verified sources in Version order; only meaningful when ``sources_complete``."""
        return [v.source for v in self.versions if v.verified and v.source is not None]


class FileCorpus:
    """File-only view of a corpus directory (no Manifest, no writes)."""

    def __init__(self, data_dir: str | Path, source_root: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.source_root = Path(source_root) if source_root is not None else self.data_dir / "raw"

    def metadata_path(self, arxiv_id: str) -> Path:
        return self.data_dir / "metadata" / f"{publication_key(require_id(arxiv_id))}.json"

    def references_path(self, arxiv_id: str) -> Path:
        return self.data_dir / "references" / f"{publication_key(require_id(arxiv_id))}.json"

    def version_path(self, arxiv_id: str, version: int) -> Path:
        return self.source_root / publication_key(require_id(arxiv_id)) / f"v{version}"

    def read_publication(self, arxiv_id: str, body: bytes | None = None) -> Publication:
        """Parse and validate metadata; raise on any problem."""
        if body is None:
            body = self.metadata_path(arxiv_id).read_bytes()
        payload = json.loads(body)
        if payload["format"] != 1:
            raise ValueError("Old discovery cache must be refreshed")
        publication = Publication(**payload["publication"])
        validate_publication(publication, arxiv_id)
        return publication

    def read_references(self, arxiv_id: str, body: bytes | None = None) -> list[dict]:
        """Raw Semantic Scholar rows after checking identity and mapping; raise on any problem."""
        if body is None:
            body = self.references_path(arxiv_id).read_bytes()
        payload = json.loads(body)
        if payload["format"] != 1 or payload["arxiv_id"] != arxiv_id:
            raise ValueError("Wrong references cache")
        reference_rows(arxiv_id, payload["rows"])
        return payload["rows"]

    def publication(self, arxiv_id: str) -> PublicationState:
        """State of one Publication from files only."""
        require_id(arxiv_id)
        try:
            publication = self.read_publication(arxiv_id)
        except (OSError, ValueError, KeyError, TypeError):
            publication = None
        versions = []
        for version in range(1, (publication.versions if publication else 0) + 1):
            source = verified_source(self.version_path(arxiv_id, version))
            versions.append(VersionState(version, source, verified=source is not None))
        try:
            self.read_references(arxiv_id)
            references_ok = True
        except (OSError, ValueError, KeyError, TypeError):
            references_ok = False
        return PublicationState(arxiv_id, publication, tuple(versions), references_ok)
