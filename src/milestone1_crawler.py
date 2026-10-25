"""
milestone1_crawler.py - Crawler Milestone 1 (arXiv + Semantic Scholar)

Chạy thử 1 bài:
    python milestone1_crawler.py --id 1706.03762
Chạy nhiều bài:
    python milestone1_crawler.py --ids-file ids.txt

Biến môi trường (nên đặt):
    CONTACT_EMAIL   email của bạn (đưa vào User-Agent, giống để lại danh thiếp)
    S2_API_KEY      key Semantic Scholar (KHÔNG commit lên repo!)

Cài thư viện:
    pip install arxiv requests psutil
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
import traceback
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import arxiv
import requests
import urllib3

try:
    import psutil  # tùy chọn, dùng để đo RAM
except ImportError:
    psutil = None

# ----------------------------------------------------------------------
# 1. Cấu hình
# ----------------------------------------------------------------------
CONTACT = os.environ.get("CONTACT_EMAIL", "your-email@example.com")
USER_AGENT = f"IntroDS-student-crawler/0.1 (mailto:{CONTACT})"
S2_API_KEY = os.environ.get("S2_API_KEY")

DATA_DIR = Path("data")
LOG_FILE = Path("logs") / "run_log.jsonl"

# Khi gặp nhiều lỗi "bị chặn / mạng / quá tải" liên tiếp thì nghỉ rồi thử tiếp, thay vì dồn dập hỏi thêm
STREAK_BEFORE_COOLDOWN = 5     # cứ 5 lỗi liên tiếp thì nghỉ một lần
STREAK_BEFORE_STOP = 15        # 15 lỗi liên tiếp (đã nghỉ 2 lần mà vẫn lỗi) thì dừng cả lần chạy
COOLDOWN_START = 300           # giây; nghỉ lần đầu 5 phút
COOLDOWN_MAX = 1800            # giây; mỗi lần nghỉ gấp đôi, tối đa 30 phút

# Không để dấu cách sau dấu phẩy trong danh sách field
S2_FIELDS = (
    "title,references.title,references.authors,"
    "references.publicationDate,references.externalIds,references.paperId"
)


# ----------------------------------------------------------------------
# 2. "Xếp hàng lịch sự": đảm bảo cách nhau tối thiểu N giây giữa 2 lần gọi
# ----------------------------------------------------------------------
class Throttle:
    """
    "Người gác cổng": bắt chờ ít nhất min_gap giây giữa 2 lần gọi liên tiếp.
      from_start=False (mặc định, thận trọng): tính từ lúc lần gọi trước KẾT THÚC
                        (cách thư viện arxiv chính thức làm).
      from_start=True : tính từ lúc lần gọi trước BẮT ĐẦU (nhanh hơn, chỉ bật khi đã xác nhận quy tắc).
    Ngoài ra đo: số lần gọi, tổng thời gian chờ, tổng thời gian thật sự gọi mạng.
    """

    def __init__(self, min_gap, from_start=False):
        self.min_gap = min_gap
        self.from_start = from_start
        self.last_start = 0.0
        self.last_end = 0.0
        self.n_requests = 0
        self.waited = 0.0     # tổng thời gian ngủ để chờ
        self.busy = 0.0       # tổng thời gian đang gọi mạng

    def wait(self):
        ref = self.last_start if self.from_start else self.last_end
        gap = time.monotonic() - ref
        if gap < self.min_gap:
            pause = self.min_gap - gap
            time.sleep(pause)
            self.waited += pause
        self.last_start = time.monotonic()

    def mark(self):
        now = time.monotonic()
        self.busy += now - self.last_start
        self.last_end = now
        self.n_requests += 1

    def summary(self):
        n = self.n_requests
        return {
            "requests": n,
            "min_gap": self.min_gap,
            "waited_seconds": round(self.waited, 1),
            "busy_seconds": round(self.busy, 1),
            "avg_request_seconds": round(self.busy / n, 3) if n else None,
        }


ARXIV_THROTTLE = Throttle(3.0)                          # arXiv: >= 3 giây
S2_THROTTLE = Throttle(1.1 if S2_API_KEY else 3.2)      # S2: 1/giây (có key)
ARXIV_CLIENT = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)


# ----------------------------------------------------------------------
# 3. Tải về có thử lại (retry)
# ----------------------------------------------------------------------
# Lỗi mạng: lỗi của requests VÀ lỗi của urllib3 (ví dụ ProtocolError / IncompleteRead khi kết nối đứt
# giữa lúc tải). Vì ta đọc dữ liệu thô nên lỗi urllib3 không được requests bọc lại, phải bắt riêng.
NETWORK_ERRORS = (requests.RequestException, urllib3.exceptions.HTTPError)

# True: gửi "Accept-Encoding: identity" (xin file không nén thêm). False: để mặc định của thư viện.
# Nếu nghi cách này làm máy chủ cắt kết nối, chạy với --default-encoding để thử.
ACCEPT_IDENTITY = True

_SESSIONS = {}


def _session_for(throttle):
    """
    Mỗi "người gác cổng" dùng một Session riêng: giữ kết nối mở (keep-alive) giữa các lần gọi,
    đỡ tốn thời gian bắt tay TLS mỗi lần. Vẫn chỉ MỘT kết nối tại một thời điểm.
    Accept-Encoding: identity + đọc dữ liệu thô: nhận đúng các byte server gửi, không tự giải nén
    (để việc nhận dạng .gz/.tar.gz bên dưới luôn đúng như trước).
    """
    session = _SESSIONS.get(id(throttle))
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        if ACCEPT_IDENTITY:
            session.headers["Accept-Encoding"] = "identity"
        _SESSIONS[id(throttle)] = session
    return session


def _drop_session(throttle):
    """Bỏ session (và kết nối) hiện tại: lần thử sau sẽ mở kết nối mới."""
    session = _SESSIONS.pop(id(throttle), None)
    if session is not None:
        session.close()


def _retry_after(value, default):
    """Số giây server bảo chờ (Retry-After). Giới hạn tối đa 120 giây để không ngủ im lặng hàng giờ."""
    try:
        return min(max(float(value), 1.0), 120.0)
    except (TypeError, ValueError):
        return default


MAX_ATTEMPTS = 60          # chặn vòng lặp vô tận: tối đa số lần gọi cho MỘT file
MAX_FILE_SECONDS = 600     # file nhỏ: tối đa 10 phút cho một file
MIN_SPEED = 10_000         # byte/giây (10 KB/s): chậm hơn mức này thì coi như vô vọng
UNKNOWN_SIZE_SECONDS = 3600  # server không báo dung lượng: cho tối đa 1 tiếng
PROGRESS_EVERY = 60        # giây giữa 2 dòng báo tiến độ khi đang tải file lớn


def _limit(total):
    """Thời gian tối đa cho một file: file lớn được thêm giờ theo dung lượng (tốc độ sàn MIN_SPEED)."""
    if total is None:
        return UNKNOWN_SIZE_SECONDS
    return max(MAX_FILE_SECONDS, total / MIN_SPEED)


def _parse_content_range(value):
    """'bytes 1048576-5000000/5000001' -> (start, end, total); không đọc được thì None."""
    m = re.match(r"bytes (\d+)-(\d+)/(\d+|\*)", value or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3).isdigit() else None


def _fetch_bytes(url, throttle, headers, retries, raw):
    """
    Vòng tải có thử lại. Với file nguồn (raw=True) còn biết TẢI TIẾP phần còn thiếu khi kết nối đứt:
      - dữ liệu nhận được được giữ lại trong buf, lần thử sau xin tiếp bằng 'Range: bytes=<đã có>-'
        (kèm 'If-Range' = ETag để chắc file không đổi giữa các lần);
      - nếu máy chủ không hỗ trợ Range (trả 200) thì tải lại từ đầu như bình thường;
      - lần thử mà đi XA HƠN mọi lần trước (buf dài hơn mức cao nhất từng đạt) không bị tính là thất bại,
        nên file lớn bị cắt nhiều lần vẫn tải xong được; tải đi tải lại mà không xa hơn thì bị tính lỗi;
      - kiểm tra Content-Range khớp vị trí; hết lượt hoặc quá giờ thì báo lỗi.
    Giới hạn thời gian (xem _limit) được kiểm tra ở đầu mỗi lần thử VÀ trong lúc đọc dữ liệu, nên một
    kết nối nhỏ giọt chậm cũng không treo vô hạn. Mọi lần chờ/thử lại đều in một dòng ra màn hình.
    """
    buf = bytearray()
    total, can_range, validator = None, False, None
    fails = 0                                   # số lần lỗi liên tiếp mà không đi xa thêm được
    best = 0                                    # số byte nhiều nhất từng có trong buf
    t_start = time.monotonic()
    for attempt in range(MAX_ATTEMPTS):
        now = time.monotonic()
        if now - t_start > _limit(total):
            raise RuntimeError(f"Timeout: gave up after {now - t_start:.0f}s: {url}")
        session = _session_for(throttle)        # sau lỗi mạng sẽ là session (kết nối) mới
        req_headers = dict(headers or {})
        resuming = raw and can_range and len(buf) > 0
        if resuming:
            req_headers["Range"] = f"bytes={len(buf)}-"
            if validator:
                req_headers["If-Range"] = validator
        best_before = best
        if attempt > 0:
            size = f"{len(buf) / 1e6:.1f}/{total / 1e6:.1f} MB" if total else f"{len(buf)} bytes"
            print(f"  [retry {attempt}] {url} (have {size}, fails={fails})", flush=True)
        throttle.wait()
        try:
            resp = session.get(url, headers=req_headers, timeout=60, stream=True)
            code = resp.status_code
            data = None
            if code in (200, 206):
                if not raw:
                    data = resp.content                         # đã giải nén nếu server nén (dùng cho JSON)
                else:
                    if code == 206 and resuming:
                        cr = _parse_content_range(resp.headers.get("Content-Range"))
                        if cr is None or cr[0] != len(buf) or (total is not None and cr[2] not in (None, total)):
                            buf.clear()                         # trả lời không khớp: bỏ phần đã có, tải lại từ đầu
                            total, can_range = None, False
                            raise requests.exceptions.ChunkedEncodingError("inconsistent Content-Range on resume")
                    else:                                       # 200: thân phản hồi là file từ byte 0
                        buf.clear()
                        length = resp.headers.get("Content-Length", "")
                        total = int(length) if length.isdigit() else None
                        can_range = resp.headers.get("Accept-Ranges", "").lower() == "bytes"
                        validator = resp.headers.get("ETag") or resp.headers.get("Last-Modified")
                    last_print, last_len = time.monotonic(), len(buf)
                    for chunk in resp.raw.stream(1 << 16, decode_content=False):
                        buf.extend(chunk)                       # giữ lại từng khối: nếu đứt giữa chừng vẫn còn phần đã nhận
                        now = time.monotonic()
                        if now - t_start > _limit(total):
                            resp.close()                        # đóng ngay kết nối đang đọc dở
                            _drop_session(throttle)
                            raise RuntimeError(
                                f"Timeout: gave up after {now - t_start:.0f}s (still downloading): {url}")
                        if now - last_print >= PROGRESS_EVERY:
                            speed = (len(buf) - last_len) / (now - last_print) / 1024
                            size = f"{len(buf) / 1e6:.1f}/{total / 1e6:.1f} MB" if total else f"{len(buf) / 1e6:.1f} MB"
                            print(f"  downloading {url}: {size} ({speed:.0f} KB/s)", flush=True)
                            last_print, last_len = now, len(buf)
                    if total is not None and len(buf) != total:
                        raise requests.exceptions.ChunkedEncodingError(
                            f"incomplete body: got {len(buf)} of {total} bytes")
                    data = bytes(buf)
        except NETWORK_ERRORS as exc:                           # kể cả đứt kết nối giữa lúc tải: thử lại
            _drop_session(throttle)
            best = max(best, len(buf))
            if raw and len(buf) > best_before:
                fails = 0                                       # đã đi xa hơn mọi lần trước: không tính là thất bại
            else:
                fails += 1
            if fails > retries or attempt == MAX_ATTEMPTS - 1:
                raise
            wait_s = 5 * 2 ** max(fails - 1, 0)
            print(f"  [net error] {type(exc).__name__} on {url} -> wait {wait_s}s", flush=True)
            time.sleep(wait_s)
            continue
        finally:
            throttle.mark()

        if code in (200, 206):
            return data
        if code == 404:
            return None
        if code == 403:
            raise RuntimeError(
                f"403 for {url}: check host (export.arxiv.org) and User-Agent"
            )
        if code == 416 and resuming:                            # vị trí xin tiếp không hợp lệ: tải lại từ đầu
            buf.clear()
            total, can_range = None, False
            continue
        if code in (429, 500, 502, 503, 504):
            fails += 1
            if fails > retries:
                resp.raise_for_status()
            wait_s = max(_retry_after(resp.headers.get("Retry-After"), 0), 5 * 2 ** (fails - 1))
            print(f"  [HTTP {code}] {url} -> sleeping {wait_s:.0f}s before retry", flush=True)
            time.sleep(wait_s)
            continue
        resp.raise_for_status()                                 # lỗi khác (400, 401...): báo ngay, không thử lại
        return b""
    raise RuntimeError(f"Timeout: gave up after {MAX_ATTEMPTS} attempts: {url}")


def fetch_bytes(url, throttle, headers=None, retries=4, raw=True):
    """
    Tải url, trả về bytes. 404 -> None. Lỗi tạm thời -> thử lại, chờ lâu dần.
    raw=True : byte thô đúng như server gửi (dùng cho file nguồn arXiv, không tự giải nén).
    raw=False: để thư viện tự giải nén (dùng cho JSON).
    Khi báo lỗi, gắn thêm thuộc tính crawler_url vào lỗi để log biết URL nào gây lỗi.
    """
    try:
        return _fetch_bytes(url, throttle, headers, retries, raw)
    except Exception as exc:
        exc.crawler_url = url
        raise


# ----------------------------------------------------------------------
# 4. Nhận dạng và giải nén: chỉ giữ .tex và .bib
# ----------------------------------------------------------------------
def _safe_rel(name):
    """Chuẩn hóa đường dẫn trong file nén; trả None nếu nguy hiểm (../ hoặc tuyệt đối)."""
    p = posixpath.normpath(name.replace("\\", "/"))
    if p.startswith("/") or p == ".." or p.startswith("../") or p == ".":
        return None
    return p


class CorruptArchive(Exception):
    """File nén bị hỏng hoặc bị cắt cụt."""


_READ_ERRORS = (tarfile.TarError, EOFError, zlib.error, OSError)


def _save_tar(tar, out_dir):
    """
    Trả về (danh sách file giữ lại, dung lượng giữ lại, dung lượng của TẤT CẢ file).
    Làm 2 pha: ĐỌC hết trước (lỗi đọc = file nén hỏng), rồi mới GHI ra đĩa
    (lỗi ghi như hết dung lượng đĩa vẫn báo lỗi thật, không bị nhầm là file hỏng).
    """
    try:
        members = tar.getmembers()
    except _READ_ERRORS as exc:
        raise CorruptArchive(repr(exc))

    everything, pending = 0, []
    for member in members:
        if not member.isfile():
            continue
        everything += member.size
        rel = _safe_rel(member.name)
        if rel is None or not rel.lower().endswith((".tex", ".bib")):
            continue
        try:
            fobj = tar.extractfile(member)
            content = fobj.read() if fobj is not None else None
        except _READ_ERRORS as exc:
            raise CorruptArchive(repr(exc))
        if content is not None:
            pending.append((rel, content))

    # Đọc nốt phần còn lại của luồng nén: lúc này gzip mới kiểm tra mã CRC, phát hiện dữ liệu hỏng
    try:
        stream = getattr(tar, "fileobj", None)
        while stream is not None and stream.read(1 << 20):
            pass
    except _READ_ERRORS as exc:
        raise CorruptArchive(repr(exc))

    files, kept = [], 0
    for rel, content in pending:
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
    kind: 'tar' | 'gz_single' | 'pdf' | 'other' | 'corrupt'
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if data[:4] == b"%PDF":
        return "pdf", [], 0, len(data)

    # Túi nén (.tar hoặc .tar.gz)
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.ReadError:
        tar = None                               # không phải túi nén, thử cách khác bên dưới
    except (EOFError, zlib.error, OSError):
        return "corrupt", [], 0, len(data)       # luồng nén bị cắt cụt hoặc hỏng ngay từ đầu
    if tar is not None:
        with tar:
            try:
                files, kept, everything = _save_tar(tar, out_dir)
            except CorruptArchive:
                return "corrupt", [], 0, len(data)   # túi nén hỏng: ghi bản ghi rỗng, không coi là lỗi chương trình
            return "tar", files, kept, everything

    # File .gz đơn (chỉ 1 file bên trong)
    if data[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(data)
        except (OSError, EOFError, zlib.error):
            return "corrupt", [], 0, len(data)
        if raw[:4] == b"%PDF":
            return "pdf", [], 0, len(raw)
        if b"\x00" in raw[:4096]:          # có byte 0 -> nhiều khả năng là file nhị phân
            return "other", [], 0, len(raw)
        (out_dir / "main.tex").write_bytes(raw)
        return "gz_single", ["main.tex"], len(raw), len(raw)

    return "other", [], 0, len(data)        # ví dụ file Word


# ----------------------------------------------------------------------
# 5. Các hàm tiện ích nhỏ
# ----------------------------------------------------------------------
def safe_dirname(paper_id):
    """2310.12345 -> 2310-12345 ; hep-th/9901001 -> hep-th-9901001"""
    return paper_id.replace("/", "-").replace(".", "-")


def split_versioned_id(entry_id):
    """'http://arxiv.org/abs/2310.12345v4' -> ('2310.12345', 4)"""
    m = re.search(r"abs/(.+?)(?:v(\d+))?$", entry_id)
    if not m:
        raise ValueError(f"cannot parse entry_id: {entry_id}")
    return m.group(1), int(m.group(2) or 1)


def write_json(path, obj):
    """Ghi file tạm rồi đổi tên: lỡ bị ngắt giữa chừng cũng không để lại file hỏng."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def append_log(rec):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


