"""
make_stats.py - Thống kê Milestone 1 từ Manifest của Engine `src/crawl/`.

Cách chạy:
    python -m src.make_stats --data-dir data/crawl-smoke [--ids-file ids.txt] [--out stats]
Kết quả:
    <out>/summary.json   (các con số tổng hợp)
    <out>/papers.csv     (mỗi Publication một dòng, dùng để vẽ biểu đồ)

Nguồn: `manifests/crawl.jsonl` (bản ghi CUỐI của mỗi task), `metadata/<key>.json`
(số Version), `raw/<key>/v<n>/source.json` (danh sách .tex/.bib giữ lại) và
`references/<key>.json`. Chỉ đọc, không sửa hay cắt Manifest, nên chạy được cả khi
crawler đang ghi (dòng cuối chưa ghi xong bị bỏ qua). Không kiểm checksum: số liệu
đã xác minh checksum dùng `scripts.report_m1` hoặc `src.crawl.validation`.

Trạng thái Publication:
    done           metadata, mọi Version (success/non_tex) và references đều success
    unavailable    có Version arXiv trả HTTP 404 (unavailable), không có lỗi khác
    error          có task lỗi (discovery, source hoặc references)
    incomplete     còn task chưa chạy
    not_attempted  chưa có bản ghi discovery

Dung lượng: `bytes_after` là tổng .tex/.bib đã giữ. Layout `src/crawl/` không ghi
dung lượng file nén hay dung lượng trước khi bỏ ảnh, nên các số đó là null.
Thời gian và RAM lấy từ harness `src.benchmark`, không có trong Manifest.
"""
import argparse
import csv
import json
import statistics
from pathlib import Path

from src.common.references import CitationList
from src.crawl.storage import key

CSV_COLUMNS = [
    "id", "status", "n_versions", "versions_with_tex", "versions_non_tex",
    "versions_unavailable", "bytes_after", "n_refs", "n_refs_with_arxiv_id",
    "n_references",
]
SOURCE_OK = {"success", "non_tex"}


def load_last_per_id(log_path):
    """Dòng cuối của mỗi bài trong log standalone (`logs/run_log.jsonl`, khóa `id`)."""
    last = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            last[rec["id"]] = rec
    return last


def load_manifest(path):
    """Bản ghi cuối theo (arxiv_id, version, kind); bỏ dòng cuối nếu đang ghi dở."""
    records = {}
    if not path.exists():
        return records
    lines = path.read_bytes().splitlines(keepends=True)
    for index, line in enumerate(lines):
        try:
            rec = json.loads(line)
            if not line.endswith(b"\n"):
                raise ValueError("unterminated line")
        except ValueError:
            if index == len(lines) - 1:
                break
            raise ValueError(f"Corrupt manifest line {index + 1}") from None
        records[(rec["arxiv_id"], rec.get("version"), rec.get("kind", "source"))] = rec
    return records


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def publication_row(data_dir, records, arxiv_id):
    """Một dòng papers.csv; số không biết được để None, không điền 0."""
    row = dict.fromkeys(CSV_COLUMNS)
    row["id"] = arxiv_id
    discovery = records.get((arxiv_id, None, "discovery"))
    if discovery is None:
        row["status"] = "not_attempted"
        return row
    metadata = _read_json(data_dir / "metadata" / f"{key(arxiv_id)}.json")
    if discovery.get("status") != "success" or not metadata:
        row["status"] = "error" if discovery.get("status") == "error" else "incomplete"
        return row
    versions = metadata["publication"]["versions"]
    statuses = []
    tex = non_tex = size = 0
    for version in range(1, versions + 1):
        rec = records.get((arxiv_id, version, "source"))
        status = rec.get("status") if rec else "not_attempted"
        statuses.append(status)
        if status in SOURCE_OK:
            directory = data_dir / "raw" / key(arxiv_id) / f"v{version}"
            receipt = _read_json(directory / "source.json") or {}
            for name in receipt.get("files", {}):
                try:
                    size += (directory / name).stat().st_size
                except OSError:
                    pass
            tex += status == "success"
            non_tex += status == "non_tex"
    references = records.get((arxiv_id, None, "references"))
    ref_status = references.get("status") if references else "not_attempted"
    statuses.append(ref_status)
    if ref_status == "success":
        payload = _read_json(data_dir / "references" / f"{key(arxiv_id)}.json")
        if payload is not None:
            citations = CitationList.from_raw(arxiv_id, payload["rows"])
            row["n_refs"] = citations.total
            # One definition everywhere (CitationList): raw rows before deduplication.
            row["n_refs_with_arxiv_id"] = citations.with_arxiv_id
            row["n_references"] = len(citations.references)  # rows of the references table
    row.update(n_versions=versions, versions_with_tex=tex, versions_non_tex=non_tex,
               versions_unavailable=statuses.count("unavailable"), bytes_after=size)
    if all(s in SOURCE_OK for s in statuses[:-1]) and ref_status == "success":
        row["status"] = "done"
    elif "error" in statuses:
        row["status"] = "error"
    elif "unavailable" in statuses:
        row["status"] = "unavailable"
    else:
        row["status"] = "incomplete"
    return row


