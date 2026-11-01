"""Check a crawl output folder against its submitted benchmark summary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from src.crawl.validation import validate_crawl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path, help="src/crawl output directory")
    parser.add_argument("--benchmark", required=True, type=Path, help="member benchmark.json")
    args = parser.parse_args(argv)
    report = validate_crawl(args.data_dir, args.benchmark)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
