"""Merge downloaded arXiv/S2 notebook checkpoints offline into final Parquet."""
import argparse
import json
from pathlib import Path
import tempfile

from scripts.crawl_range import parse_range
from src.crawl.split import merge_results, unpack_cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arxiv", type=Path, required=True)
    parser.add_argument("--s2", type=Path, required=True)
    parser.add_argument("--start", default="2412.08848")
    parser.add_argument("--end", default="2412.13847")
    parser.add_argument("--output", type=Path, default=Path("data/kaggle-merged"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        roots = [unpack_cache(path, Path(temporary) / stage)
                 for path, stage in [(args.arxiv, "arxiv"), (args.s2, "s2")]]
        result = merge_results(roots, args.output, parse_range(args.start, args.end).ids())
    print(json.dumps(result, indent=2))
    return 0 if not result["pending_ids"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