COOLDOWN_LOG = LOG_FILE.parent / "cooldowns.jsonl"
COOLDOWN_TOTAL = 0.0      # tổng số giây đã ngủ vì cooldown trong lần chạy này


def sleep_cooldown(seconds):
    """
    Ngủ để hạ nhiệt và ghi lại thời gian ngủ THỰC TẾ vào logs/cooldowns.jsonl
    (kể cả khi bị Ctrl+C giữa chừng), để báo cáo có thể trừ thời gian này ra khỏi wall time.
    """
    global COOLDOWN_TOTAL
    start_epoch, t0 = time.time(), time.monotonic()
    try:
        time.sleep(seconds)
    finally:
        slept = time.monotonic() - t0
        COOLDOWN_TOTAL += slept
        COOLDOWN_LOG.parent.mkdir(parents=True, exist_ok=True)
        with COOLDOWN_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"start_epoch": round(start_epoch, 1), "seconds": round(slept, 1)}) + "\n")


def error_location(exc):
    """
    Dòng code của chương trình này nơi lỗi xảy ra, ví dụ
    'milestone1_crawler.py:215 in fetch_bytes (raised in response.py:928 in _error_catcher)'.
    """
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return None
    last = frames[-1]
    mine = [f for f in frames if Path(f.filename).name == Path(__file__).name]
    target = mine[-1] if mine else last
    text = f"{Path(target.filename).name}:{target.lineno} in {target.name}"
    if target is not last:
        text += f" (raised in {Path(last.filename).name}:{last.lineno} in {last.name})"
    return text


