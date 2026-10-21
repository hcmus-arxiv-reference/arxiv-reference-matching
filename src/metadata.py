"""Batch Atom discovery; versioned requests recover revision dates."""
import re, time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from .storage import require_id, key, write_json, read_json
A = '{http://www.w3.org/2005/Atom}'
X = '{http://arxiv.org/schemas/atom}'

def parse(body):
    result = {}
    for e in ET.fromstring(body).findall(A+'entry'):
        identifier = e.findtext(A+'id', '')
        m = re.search(r'/abs/(.+)v(\d+)$', identifier)
        if not m: continue
        pid = require_id(m[1])
        def text(name):
            v = e.findtext(name)
            return ' '.join(v.split()) if v else None
        result[pid] = dict(arxiv_id=pid, title=text(A+'title'),
            authors=[a.findtext(A+'name') for a in e.findall(A+'author')],
            submission_date=text(A+'published'), updated=text(A+'updated'),
            venue=text(X+'journal_ref'), versions=int(m[2]))
    return result

def query(client, ids):
    r = client.get('https://export.arxiv.org/api/query?'+urlencode({'id_list': ','.join(ids), 'max_results':len(ids)}))
    if r.status != 200: raise RuntimeError(f'arXiv metadata HTTP {r.status}')
    return parse(r.body)

def discover(client, ids, root, refresh=False):
    """Only missing IDs are fetched; absent API rows remain explicit errors."""
    pending = []
    for pid in ids:
        cached = read_json(root/'metadata'/f'{key(pid)}.json')
        if refresh or not cached or cached.get('arxiv_id') != pid or len(cached.get('revised_dates', [])) != cached.get('versions', 0)-1:
            pending.append(pid)
    errors = {}
    for start in range(0, len(pending), 50):
        batch = pending[start:start+50]; t = time.perf_counter()
        try:
            rows = query(client, batch)
        except Exception as e:
            errors.update({p:type(e).__name__ for p in batch}); continue
        for pid in batch:
            try:
                row = rows[pid]; dates = []
                for v in range(2, row['versions']+1):
                    version = row if v == row['versions'] else query(client,[f'{pid}v{v}'])[pid]
                    if version['versions'] != v or not version['updated']: raise ValueError('Revision mismatch')
                    dates.append(version['updated'])
                row['revised_dates'] = dates
                write_json(root/'metadata'/f'{key(pid)}.json', row)
            except Exception as e: errors[pid] = type(e).__name__
        print(f'Discovery {min(start+50,len(pending))}/{len(pending)} ({time.perf_counter()-t:.1f}s)', flush=True)
    return errors
