"""Dự đoán thời gian crawl một Range và kiểm dự đoán bằng log của chính lượt chạy.

Mô hình (đo và lập ngày 14/11/2026 từ benchmark Colab):

- arXiv là nút cổ chai: một kết nối, request sau bắt đầu ít nhất ``GAP_SECONDS``
  sau lúc request trước *bắt đầu* (``HttpClient._send``). Một request vì vậy chiếm
  ``max(GAP_SECONDS, latency + bytes / bandwidth)`` giây.
- Một Range gồm ``versions`` request ``/src/`` (kích thước theo mẫu 415 Version,
  ``configs/size_sample_bytes.json``) và ``other_requests`` request nhỏ (Discovery
  theo lô, tra ngày từng Version), mỗi request ``GAP_SECONDS``.
- S2 chạy ở luồng riêng (References theo lô), nên chỉ phần arXiv phải chờ S2
  (``references_wait_seconds`` trong ``timings.jsonl``) cộng thêm vào thời gian.

``check_run`` so tốc độ thực tế (Publication mỗi giờ) với tốc độ mô hình dự đoán
từ băng thông đo được, và cho biết bao nhiêu phần wall time được giải thích bởi
thời gian bận của arXiv cộng thời gian chờ S2. Phần còn lại là chi phí ngoài mô
hình (giải nén, ghi đĩa, khởi động tiến trình mỗi đoạn).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import statistics
from typing import Iterable

GAP_SECONDS = 3.1                 # min_interval của arXiv trong src/crawl/cli.py
DEFAULT_LATENCY = 0.5             # giây tới byte đầu, khi log không có file nhỏ để đo
SMALL_FILE = 200_000              # file nhỏ hơn: thời gian ≈ độ trễ
LARGE_FILE = 1_000_000            # file lớn hơn: dùng để đo băng thông
TOLERANCE = 0.15                  # cổng chạy thử: lệch tối đa 15% so với dự đoán
MAX_S2_WAIT_SHARE = 0.05          # và S2 không giữ arXiv quá 5% wall time
MIN_RUN_FILES = 30                # từ chừng này file /src/ trở lên, so với kích thước file thật của lượt
SIZE_SAMPLE = Path(__file__).resolve().parents[2] / "configs" / "size_sample_bytes.json"


@dataclass(frozen=True)
class RangeShape:
    """Số request arXiv của một Range."""
    publications: int
    versions: int          # request /src/, một mỗi Version
    other_requests: int    # Discovery theo lô và tra ngày từng Version

    def scaled(self, publications: int) -> "RangeShape":
        """Cùng tỉ lệ request mỗi Publication cho một số Publication khác."""
        k = publications / self.publications
        return RangeShape(publications, round(self.versions * k), round(self.other_requests * k))


# Range Bảo (2508.02872–2508.07871), đếm trên bản crawl Mac: 7.811 Version,
# 873 lần tra ngày Version, 100 lô Discovery 50 ID.
BAO_RANGE = RangeShape(5000, 7811, 873 + 100)
# Discovery và ngày Version từ snapshot metadata (src/crawl/snapshot.py): chỉ còn /src/.
BAO_RANGE_SNAPSHOT = RangeShape(5000, 7811, 0)


@dataclass(frozen=True)
class Link:
    """Đường truyền tới arXiv đo được từ log request."""
    bandwidth_bps: float
    latency_seconds: float
    files: int
    latency_measured: bool


def load_sample_sizes(path: str | Path = SIZE_SAMPLE) -> list[int]:
    return [int(n) for n in json.loads(Path(path).read_text(encoding="utf-8"))["downloaded_bytes"]]


def read_jsonl(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def request_seconds(size: int, link: Link, gap: float = GAP_SECONDS) -> float:
    """Thời gian một request /src/ chiếm luồng arXiv."""
    return max(gap, link.latency_seconds + size / link.bandwidth_bps)


def predict_seconds(sizes: Iterable[int], link: Link, shape: RangeShape, gap: float = GAP_SECONDS) -> float:
    """Wall time dự đoán cho ``shape`` khi S2 không giữ luồng arXiv."""
    per_source = statistics.fmean(request_seconds(s, link, gap) for s in sizes)
    return shape.versions * per_source + shape.other_requests * gap


def arxiv_sources(records: Iterable[dict]) -> list[dict]:
    """Request /src/ thành công (200 hoặc 206 khi tải nối)."""
    return [r for r in records
            if r.get("service") == "arxiv" and r.get("event") == "request"
            and r.get("endpoint") == "src" and r.get("status") in (200, 206) and r.get("bytes", 0) > 0]


def link_from_requests(records: Iterable[dict]) -> Link | None:
    """Băng thông và độ trễ arXiv từ log; None khi chưa có file nào."""
    sources = arxiv_sources(records)
    if not sources:
        return None
    small = [r["seconds"] for r in sources if r["bytes"] < SMALL_FILE]
    latency = statistics.median(small) if small else DEFAULT_LATENCY
    large = [r for r in sources if r["bytes"] >= LARGE_FILE] or sources
    transfer = sum(max(r["seconds"] - latency, 1e-3) for r in large)
    return Link(sum(r["bytes"] for r in large) / transfer, latency, len(sources), bool(small))


def check_run(requests: list[dict], timings: list[dict], *, link: Link | None = None,
              sizes: list[int] | None = None, range_publications: int = 5000,
              wall_seconds: float | None = None) -> dict:
    """So lượt chạy với mô hình.

    ``link`` là đường truyền đo trước khi chạy (``speedtest``); thiếu thì đo từ
    chính log của lượt. Số request mỗi Publication lấy từ log của lượt.
    ``wall_seconds`` là wall time của các đoạn (gồm khởi động và Export); thiếu
    thì cộng ``seconds`` trong ``timings.jsonl``.

    Tốc độ dự đoán của lượt dùng kích thước các file lượt đã tải (khi có ít
    nhất ``MIN_RUN_FILES``), vì vài trăm bài đầu Range có thể nặng hay nhẹ hơn
    mẫu; ước cả Range luôn dùng ``sizes`` (mặc định mẫu 415 Version).
    """
    sizes = sizes if sizes is not None else load_sample_sizes()
    observed = [r["bytes"] for r in arxiv_sources(requests) if not r.get("range")]
    run_sizes = observed if len(observed) >= MIN_RUN_FILES else sizes
    visits = len(timings)
    wall = wall_seconds if wall_seconds else sum(t.get("seconds", 0.0) for t in timings)
    s2_wait = sum(t.get("references_wait_seconds", 0.0) for t in timings)
    arxiv_requests = [r for r in requests if r.get("service") == "arxiv" and r.get("event") == "request"]
    arxiv_busy = sum(r.get("paced", 0.0) + r.get("seconds", 0.0) for r in arxiv_requests)
    arxiv_backoff = sum(r.get("delay", 0.0) for r in requests
                        if r.get("service") == "arxiv" and r.get("event") == "backoff")
    api_requests = [r for r in arxiv_requests if r.get("endpoint") == "api"]
    s2_requests = [r for r in requests if r.get("service") == "s2" and r.get("event") == "request"]
    s2_backoff = [r for r in requests if r.get("service") == "s2" and r.get("event") == "backoff"]
    arxiv_busy += arxiv_backoff
    run_link = link_from_requests(requests)
    used = link or run_link
    result = {
        "publications_visited": visits,
        "wall_seconds": round(wall, 1),
        "measured_per_hour": round(visits * 3600 / wall, 1) if wall else None,
        "arxiv": {"requests": len(arxiv_requests),
                  "source_files": len(arxiv_sources(requests)),
                  "busy_seconds": round(arxiv_busy, 1),
                  "status_429": sum(1 for r in arxiv_requests if r.get("status") == 429),
                  "api_requests": len(api_requests),
                  "api_not_ok": sum(1 for r in api_requests if r.get("status") != 200),
                  "backoff_seconds": round(arxiv_backoff, 1),
                  "backoff_share": round(arxiv_backoff / wall, 3) if wall else None,
                  "link_from_run": asdict(run_link) if run_link else None},
        "s2": {"requests": len(s2_requests),
               "status_429": sum(1 for r in s2_requests if r.get("status") == 429),
               "backoff_seconds": round(sum(r.get("delay", 0.0) for r in s2_backoff), 1),
               "arxiv_wait_seconds": round(s2_wait, 1),
               "arxiv_wait_share": round(s2_wait / wall, 3) if wall else None},
        "explained_share": round((arxiv_busy + s2_wait) / wall, 3) if wall else None,
        "link_used": asdict(used) if used else None,
    }
    if not (used and visits and wall):
        result["verdict"] = "CHƯA ĐỦ SỐ LIỆU"
        return result
    sources = sum(1 for r in arxiv_requests if r.get("endpoint") == "src" and not r.get("range"))
    others = sum(1 for r in arxiv_requests if r.get("endpoint") != "src")
    shape = RangeShape(visits, sources, others)
    predicted = predict_seconds(run_sizes, used, shape)
    predicted_rate = visits * 3600 / predicted
    deviation = result["measured_per_hour"] / predicted_rate - 1
    range_shape = shape.scaled(range_publications)
    result.update({
        "predicted_per_hour": round(predicted_rate, 1),
        "predicted_from": "run_files" if run_sizes is observed else "size_sample",
        "deviation": round(deviation, 3),
        "range_hours_at_measured_rate": round(range_publications / result["measured_per_hour"], 1),
        "range_hours_predicted": round(predict_seconds(sizes, used, range_shape) / 3600, 1),
        "range_hours_predicted_bao_shape": round(
            predict_seconds(sizes, used, BAO_RANGE.scaled(range_publications)) / 3600, 1),
    })
    ok = abs(deviation) <= TOLERANCE and s2_wait / wall <= MAX_S2_WAIT_SHARE
    result["verdict"] = "ĐẠT" if ok else "KHÔNG ĐẠT"
    return result


def describe(result: dict) -> str:
    """Vài dòng tiếng Việt cho notebook."""
    lines = [f"Đã thăm {result['publications_visited']} Publication trong "
             f"{result['wall_seconds'] / 3600:.2f} giờ: {result['measured_per_hour']} bài/giờ."]
    link = result.get("link_used")
    if link:
        lines.append(f"Băng thông arXiv {link['bandwidth_bps'] / 1e6:.2f} MB/s, độ trễ "
                     f"{link['latency_seconds']:.2f} s ({link['files']} file"
                     f"{'' if link['latency_measured'] else ', độ trễ mặc định'}).")
    arxiv = result["arxiv"]
    lines.append(f"arXiv: {arxiv['requests']} request, {arxiv['status_429']} lần 429; API Discovery "
                 f"{arxiv['api_not_ok']}/{arxiv['api_requests']} lần không phải 200; chờ backoff "
                 f"{arxiv['backoff_seconds']} s ({(arxiv['backoff_share'] or 0) * 100:.1f}% wall time).")
    s2 = result["s2"]
    lines.append(f"S2: {s2['requests']} request, {s2['status_429']} lần 429, chờ backoff "
                 f"{s2['backoff_seconds']} s; arXiv phải chờ S2 {s2['arxiv_wait_seconds']} s "
                 f"({(s2['arxiv_wait_share'] or 0) * 100:.1f}% wall time).")
    if "predicted_per_hour" in result:
        lines.append(f"Dự đoán {result['predicted_per_hour']} bài/giờ, lệch {result['deviation'] * 100:+.1f}%. "
                     f"Mô hình giải thích {(result['explained_share'] or 0) * 100:.0f}% wall time.")
        lines.append(f"Ước cả Range: {result['range_hours_at_measured_rate']} giờ theo tốc độ đo, "
                     f"{result['range_hours_predicted']} giờ theo mô hình.")
    if result["verdict"] == "KHÔNG ĐẠT" and (arxiv["backoff_share"] or 0) > MAX_S2_WAIT_SHARE:
        lines.append("Lý do chính: arXiv giới hạn request (429/5xx) trong lượt này; phần chờ đó nằm "
                     "ngoài mô hình. Xem dòng arxiv/backoff trong manifests/requests.jsonl.")
    lines.append(f"KẾT LUẬN: {result['verdict']}")
    return "\n".join(lines)