def is_blocking_error(exc):
    """Lỗi kiểu bị chặn / mạng / quá tải (nên nghỉ rồi thử lại), khác với lỗi riêng của từng bài."""
    if isinstance(exc, NETWORK_ERRORS):
        return True
    return isinstance(exc, RuntimeError) and "403" in str(exc)


def rss_mb():
    if psutil is None:
        return None
    return round(psutil.Process().memory_info().rss / 1024 / 1024, 1)


# ----------------------------------------------------------------------
# 6. Ba việc chính
# ----------------------------------------------------------------------
def meta_from_result(r, base_id, n_versions, discover_seconds):
    return {
        "arxiv_id": base_id,
        "n_versions": n_versions,
        "title": r.title,
        "authors": [a.name for a in r.authors],
        "published": r.published.isoformat(),
        "updated": r.updated.isoformat(),
        "journal_ref": r.journal_ref,
        "discover_seconds": discover_seconds,
    }


def discover_paper(paper_id):
    """Hỏi arXiv API cho MỘT bài (dùng khi hỏi theo lô bị lỗi)."""
    t0 = time.perf_counter()
    ARXIV_THROTTLE.wait()
    try:
        results = list(ARXIV_CLIENT.results(arxiv.Search(id_list=[paper_id])))
    finally:
        ARXIV_THROTTLE.mark()
    if not results:
        return None
    r = results[0]
    base_id, n_versions = split_versioned_id(r.entry_id)
    return meta_from_result(r, base_id, n_versions, round(time.perf_counter() - t0, 3))


