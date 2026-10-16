"""Đo hiệu năng dùng chung: thời gian, RAM tối đa, dung lượng đĩa.

Đề chấm hiệu năng nên mọi module dùng cùng một bộ đo này.
Lưu ý: peak_rss_mb là mức RAM tối đa của CẢ TIẾN TRÌNH từ lúc khởi động,
không phải riêng khối lệnh được đo.
"""

from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

try:
    import resource
except ImportError:  # Windows
    resource = None


def peak_rss_mb() -> float | None:
    """RAM tối đa của tiến trình hiện tại (MB), hoặc None nếu không đo được."""
    if resource is None:
        return None
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS trả byte, Linux trả KB.
    return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024


def dir_size_mb(path: str | Path) -> float:
    """Tổng dung lượng các file trong thư mục (MB); path là file thì trả dung lượng file."""
    path = Path(path)
    if path.is_file():
        return path.stat().st_size / (1024 * 1024)
    total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return total / (1024 * 1024)


@dataclass
class Measurement:
    label: str
    seconds: float = 0.0
    peak_rss_mb: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@contextmanager
def measure(label: str) -> Iterator[Measurement]:
    """Đo thời gian chạy (và RAM tối đa) của một khối lệnh.

    with measure("parse 2508.02872") as m:
        ...
    print(m.seconds, m.peak_rss_mb)
    """
    result = Measurement(label=label)
    start = time.perf_counter()
    try:
        yield result
    finally:
        result.seconds = time.perf_counter() - start
        result.peak_rss_mb = peak_rss_mb()


def append_jsonl(path: str | Path, record: dict) -> None:
    """Ghi thêm một dòng JSON vào file log (dùng cho thống kê và báo cáo)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
