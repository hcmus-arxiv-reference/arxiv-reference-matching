"""Notebook-friendly M1 runner; SQLite owns progress and metadata."""
import logging
from pathlib import Path
import time
from .crawler import Client, Crawler
from .store import Store
from .semantic import make_client, crawl_references

LOG = logging.getLogger(__name__)


def snapshot(root, destination):
    """Bundle a consistent database backup and retained sources between runs."""
    import tempfile
    import zipfile
    root, destination = Path(root), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    store = Store(root / 'crawl.sqlite')
    try:
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            database = Path(temporary) / 'crawl.sqlite'
            store.backup(database)
            staging = destination.with_suffix('.partial')
            with zipfile.ZipFile(staging, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.write(database, 'crawl.sqlite')
                for path in root.glob('*/v*/source/**/*'):
                    if path.is_file():
                        archive.write(path, path.relative_to(root).as_posix())
                for path in (root / 'exports').glob('*.parquet'):
                    archive.write(path, path.relative_to(root).as_posix())
            staging.replace(destination)
    finally:
        store.close()
    return str(destination)


def run(root, identifiers, user_agent, s2_key, batch_size=25):
    """Run bounded IDs, retain partial successes, retry failures on next run."""
    root = Path(root)
    store = Store(root / 'crawl.sqlite')
    arxiv = Client(user_agent)
    semantic = make_client(user_agent, s2_key)
    crawler = Crawler(root, arxiv, store)
    started = time.monotonic()
    errors = []
    with store.db:
        run_id = store.db.execute("INSERT INTO runs(status) VALUES ('running')").lastrowid
    status = 'interrupted'
    try:
        store.import_legacy(root)
        for start in range(0, len(identifiers), batch_size):
            batch = identifiers[start:start + batch_size]
            crawler.prefetch(batch, batch_size)
            older = []
            for identifier in batch:
                latest = store.get_metadata(identifier)
                if latest:
                    older.extend(f'{identifier}v{v}' for v in range(1, latest['version']))
            crawler.prefetch(older, batch_size)
            for identifier in batch:
                LOG.info('Publication %s', identifier)
                try:
                    records = crawler.publication(identifier)
                    errors.extend(f"{identifier}v{r['version']}: {r.get('error')}" for r in records if r['status'] == 'error')
                except Exception as error:
                    errors.append(f'{identifier} arXiv: {type(error).__name__}: {error}')
                    LOG.exception('arXiv failed')
                try:
                    crawl_references(store, semantic, identifier)
                except Exception as error:
                    errors.append(f'{identifier} S2: {type(error).__name__}: {error}')
                    LOG.error('References failed: %s', error)
        status = 'errors' if errors else 'complete'
        return {'arxiv_requests': arxiv.requests, 's2_requests': semantic.requests,
                'wall_seconds': time.monotonic() - started, 'errors': errors}
    finally:
        with store.db:
            store.db.execute('UPDATE runs SET status=?,wall_seconds=?,arxiv_requests=?,s2_requests=? WHERE id=?',
                (status, time.monotonic() - started, arxiv.requests, semantic.requests, run_id))
            store.db.executemany('INSERT INTO run_errors VALUES (?,?)', [(run_id, error) for error in errors])
        store.close()


def export_tables(root, identifiers=None):
    """Export complete records to the existing, validated M1 schemas."""
    from src.common.schema import from_records, write_table
    root = Path(root)
    store = Store(root / 'crawl.sqlite')
    papers, references = [], []
    selected = set(identifiers) if identifiers is not None else None
    try:
        for row in store.db.execute("SELECT cache_key FROM metadata WHERE cache_key=arxiv_id").fetchall():
            metadata = store.get_metadata(row[0])
            identifier = metadata['arxiv_id']
            if selected is not None and identifier not in selected:
                continue
            versions = [store.get_metadata(f'{identifier}v{v}') for v in range(1, metadata['version'] + 1)]
            if any(value is None for value in versions):
                raise ValueError(f'Incomplete version metadata: {identifier}')
            papers.append(dict(arxiv_id=identifier, title=metadata['title'], authors=metadata['authors'],
                submission_date=versions[0]['submission_date'], revised_dates=[v['updated'] for v in versions[1:]], venue=metadata['venue']))
        seen = set()
        for row in store.db.execute("SELECT r.* FROM s2_references r JOIN reference_jobs j USING(arxiv_id) WHERE j.status='complete' AND r.ref_arxiv_id IS NOT NULL ORDER BY r.arxiv_id,r.position"):
            if selected is not None and row['arxiv_id'] not in selected:
                continue
            key = (row['arxiv_id'], row['ref_arxiv_id'])
            if key in seen:
                continue
            seen.add(key)
            authors = [a[0] for a in store.db.execute('SELECT name FROM reference_authors WHERE arxiv_id=? AND reference_position=? ORDER BY position', (row['arxiv_id'], row['position']))]
            references.append(dict(arxiv_id=key[0], ref_arxiv_id=key[1], ref_title=row['title'],
                ref_authors=authors, ref_submission_date=None, ref_s2_id=row['s2_id']))
        for name, records in [('papers', papers), ('references', references)]:
            write_table(from_records(records, name), name, root / 'exports' / (name + '.parquet'))
        return {'papers': len(papers), 'references': len(references)}
    finally:
        store.close()