def discover_many(ids, batch_size=50):
    """
    Hỏi arXiv API THEO LÔ (nhiều ID trong một lần hỏi) để tiết kiệm số lần hỏi.
    Trả về dict: id -> meta (dict), hoặc None nếu arXiv không có bài đó.
    ID không có mặt trong dict = lô bị lỗi, process_paper sẽ tự hỏi lẻ.
    Dùng ID gốc, KHÔNG kèm đuôi version.
    """
    found, todo = {}, []
    for pid in ids:
        paper_dir = DATA_DIR / safe_dirname(pid)
        if (paper_dir / "done.json").exists():
            continue                                  # đã xong, khỏi hỏi
        if (paper_dir / "meta.json").exists():
            found[pid] = read_json(paper_dir / "meta.json")   # đã hỏi từ lần chạy trước
        else:
            todo.append(pid)

    for i in range(0, len(todo), batch_size):
        chunk = todo[i:i + batch_size]
        t0 = time.perf_counter()
        ARXIV_THROTTLE.wait()
        try:
            results = list(ARXIV_CLIENT.results(arxiv.Search(id_list=chunk)))
        except Exception as exc:
            print(f"discover batch {i // batch_size} failed ({exc!r}); will ask one by one")
            continue
        finally:
            ARXIV_THROTTLE.mark()
        per_paper = round((time.perf_counter() - t0) / len(chunk), 3)   # chia đều cho mỗi bài
        by_id = {}
        for r in results:
            base_id, n_versions = split_versioned_id(r.entry_id)
            by_id[base_id] = meta_from_result(r, base_id, n_versions, per_paper)
        for pid in chunk:
            meta = by_id.get(pid)
            if meta is not None:
                write_json(DATA_DIR / safe_dirname(pid) / "meta.json", meta)
            found[pid] = meta                         # None = arXiv không có bài này
    return found


