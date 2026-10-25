"""
analyze_errors.py - Cho biết VÌ SAO các bài bị error (đọc logs/run_log.jsonl).

Cách chạy:
    python src/analyze_errors.py
    python src/analyze_errors.py --bucket 200 --show 5

In ra:
    1. Số dòng log theo trạng thái
    2. Các bài đang lỗi, chia theo nhóm nguyên nhân (kèm ví dụ)
    3. Xu hướng theo thời gian: tỷ lệ lỗi trong từng đợt N lần xử lý (có tăng dần không?)
    4. Bài lỗi lặp lại nhiều lần (lỗi riêng của bài) so với bài đã tự hết lỗi
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

# Thứ tự quan trọng: nhóm đứng trước được xét trước
CATEGORIES = [
    ("disk full",
     re.compile(r"Errno 28|No space left|WinError 112|not enough space", re.I),
     "Het dung luong o dia. Giai phong o dia roi chay lai."),
    ("blocked by arXiv (403)",
     re.compile(r"403 for |403 Client Error|Forbidden", re.I),
     "Bi arXiv chan. Dung lai mot luc, kiem tra CONTACT_EMAIL, khong chay 2 ban cung luc."),
    ("rate limited or server busy (429, 5xx)",
     re.compile(r"429 Client Error|Too Many Requests|50[0234] Server Error|Service Unavailable|"
                r"Bad Gateway|Gateway Timeout", re.I),
     "Bi gioi han toc do hoac may chu ban. Kiem tra khong chay 2 ban cung luc, kiem tra S2_API_KEY."),
    ("network (timeout, connection)",
     re.compile(r"ConnectionError|Timeout|Max retries|Connection aborted|Connection broken|IncompleteRead|"
                r"ProtocolError|ChunkedEncodingError|incomplete body|NameResolution|SSLError|ProxyError",
                re.I),
     "Mang bi dut giua luc tai (IncompleteRead) hoac cham. Kiem tra wifi/VPN, dung day mang, tat che do ngu cua may."),
    ("file system (file name, path, permission)",
     re.compile(r"WinError|FileNotFoundError|FileExistsError|PermissionError|NotADirectoryError|"
                r"IsADirectoryError|Invalid argument|OSError", re.I),
     "Loi ghi file (ten file Windows khong hop le, duong dan qua dai, quyen truy cap). Gui dong 'where' cho nguoi ho tro."),
    ("corrupt or unexpected archive",
     re.compile(r"ReadError|EOFError|BadGzipFile|zlib|TarError|CorruptArchive", re.I),
     "File nen hong. Ban moi cua crawler da ghi nhan day la ban ghi rong thay vi loi."),
    ("unexpected data from API or code bug",
     re.compile(r"JSONDecodeError|KeyError|TypeError|AttributeError|ValueError|IndexError", re.I),
     "Du lieu tra ve khong dung dinh dang hoac loi code. Gui dong 'error' va 'where' cho nguoi ho tro."),
    ("memory", re.compile(r"MemoryError", re.I), "Het RAM."),
]


def categorize(message):
    for name, pattern, _ in CATEGORIES:
        if pattern.search(message or ""):
            return name
    return "other"


def hint_for(name):
    for cat, _, hint in CATEGORIES:
        if cat == name:
            return hint
    return "Xem truong 'error' va 'where' de biet them."


def shorten(message, width=110):
    message = re.sub(r"\s+", " ", message or "")
    return message if len(message) <= width else message[: width - 3] + "..."


def main():
    ap = argparse.ArgumentParser(description="Explain why papers failed")
    ap.add_argument("--log", default="logs/run_log.jsonl")
    ap.add_argument("--bucket", type=int, default=100, help="so lan xu ly moi dot khi xet xu huong")
    ap.add_argument("--show", type=int, default=3, help="so vi du moi nhom")
    args = ap.parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        raise SystemExit(f"{log_path} not found. Run from the repo root folder, after at least one crawl.")
    records = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    if not records:
        raise SystemExit("log is empty")

    # ---- 1. tổng quan ----
    by_status = Counter(r["status"] for r in records)
    print("== 1. Log lines by status (each line = one attempt on one paper) ==")
    for status, n in by_status.most_common():
        print(f"   {status:10s} {n}")

    last = {}
    for r in records:
        last[r["id"]] = r
    errors_now = [r for r in last.values() if r["status"] == "error"]
    print(f"\n   Papers whose LAST attempt failed: {len(errors_now)} of {len(last)} papers seen")

    # ---- 2. nhóm nguyên nhân ----
    print("\n== 2. Why do they fail? (papers whose last attempt failed) ==")
    if not errors_now:
        print("   No failing papers.")
    groups = {}
    for r in errors_now:
        groups.setdefault(categorize(r.get("error", "")), []).append(r)
    for name, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        pct = 100 * len(items) / len(errors_now)
        print(f"\n   [{name}]  {len(items)} papers ({pct:.0f}%)")
        print(f"   hint: {hint_for(name)}")
        where = Counter(r.get("where") for r in items if r.get("where"))
        if where:
            print("   where: " + "; ".join(f"{w} (x{n})" for w, n in where.most_common(3)))
        for r in items[: args.show]:
            print(f"   - {r['id']}: {shorten(r.get('error'))}")
            if r.get("url"):
                print(f"       url: {r['url']}")

    # ---- 3. xu hướng theo thời gian ----
    print(f"\n== 3. Trend over time (per {args.bucket} attempts, oldest first) ==")
    print("   attempts       done  error  not_found  error%")
    for start in range(0, len(records), args.bucket):
        chunk = records[start:start + args.bucket]
        c = Counter(r["status"] for r in chunk)
        pct = 100 * c["error"] / len(chunk)
        bar = "#" * int(round(pct / 5))
        print(f"   {start + 1:>5}-{start + len(chunk):<6} {c['done']:>6} {c['error']:>6} {c['not_found']:>9}"
              f"  {pct:5.1f}%  {bar}")

    # ---- 4. lỗi lặp lại hay tự hết ----
    attempts = Counter()
    failed_ids = set()
    for r in records:
        if r["status"] == "error":
            attempts[r["id"]] += 1
            failed_ids.add(r["id"])
    recovered = [i for i in failed_ids if last[i]["status"] == "done"]
    repeated = [i for i, n in attempts.items() if n >= 2 and last[i]["status"] == "error"]
    print("\n== 4. Repeat failures ==")
    print(f"   Papers that failed at least once      : {len(failed_ids)}")
    print(f"   ... and later finished OK (transient) : {len(recovered)}")
    print(f"   ... failed 2+ times and still failing : {len(repeated)}  "
          "(likely a problem specific to that paper)")
    if repeated:
        print("   examples: " + ", ".join(sorted(repeated)[: args.show * 2]))


if __name__ == "__main__":
    main()
