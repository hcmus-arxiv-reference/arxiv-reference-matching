"""Dự đoán và kiểm thời gian crawl một Range (mô hình: ``src/crawl/runtime_model.py``).

Hai lệnh, đều chạy khi KHÔNG có crawler nào khác đang chạy trên máy này:

    # Trước khi crawl: tải 2 Version mẫu qua export.arxiv.org (cách >= 3,1 giây),
    # đo băng thông và in số giờ dự đoán cho một Range.
    python -m scripts.predict_runtime speedtest --out speedtest.json

    # Sau một hay nhiều đoạn crawl: so tốc độ thực tế với dự đoán.
    python -m scripts.predict_runtime check --data-dir <DATA_DIR> --speedtest speedtest.json

``check`` đọc ``manifests/requests.jsonl`` (log từng request của ``src.crawl.cli``)
và ``manifests/timings.jsonl``. Mã thoát 0 khi ĐẠT, 1 khi KHÔNG ĐẠT, 2 khi chưa đủ số liệu.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from src.common.config import get_settings
from src.crawl.http_client import HttpClient
from src.crawl.runtime_model import (BAO_RANGE, GAP_SECONDS, Link, check_run, describe,
                                     link_from_requests, load_sample_sizes, predict_seconds,
                                     read_jsonl)

# Hai Version trong Range Bảo, khoảng 8 và 6 MB; trên Mac 13/11 mất 6,1 và 4,4 giây.
SPEEDTEST_VERSIONS = ("2508.03249v1", "2508.06509v1")


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
    hours = predict_seconds(load_sample_sizes(), link, BAO_RANGE) / 3600
    files = [{"bytes": r["bytes"], "seconds": r["seconds"]} for r in records if r.get("event") == "request"]
    return {"link": asdict(link), "files": files, "range_hours_predicted": round(hours, 1)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    test = sub.add_parser("speedtest", help="đo băng thông arXiv và dự đoán số giờ một Range")
    test.add_argument("--out", type=Path)
    check = sub.add_parser("check", help="so lượt chạy với dự đoán")
    check.add_argument("--data-dir", type=Path, required=True)
    check.add_argument("--speedtest", type=Path, help="kết quả speedtest; thiếu thì đo từ log của lượt")
    check.add_argument("--range-publications", type=int, default=5000)
    check.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if args.command == "speedtest":
        result = speedtest()
        link = result["link"]
        files = ", ".join(f"{f['bytes'] / 1e6:.1f} MB trong {f['seconds']:.1f}s" for f in result["files"])
        print(f"Băng thông arXiv {link['bandwidth_bps'] / 1e6:.2f} MB/s ({files}).")
        print(f"Dự đoán một Range (5.000 ID, cỡ Range Bảo): {result['range_hours_predicted']} giờ.")
    else:
        link = None
        if args.speedtest:
            link = Link(**json.loads(args.speedtest.read_text(encoding="utf-8"))["link"])
        manifests = args.data_dir / "manifests"
        result = check_run(read_jsonl(manifests / "requests.jsonl"), read_jsonl(manifests / "timings.jsonl"),
                           link=link, range_publications=args.range_publications)
        print(describe(result))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.command == "check":
        return {"ĐẠT": 0, "KHÔNG ĐẠT": 1}.get(result["verdict"], 2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
