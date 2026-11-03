"""Read and validate cached Publication data without modifying checkpoints.

The caller supplies a Manifest view. Constructing this reader never opens a
Manifest writer, acquires locks, repairs files, or contacts remote services.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Protocol
from src.common.schema import from_records
from .discovery import Publication
from .manifest import TaskRecord
from .semantic_scholar import reference_rows
from .storage import key


class TaskLookup(Protocol):
    """Read-only view implemented by Manifest and report snapshots."""
    def get(self, arxiv_id: str, version: int | None, kind: str = "source") -> TaskRecord | None: ...


class CorpusReader:
    """Verify metadata and references against the supplied task snapshot."""
    def __init__(self, data_dir: str | Path, manifest: TaskLookup):
        self.data_dir = Path(data_dir)
        self.manifest = manifest

    def metadata_path(self, arxiv_id: str) -> Path:
        return self.data_dir / "metadata" / f"{key(arxiv_id)}.json"

    def references_path(self, arxiv_id: str) -> Path:
        return self.data_dir / "references" / f"{key(arxiv_id)}.json"

    def load_publication(self, arxiv_id: str) -> Publication:
        body = self.metadata_path(arxiv_id).read_bytes()
        record = self.manifest.get(arxiv_id, None, "discovery")
        if not record or record.status != "success" or hashlib.sha256(body).hexdigest() != record.checksum:
            raise ValueError("Unverified discovery cache")
        payload = json.loads(body)
        if payload["format"] != 1:
            raise ValueError("Old discovery cache must be refreshed")
        publication = Publication(**payload["publication"])
        self.validate_publication(publication, arxiv_id)
        return publication

    @staticmethod
    def validate_publication(publication: Publication, arxiv_id: str) -> None:
        if publication.arxiv_id != arxiv_id or type(publication.versions) is not int or publication.versions < 1:
            raise ValueError("Invalid discovery identity/version count")
        if len(publication.revised_dates) != publication.versions - 1:
            raise ValueError("Incomplete revision dates")
        row = asdict(publication)
        row.pop("versions")
        from_records([row], "papers")

    def load_references(self, arxiv_id: str) -> list[dict]:
        record = self.manifest.get(arxiv_id, None, "references")
        path = self.references_path(arxiv_id)
        body = path.read_bytes()
        if not record or record.status != "success" or hashlib.sha256(body).hexdigest() != record.checksum:
            raise ValueError("Unverified references cache")
        payload = json.loads(body)
        if payload["format"] != 1 or payload["arxiv_id"] != arxiv_id:
            raise ValueError("Wrong references cache")
        reference_rows(arxiv_id, payload["rows"])
        return payload["rows"]

