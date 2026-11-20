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
import time

from huggingface_hub import CommitOperationAdd, HfApi
from src.common.config import Settings
from src.common.hf_io import raw_prefix, table_path
from src.common.schema import from_records, read_table, write_table
from .source import verified_source
from .export import PublicationBundle
from .storage import key
from src.common.json_io import write_json


class RemoteChanged(RuntimeError):
    """The dataset moved on (another member committed) while a batch was being prepared."""


class HuggingFacePublisher:
    """Upload only validated bundles; preserve other Publications and members."""
    ATTEMPTS = 4   # members upload to one dataset at the same time; a moved head is retried

    def __init__(self, settings: Settings, *, api=None, sleep=time.sleep):
        settings.require_hf()
        table_path(settings.member, "papers")  # validate member before network
        self.settings = settings
        self.api = api if api is not None else HfApi(token=settings.hf_token)
        self.sleep = sleep

    def _info(self):
        info = self.api.repo_info(repo_id=self.settings.hf_repo_id, repo_type="dataset",
                                  files_metadata=True)
        if info.private is not True:
            raise ValueError("Dataset must be private")
        if not info.sha:
            raise ValueError("Dataset has no revision; initialize it with scripts.check_hf")
        return info

    def validate_destination(self) -> None:
        """Fail early unless the configured destination is an initialized private dataset."""
        self._info()

    def _download(self, name: str, revision: str) -> Path:
        return Path(self.api.hf_hub_download(repo_id=self.settings.hf_repo_id, repo_type="dataset",
                    filename=name, revision=revision))

    def _remote(self, names, prefixes, revision: str) -> dict:
        """Remote files among exact ``names`` plus every file under ``prefixes``.

        Never use ``repo_info(...).siblings`` for this: the Hub lists at most
        100,000 siblings. Past that, the member's tables were not seen, so each
        batch replaced them instead of merging (tables/lieu kept 250 of 4,975
        rows, 20/11/2026). Exact path queries have no such cap.
        """
        remote, names = {}, sorted(set(names))
        for start in range(0, len(names), 200):
            for item in self.api.get_paths_info(repo_id=self.settings.hf_repo_id, repo_type="dataset",
                                                paths=names[start:start + 200], revision=revision):
                if hasattr(item, "blob_id"):          # a file, not a folder
                    remote[item.path] = item
        for prefix in sorted(set(prefixes)):
            for item in self.api.list_repo_tree(repo_id=self.settings.hf_repo_id, repo_type="dataset",
                                                path_in_repo=prefix, recursive=True, revision=revision):
                if hasattr(item, "blob_id"):
                    remote[item.path] = item
        return remote

    def publish(self, bundles: list[PublicationBundle], tables: dict[str, Path]) -> dict:
        """Publish one batch; retry when another member committed in the meantime.

        Each attempt re-reads the remote tables at the new head, so a retry merges
        on top of the other commit instead of overwriting it.
        """
        for attempt in range(1, self.ATTEMPTS + 1):
            try:
                return self._publish_once(bundles, tables)
            except RemoteChanged:
                if attempt == self.ATTEMPTS:
                    raise
                self.sleep(5 * attempt)
        raise AssertionError("unreachable")

    def _publish_once(self, bundles: list[PublicationBundle], tables: dict[str, Path]) -> dict:
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
        wanted = [*files, *(table_path(self.settings.member, name) for name in local)]
        remote = self._remote(wanted, [], info.sha)
        # A Version already on the Hub: list all of its files, to catch unexpected ones.
        remote.update(self._remote([], [n.rsplit("/", 1)[0] for n in files
                                        if n.endswith("/source.json") and n in remote], info.sha))
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
                    raise RemoteChanged("Dataset changed during preparation; retry upload")
                try:
                    commit = self.api.create_commit(repo_id=self.settings.hf_repo_id, repo_type="dataset",
                        operations=operations, parent_commit=info.sha, num_threads=1,
                        commit_message=f"crawl: {len(ids)} publications ({self.settings.member})")
                except Exception as error:
                    # The Hub answers 412 when parent_commit is no longer the head.
                    if getattr(getattr(error, "response", None), "status_code", None) == 412:
                        raise RemoteChanged("Dataset changed before commit; retry upload") from error
                    raise
                result = {"status": "uploaded", "publications": len(ids), "commit": commit.oid}
            # This is a receipt only. Every rerun still checks remote and local data.
            write_json(self.settings.data_dir / "manifests" / "last-upload.json",
                       {**result, "repo_id": self.settings.hf_repo_id, "member": self.settings.member,
                        "arxiv_ids": sorted(ids)})
            return result
