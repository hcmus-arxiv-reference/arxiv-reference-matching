"""
merge_benchmarks.py - Gộp các đoạn benchmark (stats/runs/run_*/) thành một kết quả cho cả đợt crawl.

Cách chạy:
    python -m src.merge_benchmarks
    python -m src.merge_benchmarks --runs stats/runs --out stats

Kết quả:
    stats/benchmark_total.json         (con số tổng hợp + từng đoạn)
    stats/benchmark_samples_all.csv    (chuỗi RAM/đĩa liền mạch theo thời gian chạy thật, để vẽ biểu đồ)

Cách tính:
    total_cooldown_seconds / wall_seconds_excl_cooldown : cooldown của crawler nằm trong khoảng chạy của từng đoạn
                         (khớp theo thời điểm với logs/cooldowns.jsonl); wall time đầy đủ vẫn là số chính
    total_wall_seconds : TỔNG thời gian các đoạn thật sự chạy (khoảng nghỉ giữa các đoạn không tính)
    peak_rss_mb        : lớn nhất qua mọi đoạn
    avg_rss_mb         : trung bình theo mẫu (khoảng cách mẫu cố định nên xấp xỉ trung bình theo thời gian)
    peak/final disk    : đĩa là tích lũy qua các đoạn nên lấy lớn nhất và giá trị cuối của đoạn cuối
Đoạn không có benchmark.json (tắt máy đột ngột) vẫn được tính từ file mẫu .csv.
"""
import argparse
import csv
import json
from pathlib import Path


def read_run(run_dir):
    csv_path = run_dir / "benchmark_samples.csv"
    if not csv_path.exists():
        return None
    rows = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        for rec in csv.DictReader(f):
            try:
                rows.append((float(rec["t_seconds"]), float(rec["rss_mb"]), float(rec["disk_mb"])))
            except (TypeError, ValueError, KeyError):
                continue                      # dòng cuối có thể ghi dở khi tắt máy
    if not rows:
        return None
    meta = {}
    json_path = run_dir / "benchmark.json"
    if json_path.exists():
        meta = json.loads(json_path.read_text(encoding="utf-8"))
    started_at = meta.get("started_at")
    start_path = run_dir / "benchmark_start.json"
    if started_at is None and start_path.exists():      # đoạn bị tắt đột ngột: chỉ có file này
        try:
            started_at = json.loads(start_path.read_text(encoding="utf-8")).get("started_at")
        except ValueError:
            started_at = None
    return {
        "name": run_dir.name,
        "rows": rows,
        "wall": meta.get("wall_seconds", rows[-1][0]),
        "final_disk": meta.get("final_disk_mb", rows[-1][2]),
        "started_at": started_at,
        "meta": meta,
    }


def read_cooldowns(path):
    """Đọc logs/cooldowns.jsonl do crawler ghi: danh sách (thời điểm bắt đầu ngủ, số giây ngủ)."""
    items = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                items.append((float(rec["start_epoch"]), float(rec["seconds"])))
            except (ValueError, KeyError, TypeError):
                continue
    return items


def cooldown_in_run(cooldowns, run):
    """Tổng giây cooldown nằm trong khoảng thời gian chạy của đoạn; None nếu không biết đoạn chạy lúc nào."""
    if run["started_at"] is None:
        return None
    lo, hi = run["started_at"], run["started_at"] + run["wall"]
    return round(sum(sec for start, sec in cooldowns if lo <= start <= hi), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="stats/runs")
    ap.add_argument("--out", default="stats")
    ap.add_argument("--cooldown-log", default="logs/cooldowns.jsonl",
                    help="file do crawler ghi mỗi lần nghỉ cooldown")
    args = ap.parse_args()

    cooldowns = read_cooldowns(Path(args.cooldown_log))
    runs = []
    for d in sorted(Path(args.runs).glob("run_*")):
        if d.is_dir():
            r = read_run(d)
            if r:
                runs.append(r)
    if not runs:
        raise SystemExit(f"no runs found in {args.runs} (expected run_01, run_02, ... each with benchmark_samples.csv)")

    all_rows, offset, per_run = [], 0.0, []
    for r in runs:
        for t, rss, disk in r["rows"]:
            all_rows.append((round(offset + t, 2), rss, disk))
        offset += r["wall"]
        m = r["meta"]
        per_run.append({
            "name": r["name"],
            "wall_seconds": round(r["wall"], 2),
            "peak_rss_mb": max(x[1] for x in r["rows"]),
            "done_papers_at_start": m.get("done_papers_at_start"),
            "done_papers_at_end": m.get("done_papers_at_end"),
            "cooldown_seconds": cooldown_in_run(cooldowns, r),
            "ended": "no benchmark.json (hard stop)" if not m else ("Ctrl+C" if m.get("interrupted") else "finished"),
        })

    known = [p["cooldown_seconds"] for p in per_run if p["cooldown_seconds"] is not None]
    cooldown_total = round(sum(known), 1) if len(known) == len(per_run) else None   # None = có đoạn không biết giờ chạy
    rss = [x[1] for x in all_rows]
    total = {
        "segments": len(runs),
        "total_wall_seconds": round(offset, 2),
        "total_wall_hours": round(offset / 3600, 2),
        "total_cooldown_seconds": cooldown_total,
        "wall_seconds_excl_cooldown": round(offset - cooldown_total, 2) if cooldown_total is not None else None,
        "peak_rss_mb": max(rss),
        "avg_rss_mb": round(sum(rss) / len(rss), 1),
        "peak_disk_mb": round(max([x[2] for x in all_rows] + [r["final_disk"] for r in runs]), 2),
        "final_disk_mb": round(runs[-1]["final_disk"], 2),
        "per_segment": per_run,
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark_total.json").write_text(json.dumps(total, indent=2), encoding="utf-8")
    with (out / "benchmark_samples_all.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_seconds", "rss_mb", "disk_mb"])
        w.writerows(all_rows)

    for key, value in total.items():
        if key != "per_segment":
            print(f"{key:20s} {value}")
    for p in per_run:
        print("  ", p)


if __name__ == "__main__":
    main()
