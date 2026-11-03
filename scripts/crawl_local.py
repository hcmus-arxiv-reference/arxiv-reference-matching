"""Resume local caches, run arXiv then S2, and export the original tables."""
import argparse
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path

from filelock import FileLock

from scripts.crawl_range import parse_range
from src.common.config import get_settings, load_env
from src.crawl.split import import_cache, make_pipeline, merge_results, run_stage


def cache_roots(data):
    """Find known local caches without recursively scanning source files."""
    data = Path(data)
    candidates = sorted(data.glob('crawl-*')) + [data / 'kaggle-merged']
    candidates += [data / 'kaggle-bundle/staging' / stage for stage in ('arxiv', 's2')]
    return [p for p in candidates if (p / 'manifests/crawl.jsonl').is_file()]


def run_local(settings, identifiers, *, roots, output, stage='all', max_passes=1,
              max_seconds=7*24*3600, retry_delay=1800):
    """Sequential workers; an interrupted arXiv run must never start S2.

    A finished pass may still have failed IDs. Those remain pending while S2
    runs; final export includes only Publications complete in both services.
    """
    if stage not in {'all', 'arxiv', 's2'}:
        raise ValueError('Invalid stage')
    settings.user_agent()  # Fail before copying cache if configuration is missing.
    ids = list(identifiers)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    roots = sorted({Path(p).resolve() for p in roots}, key=str)
    reports = {}
    with FileLock(str(output / '.local-run.lock'), timeout=0):
        for service in (('arxiv', 's2') if stage == 'all' else (stage,)):
            target = output / service
            print(f'[{service}] Import/check existing local cache. No network yet.', flush=True)
            with ExitStack() as locks:
                for root in roots:
                    if root == target.resolve():
                        raise ValueError('Input cache must differ from worker output')
                    for name in ('.pipeline.lock', '.crawl.lock'):
                        locks.enter_context(FileLock(str(root / name), timeout=0))
                copied = import_cache(roots, target, ids, service)
            print(f'[{service}] Imported {copied} components. Checking remaining IDs...', flush=True)
            pipeline = make_pipeline(replace(settings, data_dir=target), service)
            reports[service] = run_stage(pipeline, ids, service, max_passes=max_passes,
                max_seconds=max_seconds, retry_delay=retry_delay)
            print(json.dumps({k: v for k, v in reports[service].items() if k != 'pending_ids'}), flush=True)
            if reports[service]['status'] == 'stopped':
                print('Stopped safely. Rerun the same command to resume.', flush=True)
                return reports
        if stage == 'all':
            print('Exporting final merged cache and Parquet (offline)...', flush=True)
            reports['merged'] = merge_results([output / 'arxiv', output / 's2'], output / 'merged', ids)
            print(f"Final complete: {reports['merged']['complete']}/{len(ids)}; {output / 'merged/tables'}", flush=True)
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2412.08848')
    parser.add_argument('--end', default='2412.13847')
    parser.add_argument('--stage', choices=['all', 'arxiv', 's2'], default='all')
    parser.add_argument('--output', type=Path, default=Path('data/local-sequential'))
    parser.add_argument('--cache', type=Path, action='append')
    parser.add_argument('--max-passes', type=int, default=1)
    parser.add_argument('--max-hours', type=float, default=168)
    parser.add_argument('--retry-delay', type=float, default=1800)
    args = parser.parse_args()
    if args.max_passes < 1 or args.max_hours <= 0 or args.retry_delay < 0:
        parser.error('Invalid retry/time settings')
    repo = Path(__file__).resolve().parents[1]
    load_env(repo / '.env')
    try:
        reports = run_local(get_settings(), parse_range(args.start, args.end).ids(),
            roots=args.cache if args.cache is not None else cache_roots(Path('data')),
            output=args.output, stage=args.stage, max_passes=args.max_passes,
            max_seconds=args.max_hours*3600, retry_delay=args.retry_delay)
    except KeyboardInterrupt:
        print('Stopped during cache preparation/export. Rerun to resume; original caches are retained.')
        return 130
    if any(r.get('status') == 'stopped' for r in reports.values()):
        return 130
    return int(any(r.get('pending_ids') for r in reports.values()))


if __name__ == '__main__':
    raise SystemExit(main())