def download_version(paper_id, version, paper_dir):
    """Tải 1 version. Đã làm rồi (có status.json) thì bỏ qua = checkpoint."""
    vdir = paper_dir / f"v{version}"
    status_file = vdir / "status.json"
    if status_file.exists():
        return read_json(status_file)

    t0 = time.perf_counter()
    url = f"https://export.arxiv.org/src/{paper_id}v{version}"
    data = fetch_bytes(url, ARXIV_THROTTLE)
    vdir.mkdir(parents=True, exist_ok=True)

    if data is None:
        rec = {"version": version, "kind": "not_found", "status": "empty", "files": [],
               "bytes_downloaded": 0, "bytes_before": 0, "bytes_after": 0}
    else:
        kind, files, after, everything = extract_tex_bib(data, vdir)
        rec = {"version": version, "kind": kind,
               "status": "ok" if files else "empty",   # empty = bản ghi rỗng
               "files": files,
               "bytes_downloaded": len(data),   # file nén tải về
               "bytes_before": everything,      # giải nén đầy đủ (có ảnh)
               "bytes_after": after}            # chỉ .tex và .bib
    rec["seconds"] = round(time.perf_counter() - t0, 3)
    write_json(status_file, rec)
    return rec


def fetch_and_save_refs(paper_id, paper_dir):
    """Hỏi Semantic Scholar. Trả về (số tham khảo, số tham khảo có arXiv ID)."""
    refs_file = paper_dir / "references.json"
    all_file = paper_dir / "references_all.json"
    if refs_file.exists() and all_file.exists():
        return len(read_json(all_file)), len(read_json(refs_file))

    url = (f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{paper_id}"
           f"?fields={S2_FIELDS}")
    headers = {"x-api-key": S2_API_KEY} if S2_API_KEY else {}
    raw = fetch_bytes(url, S2_THROTTLE, headers, raw=False)
    if raw is None:
        return None, None

    slim = []
    for r in json.loads(raw).get("references") or []:
        ext = r.get("externalIds") or {}
        slim.append({
            "s2_id": r.get("paperId"),
            "arxiv_id": ext.get("ArXiv"),
            "title": r.get("title"),
            "authors": [a.get("name") for a in (r.get("authors") or [])],
            "date": r.get("publicationDate"),
        })
    with_arxiv = [x for x in slim if x["arxiv_id"]]
    write_json(all_file, slim)          # giữ hết trong máy
    write_json(refs_file, with_arxiv)   # bảng cuối chỉ cần có arXiv ID
    return len(slim), len(with_arxiv)


