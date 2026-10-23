"""
make_stats.py - Tính các con số thống kê cho báo cáo Milestone 1 từ file log.

Cách chạy:
    python make_stats.py --ids-file ids.txt
Kết quả:
    stats/summary.json   (các con số tổng hợp)
    stats/papers.csv     (mỗi bài một dòng, dùng để vẽ biểu đồ)

Định nghĩa dung lượng (ghi rõ trong báo cáo):
    downloaded = file nén tải về | before = giải nén đầy đủ, có ảnh | after = chỉ .tex/.bib
    size_reduction_pct so sánh before với after (cùng là dung lượng chưa nén).

Lưu ý: một bài có thể có nhiều dòng log (ví dụ lỗi rồi chạy lại thành công).
Script chỉ lấy dòng CUỐI của mỗi bài.
"""
import argparse
import csv
import json
import statistics
from pathlib import Path

CSV_COLUMNS = [
    "id", "status", "n_versions", "versions_with_tex",
    "bytes_downloaded", "bytes_before", "bytes_after", "n_refs", "n_refs_with_arxiv_id",
    "discover_seconds", "seconds", "rss_mb",
]


def load_last_per_id(log_path):
    last = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            last[rec["id"]] = rec
    return last


def avg(values):
    vals = [v for v in values if v is not None]
    return round(statistics.mean(vals), 3) if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="logs/run_log.jsonl")
    ap.add_argument("--ids-file", help="danh sách ID được giao (để tính tỷ lệ thành công)")
    ap.add_argument("--out", default="stats")
    args = ap.parse_args()

    last = load_last_per_id(Path(args.log))
    done = [r for r in last.values() if r.get("status") == "done"]
    not_found = [r for r in last.values() if r.get("status") == "not_found"]
    errors = [r for r in last.values() if r.get("status") == "error"]

    requested = None
    never_logged = []
    if args.ids_file:
        ids = [ln.strip() for ln in Path(args.ids_file).read_text(encoding="utf-8").splitlines()
               if ln.strip() and not ln.startswith("#")]
        requested = len(ids)
        never_logged = [i for i in ids if i not in last]

    total_versions = sum(r["n_versions"] for r in done)
    versions_tex = sum(r["versions_with_tex"] for r in done)
    downloaded = sum(r["bytes_downloaded"] for r in done)
    before = sum(r["bytes_before"] for r in done)
    after = sum(r["bytes_after"] for r in done)
    with_refs = [r for r in done if r.get("n_refs") is not None]

    summary = {
        "papers_requested": requested,
        "papers_done": len(done),
        "papers_not_found": len(not_found),
        "papers_error": len(errors),
        "papers_never_logged": len(never_logged),
        "paper_success_rate": round(len(done) / requested, 4) if requested else None,
        "versions_total": total_versions,
        "versions_with_tex": versions_tex,
        "version_tex_rate": round(versions_tex / total_versions, 4) if total_versions else None,
        "avg_bytes_downloaded_per_paper": round(downloaded / len(done)) if done else None,
        "avg_bytes_before_per_paper": round(before / len(done)) if done else None,
        "avg_bytes_after_per_paper": round(after / len(done)) if done else None,
        "size_reduction_pct": round(100 * (1 - after / before), 2) if before else None,
        "avg_refs_per_paper": avg([r["n_refs"] for r in with_refs]),
        "avg_refs_with_arxiv_id_per_paper": avg([r["n_refs_with_arxiv_id"] for r in with_refs]),
        "papers_with_ref_metadata": len(with_refs),
        "ref_metadata_rate": round(len(with_refs) / len(done), 4) if done else None,
        "avg_seconds_per_paper": avg([r.get("seconds") for r in done]),
        "avg_discover_seconds": avg([r.get("discover_seconds") for r in done]),
        "max_rss_mb_seen_in_log": max([r["rss_mb"] for r in done if r.get("rss_mb")], default=None),
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (out / "papers.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for rec in sorted(last.values(), key=lambda r: r["id"]):
            w.writerow(rec)

    for key, value in summary.items():
        print(f"{key:36s} {value}")


if __name__ == "__main__":
    main()