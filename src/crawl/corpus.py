"""Read and validate cached Publication data without modifying checkpoints.

The caller supplies a Manifest view. Constructing this reader never opens a
Manifest writer, acquires locks, repairs files, or contacts remote services.
File checks come from ``src.common.corpus.FileCorpus``; this module adds the
crawl-time check that each cache matches its Manifest record
(``docs/data-contract.md`` 3.2-3.3).
"""
import hashlib
from pathlib import Path
from typing import Protocol
from src.common.corpus import (FileCorpus, Publication, PublicationState, VersionState,
                               validate_publication, verified_source)
from src.common.references import CitationList
from .manifest import TaskRecord


class TaskLookup(Protocol):
    """Read-only view implemented by Manifest and report snapshots."""
    def get(self, arxiv_id: str, version: int | None, kind: str = "source") -> TaskRecord | None: ...


def _matches(record: TaskRecord | None, body: bytes) -> bool:
    return bool(record and record.status == "success"
                and hashlib.sha256(body).hexdigest() == record.checksum)


class CorpusReader:
    """Verify metadata, sources and references against the supplied task snapshot."""
    def __init__(self, data_dir: str | Path, manifest: TaskLookup,
                 source_root: str | Path | None = None):
        self.data_dir = Path(data_dir)
        self.manifest = manifest
        self.files = FileCorpus(self.data_dir, source_root)

    def metadata_path(self, arxiv_id: str) -> Path:
        return self.files.metadata_path(arxiv_id)

    def references_path(self, arxiv_id: str) -> Path:
        return self.files.references_path(arxiv_id)

    def load_publication(self, arxiv_id: str) -> Publication:
        body = self.metadata_path(arxiv_id).read_bytes()
        if not _matches(self.manifest.get(arxiv_id, None, "discovery"), body):
            raise ValueError("Unverified discovery cache")
        return self.files.read_publication(arxiv_id, body)

    validate_publication = staticmethod(validate_publication)

    def load_references(self, arxiv_id: str) -> CitationList:
        body = self.references_path(arxiv_id).read_bytes()
        if not _matches(self.manifest.get(arxiv_id, None, "references"), body):
            raise ValueError("Unverified references cache")
        return self.files.read_references(arxiv_id, body)

    def status(self, arxiv_id: str) -> PublicationState:
        """State of one Publication; a Version is verified only if receipt and Manifest agree.

        Never raises for missing or broken caches: incompleteness is part of the result.
        """
        try:
            publication = self.load_publication(arxiv_id)
        except (OSError, ValueError, KeyError, TypeError):
            publication = None
        versions = []
        for version in range(1, (publication.versions if publication else 0) + 1):
            task = self.manifest.get(arxiv_id, version, "source")
            source = verified_source(self.files.version_path(arxiv_id, version))
            verified = bool(source and task and task.status == source.status
                            and task.checksum == source.checksum)
            versions.append(VersionState(version, source, verified, task))
        try:
            references = self.load_references(arxiv_id)
        except (OSError, ValueError, KeyError, TypeError):
            references = None
        return PublicationState(arxiv_id, publication, tuple(versions), references)
