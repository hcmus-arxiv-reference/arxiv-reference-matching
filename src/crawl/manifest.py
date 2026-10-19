"""Durable JSONL checkpoint for publication/version crawl tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
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
    """Upsert-only JSONL state; a truncated final line is ignored on resume."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.records: dict[tuple[str, int | None, str], TaskRecord] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    record = TaskRecord(**json.loads(line))
                except (json.JSONDecodeError, TypeError):
                    continue
                self.records[record.key] = record

    def get(self, arxiv_id: str, version: int | None, kind: str = "source") -> TaskRecord | None:
        return self.records.get((arxiv_id, version, kind))

    def upsert(self, record: TaskRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records[record.key] = record
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
            stream.flush()

    def pending(self, records: Iterable[TaskRecord]) -> list[TaskRecord]:
        return [record for record in records if (self.get(*record.key) or record).status != "success"]
