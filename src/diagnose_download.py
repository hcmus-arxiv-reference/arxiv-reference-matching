"""
diagnose_download.py - Tim nguyen nhan khi tai file bi dut giua chung (IncompleteRead).

Tai CUNG MOT file bang nhieu cach khac nhau, cach nhau vai giay, roi so sanh ket qua.
Hay DUNG crawler truoc khi chay (arXiv chi cho phep mot ket noi tai mot thoi diem).

Cach chay:
    python src/diagnose_download.py --id 2410.10987
    python src/diagnose_download.py --id 2410.10987 --version 2
    python src/diagnose_download.py --url https://export.arxiv.org/src/2410.10987v1

Neu khong chi dinh --version, script tu chon version dau tien chua tai xong
(version khong co status.json trong data/<id>/v<n>/), nghia la version dang bi loi.
"""
import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

import requests

CONTACT = os.environ.get("CONTACT_EMAIL", "your-email@example.com")
UA = f"IntroDS-student-crawler/0.1 (mailto:{CONTACT})"
SHOW_HEADERS = ("content-length", "content-encoding", "transfer-encoding", "content-type",
                "accept-ranges", "server", "via", "x-cache", "x-served-by", "cache-control",
                "age", "connection")


def pick_version(paper_id, data_dir):
    folder = Path(data_dir) / paper_id.replace("/", "-").replace(".", "-")
    meta = folder / "meta.json"
    if not meta.exists():
        return 1
    n_versions = json.loads(meta.read_text(encoding="utf-8")).get("n_versions", 1)
    for v in range(1, n_versions + 1):
        if not (folder / f"v{v}" / "status.json").exists():
            return v
    return 1


def record_headers(out, headers):
    out["headers"] = {k.lower(): v for k, v in headers.items() if k.lower() in SHOW_HEADERS}
    length = headers.get("Content-Length", "")
    out["expected"] = int(length) if length.isdigit() else None


def attempt(name, fn):
    out = {"name": name, "status": None, "headers": {}, "got": 0, "expected": None,
           "error": None, "ok": False, "check_length": True}
    t0 = time.perf_counter()
    try:
        fn(out)
        complete = (not out["check_length"]) or out["expected"] is None or out["got"] == out["expected"]
        out["ok"] = out["status"] in (200, 206) and complete
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {str(exc)[:110]}"
    out["seconds"] = time.perf_counter() - t0
    return out


