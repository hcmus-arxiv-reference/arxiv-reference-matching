"""Atomic local checkpoints and strict publication identifiers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

from src.common.schema import ARXIV_ID_PATTERN, publication_key


def require_id(arxiv_id: str) -> str:
    """Accept a base arXiv ID, never a URL, path traversal or version suffix."""
    if not isinstance(arxiv_id, str) or not re.fullmatch(ARXIV_ID_PATTERN, arxiv_id):
        raise ValueError(f"Invalid base arXiv ID: {arxiv_id!r}")
    return arxiv_id


def key(arxiv_id: str) -> str:
    return publication_key(require_id(arxiv_id))


def write_json(path: Path, value) -> None:
    """Replace a JSON document only after a flushed, complete write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".checkpoint-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
