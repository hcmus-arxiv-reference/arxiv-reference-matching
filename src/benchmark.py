"""
benchmark.py - Chạy crawler và đo hiệu năng từ bên ngoài.
 
Cách chạy (dấu -- ngăn cách phần lệnh cần đo):
    python benchmark.py -- python milestone1_starter.py --ids-file ids.txt
 
Đo được:
    - Tổng thời gian chạy (wall time)
    - RAM tối đa và RAM trung bình (tính cả tiến trình con)
    - Dung lượng đĩa tối đa và cuối cùng của thư mục data/
Kết quả:
    stats/benchmark.json
    stats/benchmark_samples.csv   (chuỗi theo thời gian, để vẽ biểu đồ)
 
Quan trọng: khi đo chính thức, hãy XÓA thư mục data/ và logs/ trước,
để số liệu phản ánh một lần chạy từ đầu (không bị checkpoint bỏ qua).
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
        ap.error("missing command, e.g.: python benchmark.py -- python milestone1_starter.py --id 1706.03762")
 
    data_dir = Path(args.data_dir)
    samples = []
    last_disk, last_disk_t = 0, -1e9
 
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd)
    ps = psutil.Process(proc.pid)
 
    while proc.poll() is None:
        now = time.monotonic() - t0
        if now - last_disk_t >= args.disk_interval:
            last_disk = dir_size(data_dir)
            last_disk_t = now
        samples.append((round(now, 2), round(tree_rss(ps) / MB, 1), round(last_disk / MB, 2)))
        time.sleep(args.interval)
 
    wall = time.monotonic() - t0
    final_disk = dir_size(data_dir)
 
    rss_values = [s[1] for s in samples]
    result = {
        "command": cmd,
        "return_code": proc.returncode,
        "wall_seconds": round(wall, 2),
        "peak_rss_mb": max(rss_values, default=None),
        "avg_rss_mb": round(sum(rss_values) / len(rss_values), 1) if rss_values else None,
        "peak_disk_mb": round(max([s[2] for s in samples] + [final_disk / MB]), 2),
        "final_disk_mb": round(final_disk / MB, 2),
        "n_samples": len(samples),
    }
 
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    with (out / "benchmark_samples.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_seconds", "rss_mb", "disk_mb"])
        w.writerows(samples)
 
    for key, value in result.items():
        print(f"{key:16s} {value}")
    sys.exit(proc.returncode or 0)
 
 
if __name__ == "__main__":
    main()
 