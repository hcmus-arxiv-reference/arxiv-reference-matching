"""Dự đoán và kiểm thời gian crawl một Range (mô hình: ``src/crawl/runtime_model.py``).

Hai lệnh, đều chạy khi KHÔNG có crawler nào khác đang chạy trên máy này:

    # Trước khi crawl: tải 2 Version mẫu qua export.arxiv.org (cách >= 3,1 giây),
    # đo băng thông, in số giờ dự đoán cho một Range, rồi hỏi thử API Discovery
    # (/api/query) vài lần xem arXiv có đang trả 429 cho máy này không.
    python -m scripts.predict_runtime speedtest --out speedtest.json

    # Sau một hay nhiều đoạn crawl: so tốc độ thực tế với dự đoán.
    python -m scripts.predict_runtime check --data-dir <DATA_DIR> --speedtest speedtest.json

``speedtest`` thoát mã 3 khi API Discovery bị giới hạn (429/5xx/timeout): crawl
lúc đó sẽ chậm hơn dự đoán nhiều (Colab 15/11: 43/55 query bị 429).
``check`` đọc ``manifests/requests.jsonl`` (log từng request của ``src.crawl.cli``)
và ``manifests/timings.jsonl``. Mã thoát 0 khi ĐẠT, 1 khi KHÔNG ĐẠT, 2 khi chưa đủ số liệu.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import statistics
from urllib.parse import urlencode

from src.common.config import get_settings
from src.crawl.http_client import HttpClient
from src.crawl.runtime_model import (BAO_RANGE, BAO_RANGE_SNAPSHOT, GAP_SECONDS, Link, check_run, describe,
                                     link_from_requests, load_sample_sizes, predict_seconds,
                                     read_jsonl)

# Hai Version trong Range Bảo, khoảng 8 và 6 MB; trên Mac 13/11 mất 6,1 và 4,4 giây.
SPEEDTEST_VERSIONS = ("2508.03249v1", "2508.06509v1")
API_PROBES = 3   # query Discovery nhỏ, cách >= 3,1 giây, không thử lại


def speedtest(versions=SPEEDTEST_VERSIONS, *, client: HttpClient | None = None) -> dict:
    """Tải ``versions`` vào bộ nhớ, trả băng thông và dự đoán cho Range Bảo."""
    records: list[dict] = []
    if client is None:
        client = HttpClient(get_settings().user_agent(), min_interval=GAP_SECONDS, name="arxiv")
    client.on_request, client.name = records.append, client.name or "arxiv"
    for version in versions:
        response = client.get(f"https://export.arxiv.org/src/{version}")
        if response.status != 200:
            raise RuntimeError(f"{version}: HTTP {response.status}")
    link = link_from_requests(records)
    if link is None:
        raise RuntimeError("Không đo được: không có file nào tải xong")
    sizes = load_sample_sizes()
    hours = predict_seconds(sizes, link, BAO_RANGE_SNAPSHOT) / 3600
    hours_api = predict_seconds(sizes, link, BAO_RANGE) / 3600
    files = [{"bytes": r["bytes"], "seconds": r["seconds"]} for r in records if r.get("event") == "request"]
    return {"link": asdict(link), "files": files, "range_hours_predicted": round(hours, 1),
            "range_hours_predicted_api_discovery": round(hours_api, 1),
            "api": probe_api(client, [v.split("v")[0] for v in versions])}


def probe_api(client: HttpClient, ids, probes: int = API_PROBES) -> dict:
    """Hỏi API Discovery ``probes`` lần, không thử lại, đếm câu trả lời không phải 200."""
    records: list[dict] = []
    saved = client.on_request, client.max_retries
    client.on_request, client.max_retries = records.append, 0
    query = urlencode({"id_list": ",".join(ids), "max_results": len(ids)})
    try:
        for _ in range(probes):
            try:
                client.get(f"https://export.arxiv.org/api/query?{query}")
            except OSError:
                pass   # timeout hay lỗi mạng: đã ghi vào records
    finally:
        client.on_request, client.max_retries = saved
    sent = [r for r in records if r.get("event") == "request"]
    ok = [r for r in sent if r.get("status") == 200]
    return {"requests": len(sent), "ok": len(ok),
            "status_429": sum(1 for r in sent if r.get("status") == 429),
            "median_seconds": round(statistics.median(r["seconds"] for r in sent), 2) if sent else None,
            "throttled": len(ok) < len(sent)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    test = sub.add_parser("speedtest", help="đo băng thông arXiv và dự đoán số giờ một Range")
    test.add_argument("--out", type=Path)
    check = sub.add_parser("check", help="so lượt chạy với dự đoán")
    check.add_argument("--data-dir", type=Path, required=True)
    check.add_argument("--speedtest", type=Path, help="kết quả speedtest; thiếu thì đo từ log của lượt")
    check.add_argument("--range-publications", type=int, default=5000)
    check.add_argument("--wall-seconds", type=float, help="wall time các đoạn; thiếu thì cộng timings.jsonl")
    check.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if args.command == "speedtest":
        result = speedtest()
        link = result["link"]
        files = ", ".join(f"{f['bytes'] / 1e6:.1f} MB trong {f['seconds']:.1f}s" for f in result["files"])
        print(f"Băng thông arXiv {link['bandwidth_bps'] / 1e6:.2f} MB/s ({files}).")
        print(f"Dự đoán một Range (5.000 ID, cỡ Range Bảo): {result['range_hours_predicted']} giờ với snapshot "
              f"metadata, {result['range_hours_predicted_api_discovery']} giờ nếu Discovery qua API.")
        api = result["api"]
        print(f"API Discovery: {api['ok']}/{api['requests']} lần 200, {api['status_429']} lần 429, "
              f"trung vị {api['median_seconds']} s.")
        if api["throttled"]:
            print("CHÚ Ý: arXiv đang giới hạn API Discovery (429/5xx/timeout); crawl lúc này sẽ chậm hơn "
                  "dự đoán nhiều. Chờ 10–15 phút rồi đo lại.")
    else:
        link = None
        if args.speedtest:
            link = Link(**json.loads(args.speedtest.read_text(encoding="utf-8"))["link"])
        manifests = args.data_dir / "manifests"
        result = check_run(read_jsonl(manifests / "requests.jsonl"), read_jsonl(manifests / "timings.jsonl"),
                           link=link, range_publications=args.range_publications,
                           wall_seconds=args.wall_seconds)
        print(describe(result))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.command == "check":
        return {"ĐẠT": 0, "KHÔNG ĐẠT": 1}.get(result["verdict"], 2)
    return 3 if result["api"]["throttled"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
