"""Atomic local checkpoints and strict publication identifiers."""
from __future__ import annotations

import re

from src.common.schema import ARXIV_ID_PATTERN, publication_key
from src.common.json_io import write_json  # Compatibility re-export.


def require_id(arxiv_id: str) -> str:
    """Accept a base arXiv ID, never a URL, path traversal or version suffix."""
    if not isinstance(arxiv_id, str) or not re.fullmatch(ARXIV_ID_PATTERN, arxiv_id):
        raise ValueError(f"Invalid base arXiv ID: {arxiv_id!r}")
    return arxiv_id


def key(arxiv_id: str) -> str:
    return publication_key(require_id(arxiv_id))
