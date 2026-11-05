"""Validate local crawl output and export the team's M1 snapshot format.

Reporting contract: origin/feat/m1-report:src/reporting/m1.py. No crawl/API calls.
Range is explicit so Hai's data cannot accidentally be audited as Bao's Range.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from functools import lru_cache
import json
from pathlib import Path

from filelock import FileLock

from scripts.crawl_range import parse_range
from src.crawl.storage import key, write_json
from src.crawl.split import read_cache
from src.reporting import m1


def report(cache, identifiers, *, member, output, workers=8):
    """Check every source hash once, then reuse those results during reporting."""
    cache, output = Path(cache).resolve(), Path(output).resolve()
    if not cache.is_dir() or output == cache or cache in output.parents:
        raise ValueError('Output must be outside an existing cache directory')
    ids = list(identifiers)
    wanted = set(ids)
    with ExitStack() as locks:
        for name in ('.pipeline.lock','.crawl.lock'):
            locks.enter_context(FileLock(str(cache/name),timeout=0))
        view = read_cache(cache)
        sources = [cache/'raw'/key(r.arxiv_id)/f'v{r.version}'
                   for r in view.manifest.records.values() if r.kind=='source' and r.arxiv_id in wanted]
        original_check, original_link = m1.verified_source, Path.is_symlink
        # Cache immutable ancestor link metadata only for this locked read-only
        # report; restore global methods even when an exception interrupts it.
        Path.is_symlink = lru_cache(maxsize=None)(original_link)
        results = {}
        try:
            print(f'Checking {len(sources)} Version receipts and file checksums...',flush=True)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(original_check,p):p for p in sources}
                for n,future in enumerate(as_completed(futures),1):
                    results[futures[future]] = future.result()
                    if n%500==0:
                        print(f'Checked {n}/{len(sources)} Versions',flush=True)
            m1.verified_source = lambda p: results.get(Path(p))
            print('Checking metadata/references and exported Parquet tables...',flush=True)
            result = m1.snapshot(cache,ids,member=member)
        finally:
            m1.verified_source, Path.is_symlink = original_check, original_link
        result['provenance']['report_command'] = 'python -m scripts.report_m1'
        result['provenance']['source_check'] = 'Fresh SHA-256 checks; parallel local disk I/O only; no API calls'
        write_json(output,result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--start',required=True,help='Inclusive base ID, e.g. 2412.08848')
    parser.add_argument('--end',required=True,help='Inclusive base ID, e.g. 2412.13847')
    parser.add_argument('--member',default='hai')
    parser.add_argument('--workers',type=int,default=8,help='Local checksum I/O workers; never network workers')
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error('--workers must be positive')
    try:
        ids = parse_range(args.start,args.end).ids()
        result = report(args.cache,ids,member=args.member,output=args.output,workers=args.workers)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps({'counts':result['counts'],'tables':result['checks']['tables'],
        'verified_input_files':result['provenance']['verified_input_files'],
        'output':str(args.output)},ensure_ascii=False,indent=2),flush=True)
    tables = result['checks']['tables'].values()
    return int(any(not t.get('valid') or t.get('duplicate_keys') or t.get('outside_range') for t in tables))


if __name__=='__main__':
    raise SystemExit(main())
