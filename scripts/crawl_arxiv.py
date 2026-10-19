"""Run a small sample by default; --limit 5000 explicitly selects the full range."""
import argparse
import json
import time
import logging
from datetime import datetime, timezone
from itertools import islice
from src.common.config import ArxivRange, get_settings
from src.crawl.crawler import Client, Crawler, save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', default='2412')
    parser.add_argument('--start', type=int, default=8848)
    parser.add_argument('--end', type=int, default=13847)
    parser.add_argument('--limit', type=int, default=3)
    parser.add_argument('--output', default='data/crawl_hai')
    parser.add_argument('--batch-size', type=int, default=25)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    if not 1 <= args.batch_size <= 100:
        parser.error('--batch-size must be between 1 and 100')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    client = Client(get_settings().user_agent())
    crawler = Crawler(args.output, client)
    started = time.monotonic()
    results = []
    identifiers = list(islice(ArxivRange(args.prefix, args.start, args.end).ids(), args.limit))
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    def snapshot():
        summary = dict(results=results, requests=client.requests,
                       download_bytes=client.download_bytes, http_seconds=client.http_seconds,
                       wall_seconds=time.monotonic() - started)
        save_json(crawler.root / 'run_summary.json', summary)
        save_json(crawler.root / 'runs' / (run_id + '.json'), summary)
    for index, identifier in enumerate(identifiers):
        if index % args.batch_size == 0:
            batch = identifiers[index:index + args.batch_size]
            crawler.prefetch(batch, args.batch_size)
            older = []
            for item in batch:
                path = crawler.metadata_path(item)
                if path.exists():
                    latest = json.loads(path.read_text(encoding='utf-8'))
                    older.extend(f'{item}v{n}' for n in range(1, latest['version']))
            crawler.prefetch(older, args.batch_size)
        logging.info('Publication %d/%d: %s', index + 1, len(identifiers), identifier)
        try:
            records = crawler.publication(identifier)
        except Exception as error:
            records = [dict(arxiv_id=identifier, status='discovery_error', error=f'{type(error).__name__}: {error}')]
        results.extend(records)
        print(identifier, [r['status'] for r in records], flush=True)
        snapshot()
    print(json.dumps(dict(requests=client.requests, wall_seconds=time.monotonic() - started)))
    return 1 if any(r['status'] in ('error', 'discovery_error') for r in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
