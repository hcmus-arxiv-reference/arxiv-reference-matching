"""Content-aware, bounded source extraction and checksum-verified resume."""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
import zipfile

from src.common.corpus import SourceResult, verified_source  # verified_source: compatibility re-export.
from src.common.corpus import file_digest as _digest, safe_member as _safe_member
from src.common.metrics import append_jsonl

from .http_client import HttpClient, HttpStatusError
from .storage import key
from src.common.json_io import write_json

MAX_EXTRACT_BYTES = 256 * 1024 * 1024
MAX_FILES = 10000


def extract_source(payload: bytes, destination: Path) -> tuple[list[str], list[str]]:
    """Keep original TeX/BibTeX bytes; PDF/docx yield an empty Version.

    Unknown payloads and HTML fail rather than being recorded as missing TeX.
    Archive links and traversal paths are never extracted. Limits apply before
    allocation/copy, including gzip expansion and unselected tar members.
    """
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError("Source destination must not be a symlink")
    if payload.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
            payload = stream.read(MAX_EXTRACT_BYTES + 1)
    if len(payload) > MAX_EXTRACT_BYTES:
        raise ValueError("Source exceeds extraction limit")
    tex, bib = [], []
    try:
        archive = tarfile.open(fileobj=io.BytesIO(payload), mode="r:")
    except tarfile.ReadError:
        archive = None
    if archive is not None:
        with archive:
            total, count = 0, 0
            for member in archive:
                count += 1
                total += max(0, member.size)
                if count > MAX_FILES or total > MAX_EXTRACT_BYTES:
                    raise ValueError("Archive exceeds extraction limit")
                if not member.isfile() or not _safe_member(member.name):
                    continue
                relative = PurePosixPath(member.name)
                suffix = relative.suffix.lower()
                if suffix not in {".tex", ".bib"}:
                    continue
                target = destination.joinpath(*relative.parts)
                if any(p.is_symlink() for p in (target, *target.parents)):
                    raise ValueError("Symlink in extraction path")
                if target.exists():
                    raise ValueError("Duplicate archive destination")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                (tex if suffix == ".tex" else bib).append(relative.as_posix())
    else:
        raw = payload.lstrip()
        if raw.startswith(b"%PDF-"):
            return [], []
        if zipfile.is_zipfile(io.BytesIO(payload)):
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = archive.namelist()
                if len(names) <= MAX_FILES and "word/document.xml" in names:
                    return [], []
            raise ValueError("Unsupported ZIP source")
        if (not raw or b"\x00" in raw or re.search(br"<(?:!doctype\s+html|html)\b", raw[:4096], re.I)
                or not re.search(br"\\(?:documentclass|documentstyle|begin|input|def|section|bye)\b", raw)):
            raise ValueError("Unsupported source content (not verified TeX/PDF/docx)")
        (destination / "single.tex").write_bytes(payload)
        tex.append("single.tex")
    return sorted(tex), sorted(bib)


def content_bytes(payload: bytes) -> int:
    """Bytes of the source content before selecting ``.tex/.bib`` (image removal).

    Compression is undone first, so this is comparable with the bytes kept:
    a tar (gzip or plain) counts its regular files, a ZIP its members, a lone
    gzip file its decompressed size; PDF or plain TeX count the payload itself.
    The bytes downloaded are ``len(payload)`` and are reported separately.
    Call only on a payload that ``extract_source`` accepted.
    """
    if payload.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
            payload = stream.read(MAX_EXTRACT_BYTES + 1)
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            return sum(m.size for m in archive if m.isfile())
    except tarfile.ReadError:
        pass
    if zipfile.is_zipfile(io.BytesIO(payload)):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            return sum(i.file_size for i in archive.infolist() if not i.is_dir())
    return len(payload)


class ArxivSourceDownloader:
    """Download Versions resumably; HTTP progress goes to manifests/http-events.jsonl.

    Events live outside crawl.jsonl: that file is the Manifest and the validator
    accepts only task records there (decision 2026-11-02, replacing Q12(d)).
    """
    def __init__(self, client: HttpClient, root: str | Path = "data/raw",
                 events_path: str | Path | None = None) -> None:
        self.client, self.root = client, Path(root)
        self.events_path = Path(events_path) if events_path else self.root.parent / "manifests" / "http-events.jsonl"

    def _event_sink(self, arxiv_id: str, version: int):
        def emit(event: dict) -> None:
            append_jsonl(self.events_path, {
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "arxiv_id": arxiv_id, "version": version, **event})
        return emit

    def download(self, arxiv_id: str, version: int) -> SourceResult:
        publication_key = key(arxiv_id)
        if type(version) is not int or version < 1:
            raise ValueError("Version must be a positive integer")
        path = self.root / publication_key / f"v{version}"
        cached = verified_source(path)
        if cached:
            return cached
        response = self.client.get(f"https://export.arxiv.org/src/{arxiv_id}v{version}",
                                   resume=True, on_event=self._event_sink(arxiv_id, version))
        if response.status in {404, 410}:
            return SourceResult("unavailable", path, "", (), (), response.status)
        if response.status != 200:
            raise HttpStatusError(response.status, "arXiv source")
        content_type = next((v for k, v in response.headers.items() if k.lower() == "content-type"), "").lower()
        if "text/html" in content_type or "application/json" in content_type:
            raise ValueError("Source endpoint returned an error document")
        checksum = hashlib.sha256(response.body).hexdigest()
        path.parent.mkdir(parents=True, exist_ok=True)
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Symlink in source destination")
        temporary = Path(tempfile.mkdtemp(prefix=".source-", dir=path.parent))
        backup = path.with_name(f".{path.name}.previous")
        try:
            tex, bib = extract_source(response.body, temporary)
            status = "success" if tex else "non_tex"
            write_json(temporary / "source.json", {
                "format": 1, "arxiv_id": arxiv_id, "version": version,
                "status": status, "checksum": checksum,
                "files": {n: _digest(temporary / n) for n in tex + bib},
                # Size evaluation (M1 report): network bytes vs. content before selection.
                "downloaded_bytes": len(response.body),
                "content_bytes": content_bytes(response.body),
            })
            if backup.exists():
                # A prior process stopped after moving the old cache aside.
                if not path.exists():
                    backup.rename(path)
                else:
                    shutil.rmtree(backup)
            if path.exists():
                path.rename(backup)
            try:
                temporary.rename(path)
            except OSError:
                if backup.exists() and not path.exists():
                    backup.rename(path)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return SourceResult(status, path, checksum, tuple(tex), tuple(bib))
