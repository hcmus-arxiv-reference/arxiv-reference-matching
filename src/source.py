"""Content-aware, bounded source extraction and checksum-verified resume."""
from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
import zipfile

from .http_client import HttpClient, HttpStatusError
from .storage import key, write_json

MAX_EXTRACT_BYTES = 256 * 1024 * 1024
MAX_FILES = 10000


@dataclass(frozen=True)
class SourceResult:
    status: str
    path: Path
    checksum: str
    tex_files: tuple[str, ...]
    bib_files: tuple[str, ...]
    http_status: int = 200
    cached: bool = False


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name and ":" not in name


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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
    total_original = len(payload)
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
        total_original = total
    else:
        raw = payload.lstrip()
        if raw.startswith(b"%PDF-"):
            write_json(destination / "sizes.json", {"bytes_before": len(payload), "bytes_after": 0})
            return [], []
        if zipfile.is_zipfile(io.BytesIO(payload)):
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = archive.namelist()
                if len(names) <= MAX_FILES and "word/document.xml" in names:
                    write_json(destination / "sizes.json", {"bytes_before": sum(x.file_size for x in archive.infolist()), "bytes_after": 0})
                    return [], []
            raise ValueError("Unsupported ZIP source")
        if (not raw or b"\x00" in raw or re.search(br"<(?:!doctype\s+html|html)\b", raw[:4096], re.I)
                or not re.search(br"\\(?:documentclass|documentstyle|begin|input|def|section|bye)\b", raw)):
            raise ValueError("Unsupported source content (not verified TeX/PDF/docx)")
        (destination / "single.tex").write_bytes(payload)
        tex.append("single.tex")
    write_json(destination / "sizes.json", {"bytes_before": total_original, "bytes_after": sum((destination / n).stat().st_size for n in tex + bib)})
    return sorted(tex), sorted(bib)


def verified_source(path: Path) -> SourceResult | None:
    """Only accept new receipts whose exact TeX/BibTeX inventory still matches."""
    try:
        if path.is_symlink():
            return None
        receipt = json.loads((path / "source.json").read_text())
        if (receipt["format"] != 1 or receipt["status"] not in {"success", "non_tex"}
                or key(receipt["arxiv_id"]) != path.parent.name
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
            if not _safe_member(name):
                return None
            source = path / name
            if any(p.is_symlink() for p in (source, *source.parents)) or _digest(source) != digest:
                return None
        tex = tuple(sorted(n for n in files if n.lower().endswith(".tex")))
        bib = tuple(sorted(n for n in files if n.lower().endswith(".bib")))
        if (receipt["status"] == "success") != bool(tex):
            return None
        return SourceResult(receipt["status"], path, receipt["checksum"], tex, bib, cached=True)
    except (OSError, ValueError, KeyError, TypeError):
        return None


class ArxivSourceDownloader:
    def __init__(self, client: HttpClient, root: str | Path = "data/raw") -> None:
        self.client, self.root = client, Path(root)

    def download(self, arxiv_id: str, version: int) -> SourceResult:
        publication_key = key(arxiv_id)
        if type(version) is not int or version < 1:
            raise ValueError("Version must be a positive integer")
        path = self.root / publication_key / f"v{version}"
        cached = verified_source(path)
        if cached:
            return cached
        response = self.client.get(f"https://export.arxiv.org/src/{arxiv_id}v{version}")
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
                "bytes_downloaded": len(response.body),
                "files": {n: _digest(temporary / n) for n in tex + bib},
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