# ----------------------------------------------------------------------
# 7. Xử lý 1 bài
# ----------------------------------------------------------------------
def process_paper(paper_id, pool, metas=None):
    paper_dir = DATA_DIR / safe_dirname(paper_id)
    done_file = paper_dir / "done.json"
    if done_file.exists():
        return "skipped"
    paper_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    metas = metas or {}
    meta_file = paper_dir / "meta.json"
    if paper_id in metas:
        meta = metas[paper_id]                  # từ lần hỏi theo lô (None = không có bài)
    elif meta_file.exists():
        meta = read_json(meta_file)
    else:
        meta = discover_paper(paper_id)         # dự phòng: hỏi lẻ
    if meta is None:
        append_log({"id": paper_id, "status": "not_found"})
        return "not_found"
    if not meta_file.exists():
        write_json(meta_file, meta)
    discover_seconds = meta.get("discover_seconds")

    # Luồng phụ hỏi Semantic Scholar trong lúc luồng chính tải source arXiv
    refs_future = pool.submit(fetch_and_save_refs, paper_id, paper_dir)

    versions = [download_version(paper_id, v, paper_dir)
                for v in range(1, meta["n_versions"] + 1)]
    n_refs, n_refs_arxiv = refs_future.result()   # lỗi ở luồng phụ sẽ nổ ra ở đây

    summary = {
        "id": paper_id,
        "status": "done",
        "n_versions": meta["n_versions"],
        "versions_with_tex": sum(1 for v in versions if v["status"] == "ok"),
        "bytes_downloaded": sum(v["bytes_downloaded"] for v in versions),
        "bytes_before": sum(v["bytes_before"] for v in versions),
        "bytes_after": sum(v["bytes_after"] for v in versions),
        "n_refs": n_refs,
        "n_refs_with_arxiv_id": n_refs_arxiv,
        "discover_seconds": discover_seconds,
        "seconds": round(time.perf_counter() - t0, 3),
        "rss_mb": rss_mb(),
    }
    write_json(done_file, summary)   # đánh dấu xong: chạy lại sẽ bỏ qua bài này
    append_log(summary)
    return "done"


