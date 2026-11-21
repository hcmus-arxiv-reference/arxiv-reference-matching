"""Build BibSource with reviewed roots and checksum-bound archive supplements.

The main receipt remains the authority for the original TeX/BibTeX inventory.
Supplement manifests bind additional bibliography files to that exact receipt.
See docs/data-contract.md section 3.4 for the approved input extension.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path, PurePosixPath
import re

from src.common.corpus import file_digest, safe_member
from src.common.schema import require_id, publication_key
from src.parse.source import SourceBundle, assemble_source
from src.parse.structure import build_structure
from src.parse.types import BibSource


def load_root_reviews(path: Path | None) -> dict[tuple[str, int], dict]:
    """Load explicit review decisions, rejecting duplicate or incomplete records."""
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if document["format"] != 1:
        raise ValueError("Unsupported root review format")
    reviews = {}
    for review in document["reviews"]:
        key = (require_id(review["arxiv_id"]), review["version"])
        if type(key[1]) is not int or key[1] < 1 or key in reviews:
            raise ValueError("Duplicate or invalid reviewed Version")
        if not safe_member(review["root_file"]) or not review["root_file"].lower().endswith(".tex"):
            raise ValueError("Reviewed root must be a relative TeX path")
        for field in ("receipt_sha256", "root_sha256"):
            if re.fullmatch(r"[0-9a-f]{64}", review[field]) is None:
                raise ValueError("Reviewed root requires SHA-256 provenance")
        if not review["reason"].strip():
            raise ValueError("Reviewed root requires a reason")
        reviews[key] = review
    return reviews


def build_bib_source(arxiv_id: str, version: int, directory: Path, *,
                     root_review: dict | None = None,
                     supplement_dir: Path | None = None) -> tuple[SourceBundle, BibSource | None, dict]:
    """Use the normal Source/Structure entry points, retaining failed Versions."""
    root_file = None
    if root_review is not None:
        root_file = root_review["root_file"]
        if (root_review["arxiv_id"], root_review["version"]) != (arxiv_id, version):
            raise ValueError("Root review belongs to another Version")
        if (file_digest(directory / "source.json") != root_review["receipt_sha256"]
                or file_digest(directory / root_file) != root_review["root_sha256"]):
            raise ValueError("Root review no longer matches the source receipt/files")
    bundle = assemble_source(directory, root_file=root_file, require_receipt=True)
    if bundle.status == "error":
        return bundle, None, {}
    if bundle.status in {"empty_non_tex", "empty_unavailable"}:
        return bundle, BibSource(arxiv_id, version), {}
    _, source = build_structure(bundle, arxiv_id, version, directory)
    if supplement_dir is None:
        return bundle, source, {}
    manifest = supplement_dir / publication_key(arxiv_id) / f"v{version}" / "manifest.json"
    if not manifest.exists():
        return bundle, source, {}
    source, provenance = supplement_bibliography(source, bundle, directory, manifest)
    return bundle, source, provenance


def supplement_bibliography(source: BibSource, bundle: SourceBundle,
                            directory: Path, manifest_path: Path) -> tuple[BibSource, dict]:
    """Read only declared bibliography resources or the root's compiled .bbl.

    A bibliography command reads the root job's .bbl when its .bib is absent.
    Explicit input/include .bbl paths retain the same root-relative resolution.
    Unreferenced .bib files from the archive remain outside the compilation path.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest["format"], manifest["arxiv_id"], manifest["version"]) != (1, source.arxiv_id, source.version):
        raise ValueError("Bibliography supplement belongs to another Version")
    if manifest["receipt_sha256"] != file_digest(directory / "source.json"):
        raise ValueError("Bibliography supplement does not match the original receipt")
    if (not isinstance(manifest["files"], dict)
            or re.fullmatch(r"[0-9a-f]{64}", manifest["archive_sha256"]) is None):
        raise ValueError("Invalid bibliography supplement manifest")
    contents = {}
    for name, digest in manifest["files"].items():
        if not safe_member(name) or PurePosixPath(name).suffix.lower() not in {".bib", ".bbl"}:
            raise ValueError("Unsafe bibliography supplement path")
        path = manifest_path.parent / "files" / name
        if any(parent.is_symlink() for parent in (path, *path.parents)) or file_digest(path) != digest:
            raise ValueError("Bibliography supplement file checksum differs")
        raw = path.read_bytes()
        try:
            contents[name] = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            contents[name] = raw.decode("latin-1")

    source = replace(source, bib_files=dict(source.bib_files), missing_bib=list(source.missing_bib),
                     bibitems_raw=list(source.bibitems_raw))
    root = PurePosixPath(bundle.root or "main.tex")
    used = set()

    def locate(name):
        if not safe_member(name):
            return None
        return next((candidate for candidate in ((root.parent / name).as_posix(), name)
                     if candidate in contents), None)

    for name in list(source.missing_bib):
        selected = locate(name)
        if selected is not None:
            source.bib_files[selected] = contents[selected]
            source.missing_bib.remove(name)
            used.add(selected)

    bbl_paths = [item["argument"] for item in bundle.includes if item["status"] == "missing_bbl"]
    if source.bib_files or source.missing_bib:
        bbl_paths.append(root.stem + ".bbl")
    for name in bbl_paths:
        selected = locate(name)
        if selected is None or selected in used:
            continue
        # Reuse Structure's bibliography reader, without adding bibliography to
        # the hierarchy or treating citations within entries as document cites.
        wrapper = SourceBundle(status="ready", text="\\begin{document}\n" + contents[selected] + "\n\\end{document}")
        _, extra = build_structure(wrapper, source.arxiv_id, source.version)
        source.bibitems_raw.extend(item for item in extra.bibitems_raw if item not in source.bibitems_raw)
        used.add(selected)
    provenance = {"archive_sha256": manifest["archive_sha256"],
                  "receipt_sha256": manifest["receipt_sha256"],
                  "files": {name: manifest["files"][name] for name in sorted(used)}}
    return source, provenance
