"""Atomic JSON checkpoints shared by crawling and parsing tools."""
import json
import os
from pathlib import Path
import tempfile


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
