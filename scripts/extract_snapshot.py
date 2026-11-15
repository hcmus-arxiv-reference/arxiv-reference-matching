"""Trích metadata các Range từ snapshot arXiv (Kaggle ``Cornell-University/arxiv``).

Chạy một lần trên máy có file snapshot (không cần mạng):

    python -m scripts.extract_snapshot --snapshot ~/Downloads/archive.zip \\
        --member all --out data/arxiv-snapshot.json.gz

Kết quả là một file vài MB cho ``src.crawl.cli --metadata-snapshot``. Header ghi
sha256 của file snapshot và ``latest_update_date`` (mốc chốt độ phủ Version).
Định dạng và lý do: ``src/crawl/snapshot.py``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from src.common.config import member_ids
from src.crawl.snapshot import extract_snapshot


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", type=Path, required=True, help=".zip của Kaggle, .json hoặc .json.gz")
    parser.add_argument("--member", default="all", help="Range trong configs/ranges.toml; 'all' = cả nhóm")
    parser.add_argument("--out", type=Path, required=True, help=".json hoặc .json.gz")
    args = parser.parse_args(argv)
    ids = member_ids(args.member)
    started = time.monotonic()
    header = extract_snapshot(args.snapshot.expanduser(), ids, args.out)
    summary = {k: v for k, v in header.items() if k != "invalid"}
    summary["invalid"] = len(header["invalid"])
    summary["seconds"] = round(time.monotonic() - started, 1)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for identifier, reason in list(header["invalid"].items())[:20]:
        print("invalid:", identifier, reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
