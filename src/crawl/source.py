"""Download and safely extract the text parts of an arXiv source archive."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile

from .http_client import HttpClient


@dataclass(frozen=True)
class SourceResult:
    status: str
    path: Path
    checksum: str
    tex_files: tuple[str, ...]
    bib_files: tuple[str, ...]


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def _copy_text(path: Path, target: Path) -> bool:
    if path.suffix.lower() not in {".tex", ".bib"}:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    return True


def extract_source(payload: bytes, destination: Path) -> tuple[list[str], list[str]]:
    """Extract only `.tex` and `.bib`; return relative paths by type."""
    destination.mkdir(parents=True, exist_ok=True)
    tex, bib = [], []
    with tempfile.TemporaryDirectory() as temp:
        temporary = Path(temp)
        archive = temporary / "source"
        archive.write_bytes(payload)
        if tarfile.is_tarfile(archive):
            with tarfile.open(archive, "r:*") as tar:
                members = [m for m in tar.getmembers() if m.isfile() and _safe_member(m.name)]
                tar.extractall(temporary / "unpacked", members=members)
            source_root = temporary / "unpacked"
            candidates = [p for p in source_root.rglob("*") if p.is_file()]
        else:
            try:
                raw = gzip.decompress(payload)
            except gzip.BadGzipFile:
                raw = payload
            source_root = temporary / "single.tex"
            source_root.write_bytes(raw)
            candidates = [source_root]
        for candidate in candidates:
            if candidate.suffix.lower() not in {".tex", ".bib"}:
                continue
            relative = candidate.relative_to(source_root if source_root.is_dir() else candidate.parent)
            target = destination / relative
            if _copy_text(candidate, target):
                (tex if candidate.suffix.lower() == ".tex" else bib).append(str(relative))
    return sorted(tex), sorted(bib)


class ArxivSourceDownloader:
    def __init__(self, client: HttpClient, root: str | Path = "data/raw") -> None:
        self.client = client
        self.root = Path(root)

    def download(self, arxiv_id: str, version: int) -> SourceResult:
        path = self.root / arxiv_id.replace("/", "-").replace(".", "-") / f"v{version}"
        marker = path / "source.ok"
        if marker.exists():
            return SourceResult("success", path, marker.read_text().strip(), tuple(), tuple())
        response = self.client.get(f"https://export.arxiv.org/src/{arxiv_id}v{version}")
        if response.status != 200:
            path.mkdir(parents=True, exist_ok=True)
            (path / "source.empty").write_text(f"HTTP {response.status}\n", encoding="utf-8")
            return SourceResult("unavailable", path, "", tuple(), tuple())
        checksum = hashlib.sha256(response.body).hexdigest()
        self.root.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix="arxiv-source-", dir=self.root.parent))
        try:
            tex, bib = extract_source(response.body, temporary)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                shutil.rmtree(path)
            temporary.rename(path)
            marker.write_text(checksum + "\n", encoding="utf-8")
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return SourceResult("success" if tex else "non_tex", path, checksum, tuple(tex), tuple(bib))
