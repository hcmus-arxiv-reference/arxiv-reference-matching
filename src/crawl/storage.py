"""Atomic local checkpoints and strict publication identifiers."""
from __future__ import annotations

from src.common.schema import publication_key, require_id  # require_id: compatibility re-export.
from src.common.json_io import write_json  # Compatibility re-export.


def key(arxiv_id: str) -> str:
    return publication_key(require_id(arxiv_id))
