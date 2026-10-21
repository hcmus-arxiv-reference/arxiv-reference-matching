import gzip, io, tarfile, json
from pathlib import Path
import pytest
from src.source import extract_source, ArxivSourceDownloader, verified_source
from src.http_client import HttpResponse
from src.metadata import parse
from src.references import fetch
from src.storage import read_json, key, write_json

class Client:
    def __init__(self, responses): self.responses=iter(responses);self.calls=0
    def get(self,url): self.calls+=1;return next(self.responses)

def test_extract_preserves_commands_and_paths(tmp_path):
    b=io.BytesIO()
    with tarfile.open(fileobj=b,mode='w:gz') as t:
        for n,body in [('chap/main.tex',b'\\includegraphics{image}'),('refs.bib',b'@article{x}'),('image.png',b'PNG'),('../bad.tex',b'bad')]:
            m=tarfile.TarInfo(n);m.size=len(body);t.addfile(m,io.BytesIO(body))
    tex,bib=extract_source(b.getvalue(),tmp_path)
    assert tex==['chap/main.tex'] and bib==['refs.bib']
    assert (tmp_path/'chap/main.tex').read_bytes()==b'\\includegraphics{image}'
    assert not (tmp_path/'image.png').exists()

@pytest.mark.parametrize('body',[b'<html>error</html>',gzip.compress(b'<html>error</html>'),b'random text'])
def test_error_is_not_tex(body,tmp_path):
    with pytest.raises(ValueError):extract_source(body,tmp_path)

def test_pdf_empty(tmp_path): assert extract_source(b'%PDF-1.5',tmp_path)==([],[])

def test_resume_checks_checksum(tmp_path):
    payload=b'\\documentclass{article} Hello'
    c=Client([HttpResponse(200,{},payload),HttpResponse(200,{},payload)])
    d=ArxivSourceDownloader(c,tmp_path)
    assert not d.download('2409.08594',1).cached
    assert d.download('2409.08594',1).cached
    (tmp_path/'2409-08594/v1/single.tex').write_text('corrupt')
    assert not d.download('2409.08594',1).cached
    assert c.calls==2

def test_s2_pagination_and_resume(tmp_path):
    c=Client([HttpResponse(200,{},json.dumps({'data':[{'citedPaper':{'paperId':'x'}}],'next':1}).encode()),HttpResponse(200,{},b'{"data":[]}')])
    assert len(fetch(c,'2409.08594',tmp_path)['rows'])==1
    fetch(c,'2409.08594',tmp_path);assert c.calls==2

def test_s2_failure_not_cached(tmp_path):
    c=Client([HttpResponse(429,{},b'')])
    with pytest.raises(RuntimeError):fetch(c,'2409.08594',tmp_path)
    assert not (tmp_path/'references/2409-08594.json').exists()

def test_atom_versions():
    body=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2409.08594v3</id><title>T</title><author><name>A</name></author><published>2024-09-01T00:00:00Z</published></entry></feed>'
    assert parse(body)['2409.08594']['versions']==3

def test_end_to_end_offline(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src import crawl
    import pyarrow.parquet as pq
    atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2409.08594v1</id><title>Fixture only</title><author><name>A</name></author><published>2024-09-01T00:00:00Z</published></entry></feed>'
    class Fake:
        def __init__(self,*a,**kw):pass
        def get(self,url):
            if '/api/query' in url:return HttpResponse(200,{},atom)
            if '/src/' in url:return HttpResponse(200,{},b'\\documentclass{article} Test.')
            return HttpResponse(200,{},b'{"data":[{"citedPaper":{"paperId":"x","title":"Ref","externalIds":{"ArXiv":"1706.03762"},"authors":[{"name":"A"}]}}]}')
    monkeypatch.setattr(crawl,'HttpClient',Fake);monkeypatch.chdir(tmp_path)
    args=SimpleNamespace(data_dir=tmp_path/'data',refresh=False)
    args.data_dir.mkdir()
    crawl.run(args,['2409.08594'],'fixture@example.com','fake-key')
    summary=read_json(tmp_path/'outputs/summary.json')
    assert summary['complete_publications']==1
    assert summary['expected_versions']==1
    assert summary['ref_submission_dates_missing']==1
    table=pq.read_table(tmp_path/'data/tables/references/part-00000.parquet')
    assert table.to_pylist()[0]['ref_authors']==['A']
    # Simulate S2 failing after refresh: must not claim full completion.
    class FailedS2(Fake):
        def get(self,url):
            if 'semanticscholar' in url:return HttpResponse(503,{},b'')
            return super().get(url)
    monkeypatch.setattr(crawl,'HttpClient',FailedS2);args.refresh=True
    crawl.run(args,['2409.08594'],'fixture@example.com','fake-key')
    assert read_json(tmp_path/'outputs/summary.json')['complete_publications']==0
