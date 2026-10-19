"""Atomic, member-scoped publication to a private Hugging Face dataset.

Uses parent_commit to reject concurrent changes rather than overwrite them.
https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api#create_commit
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile

from huggingface_hub import CommitOperationAdd, HfApi
from src.common.config import Settings
from src.common.hf_io import raw_prefix, table_path
from src.common.schema import from_records, read_table, write_table
from .source import verified_source
from .storage import key, write_json


class HuggingFacePublisher:
    """Upload only validated bundles; preserve other Publications and members."""
    def __init__(self, settings: Settings, *, api=None):
        settings.require_hf()
        table_path(settings.member, "papers")  # validate member before network
        self.settings = settings
        self.api = api if api is not None else HfApi(token=settings.hf_token)

    def _info(self):
        info = self.api.repo_info(repo_id=self.settings.hf_repo_id, repo_type="dataset",
                                  files_metadata=True)
        if info.private is not True:
            raise ValueError("Dataset must be private")
        if not info.sha:
            raise ValueError("Dataset has no revision; initialize it with scripts.check_hf")
        return info

    def _download(self, name: str, revision: str) -> Path:
        return Path(self.api.hf_hub_download(repo_id=self.settings.hf_repo_id, repo_type="dataset",
                    filename=name, revision=revision))

    def publish(self, bundles: list[dict], tables: dict[str, Path]) -> dict:
        """One commit contains source, metadata and merged tables for this batch.

        Errors leave local data ready for retry. Never delete remote files or
        change visibility; reject different source bytes at an existing Version.
        """
        if not bundles:
            return {"status": "nothing_ready", "publications": 0}
        if set(tables) - {"papers", "references"} or "papers" not in tables:
            raise ValueError("Only crawling tables may be published")
        ids = {b["publication"].arxiv_id for b in bundles}
        if len(ids) != len(bundles):
            raise ValueError("Duplicate publication bundle")
        local = {name: read_table(name, path).to_pylist() for name, path in tables.items()}
        if {r["arxiv_id"] for r in local["papers"]} != ids:
            raise ValueError("papers table does not match upload bundles")
        if any(r["arxiv_id"] not in ids for rows in local.values() for r in rows):
            raise ValueError("Table contains rows outside upload batch")
        files = {}
        for bundle in bundles:
            publication = bundle["publication"]
            metadata = json.loads(Path(bundle["metadata"]).read_text())
            if metadata != {"format": 1, "publication": asdict(publication)}:
                raise ValueError("Metadata does not match publication bundle")
            if len(bundle["sources"]) != publication.versions:
                raise ValueError("Incomplete Version coverage")
            for version, source in enumerate(bundle["sources"], 1):
                if source.path.parent.name != key(publication.arxiv_id) or source.path.name != f"v{version}":
                    raise ValueError("Source identity does not match publication bundle")
                verified = verified_source(source.path)
                if not verified or verified.checksum != source.checksum:
                    raise ValueError("Source changed since validation")
                prefix = raw_prefix(self.settings.member, publication.arxiv_id, version)
                for name in (*verified.tex_files, *verified.bib_files, "source.json"):
                    files[f"{prefix}/{name}"] = source.path / name
                files[f"{prefix}/metadata.json"] = bundle["metadata"]
                if bundle["references"] is not None:
                    files[f"{prefix}/references.json"] = bundle["references"]
                elif "references" in tables:
                    raise ValueError("Missing raw references for exported table")
        info = self._info()
        remote = {f.rfilename: f for f in info.siblings}
        # Raw Versions are immutable. A conflicting local corpus requires review.
        for name, path in files.items():
            if not name.endswith("/source.json"):
                continue
            prefix = name.rsplit("/", 1)[0] + "/"
            existing = {n for n in remote if n.startswith(prefix) and n.lower().endswith((".tex", ".bib"))}
            expected = {n for n in files if n.startswith(prefix) and n.lower().endswith((".tex", ".bib"))}
            if existing - expected:
                raise ValueError("Remote Version contains unexpected source files")
            if name in remote:
                old = json.loads(self._download(name, info.sha).read_text())
                new = json.loads(path.read_text())
                if old != new:
                    raise ValueError("Remote source receipt conflicts with local Version")
            elif existing:
                raise ValueError("Remote source has no verifiable receipt")
        with tempfile.TemporaryDirectory(prefix="arxiv-publish-") as temporary:
            for name, rows in local.items():
                remote_path = table_path(self.settings.member, name)
                previous = read_table(name, self._download(remote_path, info.sha)).to_pylist() if remote_path in remote else []
                merged = [r for r in previous if r["arxiv_id"] not in ids] + rows
                sort_key = lambda r: (r["arxiv_id"], r.get("ref_arxiv_id", ""))
                merged.sort(key=sort_key)
                if sorted(previous, key=sort_key) == merged and remote_path in remote:
                    continue
                path = Path(temporary) / f"{name}.parquet"
                write_table(from_records(merged, name), name, path)
                files[remote_path] = path
            operations = []
            for name, path in sorted(files.items()):
                if path.is_symlink():
                    raise ValueError("Upload file must not be a symlink")
                sibling = remote.get(name)
                if sibling:
                    content = path.read_bytes()
                    lfs = getattr(sibling, "lfs", None)
                    sha256 = getattr(lfs, "sha256", None)
                    blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
                    if sha256 == hashlib.sha256(content).hexdigest() or getattr(sibling, "blob_id", None) == blob:
                        continue
                    if not sha256 and not getattr(sibling, "blob_id", None):
                        if self._download(name, info.sha).read_bytes() == content:
                            continue
                operations.append(CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(path)))
            if not operations:
                result = {"status": "unchanged", "publications": len(ids), "commit": info.sha}
            else:
                if len(operations) > 25000:
                    raise ValueError("Too many files for one commit; use a smaller batch")
                # Recheck visibility; parent_commit also protects against lost updates.
                latest = self._info()
                if latest.sha != info.sha:
                    raise RuntimeError("Dataset changed during preparation; retry upload")
                commit = self.api.create_commit(repo_id=self.settings.hf_repo_id, repo_type="dataset",
                    operations=operations, parent_commit=info.sha, num_threads=1,
                    commit_message=f"crawl: {len(ids)} publications ({self.settings.member})")
                result = {"status": "uploaded", "publications": len(ids), "commit": commit.oid}
            # This is a receipt only. Every rerun still checks remote and local data.
            write_json(self.settings.data_dir / "manifests" / "last-upload.json",
                       {**result, "repo_id": self.settings.hf_repo_id, "member": self.settings.member,
                        "arxiv_ids": sorted(ids)})
            return result
