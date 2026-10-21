"""Publication-level Semantic Scholar references, with full pagination."""
import json
from urllib.parse import quote, urlencode
from .storage import key, write_json, read_json

def fetch(client, pid, root, refresh=False):
    path = root/'references'/f'{key(pid)}.json'
    old = read_json(path)
    if not refresh and old and old.get('status')=='success' and old.get('arxiv_id')==pid:
        return old
    rows=[]; offset=0
    while True:
        params=urlencode({'fields':'paperId,externalIds,title,authors,publicationDate,year,venue','limit':1000,'offset':offset})
        r=client.get(f'https://api.semanticscholar.org/graph/v1/paper/ARXIV:{quote(pid,safe="")}/references?{params}')
        if r.status != 200: raise RuntimeError(f'Semantic Scholar HTTP {r.status}')
        obj=json.loads(r.body)
        if not isinstance(obj.get('data'),list): raise ValueError('Invalid reference page')
        rows.extend(obj['data']); nxt=obj.get('next')
        if nxt is None: break
        if type(nxt)!=int or nxt<=offset: raise ValueError('Invalid pagination')
        offset=nxt
    value={'arxiv_id':pid,'status':'success','rows':rows}
    write_json(path,value); return value