def main():
    ap = argparse.ArgumentParser(description="Diagnose broken downloads")
    ap.add_argument("--id", help="arXiv ID goc, vi du 2410.10987")
    ap.add_argument("--version", type=int, help="so version (mac dinh: version dau tien chua tai xong)")
    ap.add_argument("--url", help="URL day du (thay cho --id)")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--gap", type=float, default=3.5, help="giay nghi giua 2 lan tai (>= 3 voi arXiv)")
    args = ap.parse_args()

    if args.url:
        url = args.url
    elif args.id:
        version = args.version or pick_version(args.id, args.data_dir)
        url = f"https://export.arxiv.org/src/{args.id}v{version}"
    else:
        ap.error("need --id or --url")
    if "arxiv.org" in url and args.gap < 3:
        ap.error("--gap must be >= 3 for arxiv.org")

    print(f"URL: {url}")
    print("Dung crawler truoc khi chay script nay. Moi lan tai cach nhau", args.gap, "giay.\n")

    shared = requests.Session()
    shared.headers.update({"User-Agent": UA, "Accept-Encoding": "identity"})

    def m_default(out):          # nhu trinh duyet / curl: header mac dinh, ket noi moi
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=60, stream=True)
        out["status"] = resp.status_code
        record_headers(out, resp.headers)
        out["check_length"] = "content-encoding" not in out["headers"]   # neu server nen, do dai doi khi khac
        out["got"] = len(resp.content)

    def raw_read(session, out):
        resp = session.get(url, timeout=60, stream=True)
        out["status"] = resp.status_code
        record_headers(out, resp.headers)
        out["got"] = len(resp.raw.read(decode_content=False))

    def m_identity_new(out):     # cach crawler dang dung, ket noi moi
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Encoding": "identity"})
        raw_read(s, out)

    def m_identity_shared_1(out):  # cach crawler dang dung, session dung chung (lan 1)
        raw_read(shared, out)

    def m_identity_shared_2(out):  # cung session, lan 2 (ket noi duoc giu lai)
        raw_read(shared, out)

    def m_urllib(out):           # thu vien chuan cua Python (cach cua ban dau tien)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as resp:
            out["status"] = resp.status
            record_headers(out, resp.headers)
            out["got"] = len(resp.read())

    def m_range(out):            # may chu co ho tro tai tiep (Range) khong?
        resp = requests.get(url, headers={"User-Agent": UA, "Range": "bytes=0-1023"},
                            timeout=60, stream=True)
        out["status"] = resp.status_code
        record_headers(out, resp.headers)
        out["got"] = len(resp.raw.read(1024, decode_content=False))
        out["check_length"] = False
        resp.close()

    methods = [
        ("1 requests, ket noi moi, header mac dinh (nhu curl)", m_default),
        ("2 requests, ket noi moi, Accept-Encoding: identity, doc tho", m_identity_new),
        ("3 requests, session dung chung (lan 1), identity, doc tho", m_identity_shared_1),
        ("4 requests, session dung chung (lan 2), identity, doc tho", m_identity_shared_2),
        ("5 urllib (thu vien chuan Python)", m_urllib),
        ("6 thu xin tai tiep (Range) - chi 1 KB", m_range),
    ]
    results = []
    for i, (name, fn) in enumerate(methods):
        if i:
            time.sleep(args.gap)
        r = attempt(name, fn)
        results.append(r)
        got = f"{r['got']:,}" + (f"/{r['expected']:,}" if r["expected"] is not None else "")
        verdict = "OK" if r["ok"] else "FAIL"
        print(f"[{verdict:4s}] {name}")
        print(f"        status={r['status']}  bytes={got}  time={r['seconds']:.1f}s"
              + (f"  error={r['error']}" if r["error"] else ""))

    shown = next((r for r in results if r["headers"]), None)
    if shown:
        print("\nHeader may chu tra ve (mot so truong):")
        for k, v in shown["headers"].items():
            print(f"   {k}: {v}")

    ok = [r["ok"] for r in results]
    print("\n== Ket luan ==")
    if all(ok[:5]):
        print("Ca 5 cach deu tai du file luc nay: loi mang/may chu xay ra THINH THOANG, khong phai do cach tai.")
        print("Crawler ban moi tu thu lai khi dut nen se tu khac phuc phan lon.")
    elif ok[0] and not (ok[1] or ok[2] or ok[3]):
        print("Cach 1 (header mac dinh) tai duoc, nhung cach 2-4 (identity + doc tho) thi dut.")
        print("=> Nghi do header 'Accept-Encoding: identity'. Chay crawler voi --default-encoding de thu.")
    elif ok[1] and not ok[2]:
        print("Ket noi moi tai duoc, session dung chung thi dut => nghi do giu ket noi. Bao nguoi ho tro.")
    elif ok[3] is False and ok[2]:
        print("Lan dung chung dau tien duoc, lan thu 2 (tai lai tren ket noi cu) thi dut => nghi do giu ket noi.")
    elif ok[4] and not ok[0]:
        print("urllib tai duoc ma requests thi khong => nghi do thu vien requests/urllib3 tren may ban.")
    elif not any(ok[:5]):
        print("TAT CA cach deu dut => van de nam o duong truyen hoac may chu: mang/proxy/VPN/phan mem diet virus,")
        print("hoac may chu arXiv/CDN cat ket noi. Hay thu tren mang khac hoac Colab de so sanh.")
    else:
        print("Ket qua hon hop: gui toan bo output nay cho nguoi ho tro de phan tich.")
    if results[5]["ok"] and results[5]["status"] == 206:
        print("May chu HO TRO tai tiep (Range = 206): co the lam tinh nang tai tiep phan con thieu khi bi dut.")
    elif results[5]["ok"]:
        print("May chu bo qua Range (tra 200): tai tiep phan con thieu khong dung duoc.")


if __name__ == "__main__":
    main()
