"""
benchmark.py - Chạy crawler và đo hiệu năng từ bên ngoài. Chịu được việc bị ngắt giữa chừng.

Cách chạy (dấu -- ngăn cách phần lệnh cần đo). MỖI ĐOẠN CHẠY DÙNG MỘT --out RIÊNG:
    python -m src.benchmark --out stats/runs/run_01 -- python -m src.milestone1_crawler --ids-file ids.txt
    (bị ngắt) -> chạy tiếp với --out stats/runs/run_02, run_03, ...
    python -m src.merge_benchmarks      # gộp tất cả đoạn thành một con số

Đo được:
    - Tổng thời gian chạy (wall time) của đoạn
    - RAM tối đa và RAM trung bình (tính cả tiến trình con)
    - Dung lượng đĩa tối đa và cuối cùng của thư mục data/
Kết quả trong thư mục --out:
    benchmark.json          (ghi cuối đoạn, kể cả khi bị Ctrl+C)
    benchmark_samples.csv   (ghi dần từng mẫu: tắt máy đột ngột vẫn còn số liệu đến lúc đó)

Khi đo mới, dùng một thư mục data riêng còn trống, truyền cùng --data-dir
cho benchmark và crawler. Giữ nguyên cache đã tải; ghi rõ nếu đo resume.
Cài thư viện: pip install psutil
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

MB = 1024 * 1024


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def tree_rss(proc):
    """RAM của tiến trình và các tiến trình con (byte)."""
    try:
        total = proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except psutil.Error:
                pass
        return total
    except psutil.Error:
        return 0


def count_done(data_dir):
    """Số bài đã có done.json (để biết đoạn này bắt đầu từ đâu)."""
    return sum(1 for _ in Path(data_dir).glob("*/done.json"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="stats")
    ap.add_argument("--interval", type=float, default=1.0, help="giây giữa 2 lần lấy mẫu RAM")
    ap.add_argument("--disk-interval", type=float, default=5.0, help="giây giữa 2 lần đo đĩa")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()

    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        ap.error("missing command, e.g.: python -m src.benchmark -- python -m src.milestone1_crawler --id 1706.03762")

    data_dir = Path(args.data_dir)
    out = Path(args.out)
    if (out / "benchmark_samples.csv").exists():
        ap.error(f"{out} already has results. Use a new --out (e.g. the next run_XX) so earlier numbers are not overwritten.")
    out.mkdir(parents=True, exist_ok=True)
    done_at_start = count_done(data_dir)
    started_at = time.time()
    # Ghi ngay thời điểm bắt đầu: đoạn bị tắt máy đột ngột vẫn biết nó chạy từ lúc nào
    (out / "benchmark_start.json").write_text(json.dumps({"started_at": round(started_at, 1)}), encoding="utf-8")

    rss_values, peak_disk = [], 0.0
    last_disk, last_disk_t = 0, -1e9
    interrupted = False

    t0 = time.monotonic()
    proc = subprocess.Popen(cmd)
    ps = psutil.Process(proc.pid)

    with (out / "benchmark_samples.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_seconds", "rss_mb", "disk_mb"])
        f.flush()
        try:
            while proc.poll() is None:
                now = time.monotonic() - t0
                if now - last_disk_t >= args.disk_interval:
                    last_disk = dir_size(data_dir)
                    last_disk_t = now
                row = (round(now, 2), round(tree_rss(ps) / MB, 1), round(last_disk / MB, 2))
                w.writerow(row)
                f.flush()                      # ghi ngay: lỡ tắt máy vẫn còn số liệu
                rss_values.append(row[1])
                peak_disk = max(peak_disk, row[2])
                time.sleep(args.interval)
        except KeyboardInterrupt:
            interrupted = True                 # Ctrl+C cũng gửi tới crawler; chờ nó thoát gọn
            try:
                proc.wait(timeout=30)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                proc.terminate()

    wall = time.monotonic() - t0
    final_disk = dir_size(data_dir)

    result = {
        "command": cmd,
        "return_code": proc.returncode,
        "interrupted": interrupted,
        "wall_seconds": round(wall, 2),
        "started_at": round(started_at, 1),
        "ended_at": round(time.time(), 1),
        "peak_rss_mb": max(rss_values, default=None),
        "avg_rss_mb": round(sum(rss_values) / len(rss_values), 1) if rss_values else None,
        "peak_disk_mb": round(max(peak_disk, final_disk / MB), 2),
        "final_disk_mb": round(final_disk / MB, 2),
        "n_samples": len(rss_values),
        "done_papers_at_start": done_at_start,
        "done_papers_at_end": count_done(data_dir),
    }
    (out / "benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    for key, value in result.items():
        print(f"{key:22s} {value}")
    sys.exit(proc.returncode or 0)


if __name__ == "__main__":
    main()
