"""Cấu hình chung: đọc .env, Range arXiv của thành viên, User-Agent.

Mọi bí mật (token, API key) chỉ đọc từ biến môi trường hoặc file .env
(đã nằm trong .gitignore). KHÔNG hard-code vào code.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Mapping

try:  # python-dotenv là tùy chọn: thiếu thì chỉ dùng biến môi trường có sẵn
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

PROJECT_NAME = "arxiv-reference-matching"
PROJECT_VERSION = "0.1"

# Range mặc định của nhóm trưởng (tháng 2025-08, 2508.02872 đến 2508.07871).
# Mỗi thành viên đổi trong .env bằng ARXIV_RANGE_*.
DEFAULT_RANGE_PREFIX = "2508"
DEFAULT_RANGE_START = 2872
DEFAULT_RANGE_END = 7871


@dataclass(frozen=True)
class ArxivRange:
    """Dải arXiv ID dạng mới: <prefix>.<số 5 chữ số>, hai đầu đều tính."""

    prefix: str  # YYMM, ví dụ "2508"
    start: int
    end: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"\d{4}", self.prefix):
            raise ValueError(f"prefix phải có dạng YYMM, nhận {self.prefix!r}")
        if not (0 < self.start <= self.end <= 99999):
            raise ValueError(f"Range không hợp lệ: {self.start}..{self.end}")

    def ids(self) -> Iterator[str]:
        for n in range(self.start, self.end + 1):
            yield f"{self.prefix}.{n:05d}"

    def __len__(self) -> int:
        return self.end - self.start + 1

    def __contains__(self, arxiv_id: object) -> bool:
        if not isinstance(arxiv_id, str):
            return False
        m = re.fullmatch(rf"{self.prefix}\.(\d{{5}})", arxiv_id)
        return bool(m) and self.start <= int(m.group(1)) <= self.end


@dataclass(frozen=True)
class Settings:
    member: str | None  # tên thư mục của thành viên trên Hugging Face
    hf_token: str | None = field(repr=False)
    hf_repo_id: str | None
    s2_api_key: str | None = field(repr=False)
    contact_email: str | None
    data_dir: Path
    arxiv_range: ArxivRange

    def user_agent(self) -> str:
        """User-Agent mô tả rõ, bắt buộc khi tải từ arXiv."""
        if not self.contact_email:
            raise ValueError("Thiếu CONTACT_EMAIL trong .env (cần cho User-Agent).")
        return (
            f"{PROJECT_NAME}/{PROJECT_VERSION} "
            f"(HCMUS Introduction to Data Science course project; mailto:{self.contact_email})"
        )

    def s2_headers(self) -> dict[str, str]:
        """Header cho Semantic Scholar; thiếu key thì vẫn gọi được nhưng dễ bị 429."""
        headers = {"User-Agent": self.user_agent()}
        if self.s2_api_key:
            headers["x-api-key"] = self.s2_api_key
        return headers

    def require_hf(self) -> None:
        missing = [
            name
            for name, value in (
                ("HF_TOKEN", self.hf_token),
                ("HF_REPO_ID", self.hf_repo_id),
                ("MEMBER_NAME", self.member),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Thiếu biến môi trường: {', '.join(missing)}")


def load_env(path: str | Path | None = None) -> None:
    """Nạp file .env (nếu có) mà không ghi đè biến đã đặt sẵn."""
    if load_dotenv is not None:
        load_dotenv(path, override=False)


def get_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Đọc cấu hình. Truyền env (dict) để test; mặc định đọc os.environ sau khi nạp .env."""
    if env is None:
        load_env()
        env = os.environ

    def get(key: str) -> str | None:
        value = env.get(key)
        return value.strip() if value and value.strip() else None

    return Settings(
        member=get("MEMBER_NAME"),
        hf_token=get("HF_TOKEN"),
        hf_repo_id=get("HF_REPO_ID"),
        s2_api_key=get("S2_API_KEY"),
        contact_email=get("CONTACT_EMAIL"),
        data_dir=Path(get("DATA_DIR") or "data"),
        arxiv_range=ArxivRange(
            prefix=get("ARXIV_RANGE_PREFIX") or DEFAULT_RANGE_PREFIX,
            start=int(get("ARXIV_RANGE_START") or DEFAULT_RANGE_START),
            end=int(get("ARXIV_RANGE_END") or DEFAULT_RANGE_END),
        ),
    )