def throttle_report(wall_seconds):
    """In và lưu số liệu: thời gian thật sự đi vào chờ đợi hay vào gọi mạng."""
    rep = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "wall_seconds": wall_seconds,
        "cooldown_seconds": round(COOLDOWN_TOTAL, 1),
        "gap_from_start": ARXIV_THROTTLE.from_start,
        "arxiv": ARXIV_THROTTLE.summary(),
        "semantic_scholar": S2_THROTTLE.summary(),
    }
    path = LOG_FILE.parent / "throttle_runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rep, ensure_ascii=False) + "\n")
    a = rep["arxiv"]
    print(f"arXiv: {a['requests']} requests, avg {a['avg_request_seconds']}s each, "
          f"waited {a['waited_seconds']}s, busy {a['busy_seconds']}s")


# ----------------------------------------------------------------------
# 8. Chương trình chính
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Milestone 1 crawler (arXiv + Semantic Scholar)")
    ap.add_argument("--id", action="append", help="một arXiv ID (có thể lặp lại)")
    ap.add_argument("--ids-file", help="file text, mỗi dòng một arXiv ID")
    ap.add_argument("--limit", type=int, help="chỉ chạy N bài đầu (để thử)")
    ap.add_argument("--discover-batch", type=int, default=50,
                    help="số ID hỏi arXiv mỗi lần (tối đa 100); 0 = hỏi lẻ từng bài")
    ap.add_argument("--gap-from-start", action="store_true",
                    help="tính khoảng chờ 3 giây từ lúc BẮT ĐẦU lần gọi arXiv trước (nhanh hơn). "
                         "Mặc định tính từ lúc KẾT THÚC (thận trọng). Chỉ bật khi đã xác nhận quy tắc")
    ap.add_argument("--default-encoding", action="store_true",
                    help="không gửi 'Accept-Encoding: identity' (để thư viện dùng mặc định). "
                         "Chỉ dùng để thử khi nghi cách tải làm máy chủ cắt kết nối")
    ap.add_argument("--discover-only", action="store_true",
                    help="chỉ hỏi thông tin các bài (meta.json) rồi dừng; để biết tổng số version")
    args = ap.parse_args()
    ARXIV_THROTTLE.from_start = args.gap_from_start
    global ACCEPT_IDENTITY
    ACCEPT_IDENTITY = not args.default_encoding

    ids = list(args.id or [])
    if args.ids_file:
        for line in Path(args.ids_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                ids.append(line)
    if args.limit:
        ids = ids[: args.limit]
    if not ids:
        ap.error("no ids given (use --id or --ids-file)")

    counts = {}
    t_start = time.perf_counter()
    metas = discover_many(ids, args.discover_batch) if args.discover_batch > 0 else {}
    if args.discover_only:
        n_found = n_versions = 0
        for pid in ids:
            meta_file = DATA_DIR / safe_dirname(pid) / "meta.json"
            if meta_file.exists():
                n_found += 1
                n_versions += read_json(meta_file)["n_versions"]
        print(f"Discovery finished: {n_found}/{len(ids)} papers have meta.json "
              f"(the rest: not found or failed), {n_versions} versions in total")
        throttle_report(round(time.perf_counter() - t_start, 1))
        return
    streak, cooldown = 0, COOLDOWN_START     # streak = số lỗi kiểu "bị chặn / mạng" liên tiếp
    with ThreadPoolExecutor(max_workers=1) as pool:
        for i, pid in enumerate(ids, 1):
            blocking = False
            try:
                result = process_paper(pid, pool, metas)
            except Exception as exc:   # một bài lỗi không làm hỏng cả lần chạy
                result = "error"
                blocking = is_blocking_error(exc)
                append_log({"id": pid, "status": "error", "error": repr(exc),
                            "where": error_location(exc), "url": getattr(exc, "crawler_url", None)})
            if blocking:
                streak += 1
            elif result == "done":
                streak, cooldown = 0, COOLDOWN_START   # có bài chạy được = mạng đã ổn lại
            counts[result] = counts.get(result, 0) + 1
            print(f"[{i}/{len(ids)}] {pid}: {result}")

            if streak >= STREAK_BEFORE_STOP:
                print(f"Stopping: {streak} blocking/network errors in a row. Check your connection, "
                      "wait a while, then run the same command again (finished papers are skipped).")
                break
            if blocking and streak % STREAK_BEFORE_COOLDOWN == 0:
                print(f"{streak} blocking/network errors in a row: cooling down {cooldown:.0f}s "
                      "(not sending more requests)")
                sleep_cooldown(cooldown)
                cooldown = min(cooldown * 2, COOLDOWN_MAX)

    total = round(time.perf_counter() - t_start, 1)
    print(f"Finished in {total}s. Summary: {counts}")
    throttle_report(total)


if __name__ == "__main__":
    main()
