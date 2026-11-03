"""Package code and existing verified caches for two independent Kaggle jobs."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import zipfile

from filelock import FileLock

from scripts.crawl_range import parse_range
from src.crawl.split import archive_cache, import_cache, read_cache, ready
from src.crawl.storage import write_json


def prepare(roots, output, ids):
    """Snapshot stopped crawlers; never package .env, IDE files or legacy secrets."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    ids = list(ids)
    counts = {}
    with ExitStack() as locks:
        for root in roots:
            for name in (".pipeline.lock", ".crawl.lock"):
                locks.enter_context(FileLock(str(Path(root) / name), timeout=0))
        for stage in ("arxiv", "s2"):
            working = output / "staging" / stage
            import_cache(roots, working, ids, stage)
            view = read_cache(working)
            complete = [i for i in ids if ready(view, i, stage)]
            counts[stage] = {"complete": len(complete), "pending": len(ids)-len(complete)}
            archive_cache(working, output / f"{stage}-seed.zip")
    repo = Path(__file__).resolve().parents[1]
    files = [repo / "src/__init__.py", repo / "src/common/__init__.py",
             repo / "src/common/schema.py", repo / "src/common/config.py"]
    files.extend(sorted((repo / "src/crawl").glob("*.py")))
    with zipfile.ZipFile(output / "crawler-code.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(repo).as_posix())
    report = {"ids": ids, "counts": counts, "format": 1}
    write_json(output / "bundle-info.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2412.08848")
    parser.add_argument("--end", default="2412.13847")
    parser.add_argument("--cache", action="append", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/kaggle-bundle"))
    args = parser.parse_args()
    roots = args.cache or [p for p in sorted(Path("data").glob("crawl-*"))
                           if (p / "manifests/crawl.jsonl").exists()]
    if not roots:
        parser.error("No existing caches found; pass --cache explicitly")
    result = prepare(roots, args.output, parse_range(args.start, args.end).ids())
    print(json.dumps(result["counts"], indent=2))
    print(f"Upload only the three ZIP files and bundle-info.json from {args.output.resolve()}")


if __name__ == "__main__":
    main()
