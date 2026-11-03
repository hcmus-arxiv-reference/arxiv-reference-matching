"""Cấu hình chung: đọc .env, Range arXiv của thành viên, User-Agent.

Mọi bí mật (token, API key) chỉ đọc từ biến môi trường hoặc file .env
(đã nằm trong .gitignore). KHÔNG hard-code vào code.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from itertools import chain
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
# Range của cả nhóm, mỗi thành viên có thể gồm nhiều Đoạn (qua ranh giới tháng).
DEFAULT_RANGES_PATH = Path(__file__).resolve().parents[2] / "configs" / "ranges.toml"


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
class SegmentedRange:
    """Range gồm một hoặc nhiều Đoạn ArxivRange không chồng nhau, theo thứ tự khai báo."""

    segments: tuple[ArxivRange, ...]

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("Range cần ít nhất một Đoạn")
        for i, a in enumerate(self.segments):
            for b in self.segments[i + 1:]:
                if overlaps(a, b):
                    raise ValueError(f"Đoạn chồng nhau: {a} và {b}")

    def ids(self) -> Iterator[str]:
        return chain.from_iterable(segment.ids() for segment in self.segments)

    def __len__(self) -> int:
        return sum(len(segment) for segment in self.segments)

    def __contains__(self, arxiv_id: object) -> bool:
        return any(arxiv_id in segment for segment in self.segments)


def overlaps(a: ArxivRange, b: ArxivRange) -> bool:
    return a.prefix == b.prefix and a.start <= b.end and b.start <= a.end


@dataclass(frozen=True)
class MemberRange:
    """Range được giao của một thành viên trong configs/ranges.toml."""

    name: str
    github: str
    range: SegmentedRange
    verified: bool
    note: str | None = None


def load_ranges(path: str | Path | None = None) -> dict[str, MemberRange]:
    """Đọc configs/ranges.toml; báo lỗi nếu trùng tên, chồng Đoạn hoặc sai số ID.

    Mỗi thành viên đúng `ids_per_member` ID; Đoạn của hai thành viên không được
    chồng nhau. Thứ tự trả về theo thứ tự khai báo trong file.
    """
    data = tomllib.loads(Path(path or DEFAULT_RANGES_PATH).read_text(encoding="utf-8"))
    size = data.get("ids_per_member")
    if type(size) is not int or size < 1:
        raise ValueError("ids_per_member phải là số nguyên dương")
    members: dict[str, MemberRange] = {}
    for entry in data.get("members", []):
        name, github, verified = entry.get("name"), entry.get("github"), entry.get("verified")
        if not isinstance(name, str) or not isinstance(github, str) or type(verified) is not bool:
            raise ValueError(f"Thành viên thiếu name/github/verified: {entry!r}")
        if name in members or any(m.github == github for m in members.values()):
            raise ValueError(f"Trùng thành viên {name}/{github}")
        segments = []
        for seg in entry.get("segments", []):
            if (not isinstance(seg.get("prefix"), str) or type(seg.get("start")) is not int
                    or type(seg.get("end")) is not int):
                raise ValueError(f"{name}: Đoạn cần prefix (chuỗi), start, end (số nguyên)")
            segments.append(ArxivRange(seg["prefix"], seg["start"], seg["end"]))
        member = MemberRange(name, github, SegmentedRange(tuple(segments)), verified, entry.get("note"))
        if len(member.range) != size:
            raise ValueError(f"{name}: {len(member.range)} ID, cần đúng {size}")
        for other in members.values():
            if any(overlaps(a, b) for a in member.range.segments for b in other.range.segments):
                raise ValueError(f"Range của {name} chồng với {other.name}")
        members[name] = member
    return members


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


def member_ids(name: str, path: str | Path | None = None) -> Iterator[str]:
    """ID của một thành viên, hoặc của cả nhóm khi name="all"; chỉ Range đã xác minh."""
    members = load_ranges(path)
    chosen = list(members.values()) if name == "all" else [members.get(name)]
    if chosen == [None]:
        raise KeyError(f"Không có Range cho '{name}' trong configs/ranges.toml "
                       f"(có: {', '.join(members)})")
    unverified = [m.name for m in chosen if not m.verified]
    if unverified:
        raise ValueError(f"Range chưa xác minh: {', '.join(unverified)}")
    return chain.from_iterable(m.range.ids() for m in chosen)
