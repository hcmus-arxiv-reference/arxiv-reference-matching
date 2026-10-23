"""Local CLI for the complete arXiv + Semantic Scholar SQLite workflow."""
import argparse
import json
import logging
from pathlib import Path
from src.common.config import ArxivRange, get_settings, load_env
from src.crawl.pipeline import run, export_tables, snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', default='2412')
    parser.add_argument('--start', type=int, default=8848)
    parser.add_argument('--end', type=int, default=13847)
    parser.add_argument('--limit', type=int, default=3)
    parser.add_argument('--output', default='data/crawl_hai')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--export-only', action='store_true')
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error('--limit must be positive')
    ids = list(ArxivRange(args.prefix, args.start, args.end).ids())[:args.limit]
    print(f'Selected {len(ids)} IDs: {ids[0]} -> {ids[-1]}', flush=True)
    if args.dry_run:
        return 0
    if args.export_only:
        print(export_tables(args.output, ids))
        print(snapshot(args.output, Path(args.output).parent / 'arxiv_hai_snapshot.zip'))
        return 0
    load_env(Path(__file__).resolve().parents[1] / '.env')
    settings = get_settings()
    settings.user_agent()
    if not settings.s2_api_key:
        parser.error('Set S2_API_KEY in the local .env')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        result = run(args.output, ids, settings.user_agent(), settings.s2_api_key)
    except KeyboardInterrupt:
        print('Stopped. SQLite checkpoints are saved; rerun the same command to resume.')
        return 130
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
