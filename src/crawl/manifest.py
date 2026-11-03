"""Append-only task state, with recovery of interrupted final writes.

The pipeline holds a process lock for the data directory while using this log.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Iterable


@dataclass
class TaskRecord:
    arxiv_id: str
    version: int | None = None
    kind: str = "source"
    status: str = "pending"
    attempts: int = 0
    http_status: int | None = None
    local_path: str | None = None
    checksum: str | None = None
    error_reason: str | None = None
    updated_at: str | None = None

    @property
    def key(self) -> tuple[str, int | None, str]:
        return self.arxiv_id, self.version, self.kind


class Manifest:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.records: dict[tuple[str, int | None, str], TaskRecord] = {}
        if self.path.exists():
            data = self.path.read_bytes()
            lines = data.splitlines(keepends=True)
            offset = 0
            for index, line in enumerate(lines):
                try:
                    record = TaskRecord(**json.loads(line))
                except (ValueError, TypeError, UnicodeError):
                    if index != len(lines) - 1:
                        raise ValueError("Corrupt manifest before final line") from None
                    with self.path.open("r+b") as stream:
                        stream.truncate(offset)
                    break
                self.records[record.key] = record
                offset += len(line)
            else:
                if data and not data.endswith(b"\n"):
                    with self.path.open("ab") as stream:
                        stream.write(b"\n")

    def get(self, arxiv_id: str, version: int | None, kind: str = "source") -> TaskRecord | None:
        return self.records.get((arxiv_id, version, kind))

    def upsert(self, record: TaskRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.records[record.key] = record

    def pending(self, records: Iterable[TaskRecord]) -> list[TaskRecord]:
        return [r for r in records if (self.get(*r.key) or r).status not in {"success", "non_tex"}]