def collect(data_dir, ids=None):
    """Dòng thống kê cho `ids`, hoặc mọi Publication đã có bản ghi discovery."""
    data_dir = Path(data_dir)
    records = load_manifest(data_dir / "manifests" / "crawl.jsonl")
    if ids is None:
        ids = sorted({k[0] for k in records if k[2] == "discovery"})
    return [publication_row(data_dir, records, i) for i in dict.fromkeys(ids)]


def count_done(data_dir):
    """Số Publication `done` trong Manifest của `src/crawl/`."""
    return sum(row["status"] == "done" for row in collect(data_dir))


def avg(values):
    vals = [v for v in values if v is not None]
    return round(statistics.mean(vals), 3) if vals else None


def ratio(part, whole):
    return round(part / whole, 4) if whole else None


def summarize(rows, requested=None):
    by_status = {s: [r for r in rows if r["status"] == s]
                 for s in ("done", "unavailable", "error", "incomplete", "not_attempted")}
    done = by_status["done"]
    discovered = [r for r in rows if r["n_versions"] is not None]
    versions = sum(r["n_versions"] for r in discovered)
    tex = sum(r["versions_with_tex"] for r in discovered)
    with_refs = [r for r in rows if r["n_refs"] is not None]
    return {
        "papers_requested": requested,
        **{f"papers_{s}": len(v) for s, v in by_status.items()},
        "paper_success_rate": ratio(len(done), requested),
        "versions_total": versions,
        "versions_with_tex": tex,
        "versions_non_tex": sum(r["versions_non_tex"] for r in discovered),
        "versions_unavailable": sum(r["versions_unavailable"] for r in discovered),
        "version_tex_rate": ratio(tex, versions),
        "avg_bytes_downloaded_per_paper": None,
        "avg_bytes_before_per_paper": None,
        "avg_bytes_after_per_paper": avg([r["bytes_after"] for r in done]),
        "size_reduction_pct": None,
        "avg_refs_per_paper": avg([r["n_refs"] for r in with_refs]),
        "avg_refs_with_arxiv_id_per_paper": avg([r["n_refs_with_arxiv_id"] for r in with_refs]),
        "avg_references_per_paper": avg([r.get("n_references") for r in with_refs]),
        "papers_with_ref_metadata": len(with_refs),
        "ref_metadata_rate": ratio(len(with_refs), len(discovered)),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Thống kê M1 từ manifests/crawl.jsonl")
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--ids-file", type=Path, help="danh sách ID được giao (để tính tỷ lệ thành công)")
    ap.add_argument("--out", type=Path, default=Path("stats"))
    args = ap.parse_args(argv)
    if not (args.data_dir / "manifests" / "crawl.jsonl").exists():
        ap.error(f"{args.data_dir}/manifests/crawl.jsonl not found")

    ids = None
    if args.ids_file:
        ids = [ln.strip() for ln in args.ids_file.read_text(encoding="utf-8").splitlines()
               if ln.strip() and not ln.strip().startswith("#")]
    rows = collect(args.data_dir, ids)
    summary = summarize(rows, len(ids) if ids is not None else None)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (args.out / "papers.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["id"]))

    for name, value in summary.items():
        print(f"{name:36s} {value}")


if __name__ == "__main__":
    main()
