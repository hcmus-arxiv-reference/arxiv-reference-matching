"""Semantic Scholar paginated references, transactional per-page resume.

Contract: https://api.semanticscholar.org/api-docs/graph
publicationDate is retained as publication_date, never arXiv submission date.
"""
import json
import logging
from urllib.parse import quote, urlencode
from .crawler import Client


def make_client(user_agent, key):
    if not key:
        raise ValueError('S2_API_KEY is required for this workflow; set it in Secrets')
    return Client(user_agent, origin='https://api.semanticscholar.org', interval=1.1,
                  headers={'x-api-key': key})


def crawl_references(store, client, identifier, page_size=100):
    """Store all references, including unresolved/non-arXiv ones, by position."""
    db = store.db
    with db:
        db.execute("INSERT OR IGNORE INTO reference_jobs(arxiv_id,status) VALUES (?,'pending')", (identifier,))
    job = db.execute('SELECT * FROM reference_jobs WHERE arxiv_id=?', (identifier,)).fetchone()
    if job['status'] == 'complete':
        return 'complete'
    offset = job['next_offset']
    try:
        while True:
            with db:
                db.execute("UPDATE reference_jobs SET attempts=attempts+1,status='running',error=NULL WHERE arxiv_id=?", (identifier,))
            url = 'https://api.semanticscholar.org/graph/v1/paper/' + quote('ARXIV:' + identifier, safe=':') + '/references?'
            url += urlencode({'fields': 'paperId,externalIds,title,authors,publicationDate', 'offset': offset, 'limit': page_size})
            payload = json.loads(client.get(url))
            if not isinstance(payload.get('data'), list):
                raise ValueError('Invalid references response: missing data list')
            next_offset = payload.get('next')
            if next_offset is not None and (not isinstance(next_offset, int) or next_offset <= offset):
                raise ValueError('Non-advancing pagination')
            with db:
                for index, edge in enumerate(payload['data'], offset):
                    paper = edge.get('citedPaper') or {}
                    external = paper.get('externalIds') or {}
                    db.execute('INSERT OR REPLACE INTO s2_references VALUES (?,?,?,?,?,?)',
                        (identifier, index, paper.get('paperId'), external.get('ArXiv'), paper.get('title'), paper.get('publicationDate')))
                    db.execute('DELETE FROM reference_authors WHERE arxiv_id=? AND reference_position=?', (identifier, index))
                    db.executemany('INSERT INTO reference_authors VALUES (?,?,?,?)',
                        [(identifier, index, i, author.get('name')) for i, author in enumerate(paper.get('authors') or [])])
                status = 'complete' if next_offset is None else 'pending'
                db.execute('UPDATE reference_jobs SET status=?,next_offset=?,error=NULL WHERE arxiv_id=?',
                    (status, next_offset if next_offset is not None else offset + len(payload['data']), identifier))
            if next_offset is None:
                logging.getLogger(__name__).info('%s references complete: %d records', identifier, offset + len(payload['data']))
                return 'complete'
            offset = next_offset
    except Exception as error:
        with db:
            db.execute("UPDATE reference_jobs SET status='error',error=? WHERE arxiv_id=?", (f'{type(error).__name__}: {error}', identifier))
        raise
