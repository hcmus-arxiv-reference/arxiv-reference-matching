"""
milestone1_starter.py - Khung chạy Milestone 1 (crawl arXiv + Semantic Scholar)
 
Chạy thử 1 bài:
    python milestone1_starter.py --id 1706.03762
Chạy nhiều bài:
    python milestone1_starter.py --ids-file ids.txt
 
Biến môi trường (nên đặt):
    CONTACT_EMAIL   email của bạn (đưa vào User-Agent, giống để lại danh thiếp)
    S2_API_KEY      key Semantic Scholar (KHÔNG commit lên repo!)
 
Cài thư viện:
    pip install arxiv psutil
"""

import argparse
import gzip
import io
import json
import os
import posixpath
import re
import tarfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import arxiv

try:
    import psutil # tùy chọn, dùng để đo RAM
except ImportError:
    psutil = None


# ----------------------------------------------------------------------
# 1. Cấu hình
# ----------------------------------------------------------------------
CONTACT = os.environ.get("CONTACT_EMAIL", "24120368@student.hcmus.edu.vn")
USER_AGENT = f"IntroDS-student-crawler/0.1 (mailto:{CONTACT})"
S2_API_KEY = os.environ.get("S2_API_KEY")

DATA_DIR = Path("data")
LOG_FILE = Path("logs") / "run_log.jsonl"

S2_FIELDS = (
    "title,references.title,references.authors,"
    "references.publicationDate,references.externalIds,references.paperId"
)


# ----------------------------------------------------------------------
# 2. "Xếp hàng lịch sự": đảm bảo cách nhau tối thiểu N giây giữa 2 lần gọi
# ----------------------------------------------------------------------
class Throttle:
    def __init__(self, min_gap):
        self.min_gap = min_gap
        self.last_end = 0.0

    def wait(self):
        gap = time.monotonic() - self.last_end
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)

    def mark(self):
        self.last_end = time.monotonic()


ARXIV_THROTTLE = Throttle(3.0)
S2_THROTTLE = Throttle(1.1 if S2_API_KEY else 3.2)
ARXIV_CLIENT = arxiv.Client(page_size=100, delay_seconds=3.0, num_entries=3)


# ----------------------------------------------------------------------
# 3. Tải về có thử lại (retry)
# ----------------------------------------------------------------------
def _retry_after(err, default):
    value = err.headers.get("Retry-After") if err.headers else None
    try:
        return max(float(value), 1.0)
    except (ValueError, TypeError):
        return default

def fetch_bytes(url, throttle, headers=None, retries=4):
    """Tải url, trả về bytes. 404 -> None. Lỗi tạm thời -> thử lại, chờ lâu dần."""
    all_headers = {"User-Agent": USER_AGENT}
    all_headers.update(headers or {})
    for attempt in range(retries + 1):
        throttle.wait()
        try:
            req = urllib.request.Request(url, headers=all_headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            if err.code == 403:
                raise RuntimeError(
                    f"403 for {url}: check host (export.arxiv.org) and User-Agent"
                )
            if err.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(_retry_after(err, 5 * 2 ** attempt))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries:
                time.sleep(5 * 2 ** attempt)
                continue
            raise
        finally:
            throttle.mark()


# ----------------------------------------------------------------------
# 4. Nhận dạng và giải nén: chỉ giữ .tex và .bib
# ----------------------------------------------------------------------
def _safe_rel(name):
    """Chuẩn hóa đường dẫn trong file nén; trả None nếu nguy hiểm (../ hoặc tuyệt đối)."""
    p = posixpath.normpath(name.replace("\\", "/"))
    if p.startswith("/") or p == ".." or p.startswith("../") or p == ".":
        return None
    
    return p

def _save_tar(tar, out_dir):
    """Trả về (danh sách file giữ lại, dung lượng giữ lại, dung lượng của TẤT CẢ file)."""
    files, kept, everything = [], 0, 0
    for member in tar.getmembers():
        if not member.isfile():
            continue

        everything += member.size
        rel = _safe_rel(member.name)
        if rel is None or not rel.lower().endswith((".tex", ".bib")):
            continue

        fobj = tar.extractfile(member)
        if fobj is None:
            continue

        content = fobj.read()
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        files.append(rel)
        kept += len(content)

    return files, kept, everything

def extract_tex_bib(data, out_dir):
    """
    Nhận dạng loại file bằng NỘI DUNG (không tin đuôi file).
    Trả về (kind, files, bytes_after, bytes_all).
      bytes_after = dung lượng các file .tex/.bib giữ lại
      bytes_all   = dung lượng giải nén của TẤT CẢ file (gồm cả ảnh) = "trước khi bỏ ảnh"
    kind: 'tar' | 'gz_single' | 'pdf' | 'other'
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if data[:4] == b"%PDF":
        return "pdf", [], 0, len(data)

    # Túi nén (.tar hoặc .tar.gz)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
            files, kept, everything = _save_tar(tar, out_dir)
            return "tar", files, kept, everything
    except tarfile.ReadError:
        pass

    # File .gz đơn (chỉ 1 file bên trong)
    if data[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(data)
        except (OSError, EOFError):
            return "other", [], 0, len(data)

        if raw[:4] == b"%PDF":
            return "pdf", [], 0, len(raw)

        if b"\x00" in raw[:4096]:       # có byte 0 -> nhiều khả năng là file nhị phân
            return "other", [], 0, len(raw)
        
        (out_dir / "main.tex").write_bytes(raw)
        return "gz_single", ["main.tex"], len(raw), len(raw)

    return "other", [], 0, len(data)        # ví dụ file Word


