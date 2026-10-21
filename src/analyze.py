"""Export metadata without dropping partial publications; summarize actual coverage."""
import argparse, re, json, shutil
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from .storage import read_json, write_json, key
from .source import verified_source

PAPER_SCHEMA=pa.schema([('arxiv_id',pa.string()),('title',pa.string()),('authors',pa.list_(pa.string())),('submission_date',pa.string()),('revised_dates',pa.list_(pa.string())),('venue',pa.string())])
REF_SCHEMA=pa.schema([('arxiv_id',pa.string()),('ref_arxiv_id',pa.string()),('ref_title',pa.string()),('ref_authors',pa.list_(pa.string())),('ref_submission_date',pa.string()),('ref_s2_id',pa.string())])

def analyze(root,out):
    out.mkdir(parents=True,exist_ok=True)
    assignment=read_json(root/'assignment.json')
    if not assignment: raise ValueError('Run crawler first: assignment.json missing')
    papers=[]; refs=[]; records=[]
    dates=read_json(root/"reference_dates.json") or {}
    for pid in assignment['ids']:
        meta=read_json(root/'metadata'/f'{key(pid)}.json')
        stat=read_json(root/'status'/f'{key(pid)}.json') or {}
        sr=read_json(root/'s2_status'/f'{key(pid)}.json') or {}
        ref=read_json(root/'references'/f'{key(pid)}.json') or {}
        expected=meta['versions'] if meta else 0
        ok=empty=before=after=downloaded=0
        for v in range(1,expected+1):
            path=root/'raw'/key(pid)/f'v{v}'
            receipt=verified_source(path)
            if receipt:
                ok+=receipt.status=='success'; empty+=receipt.status=='non_tex'
                sizes=read_json(path/'sizes.json') or {}
                before+=sizes.get('bytes_before',0); after+=sizes.get('bytes_after',0)
                downloaded+=(read_json(path/'source.json') or {}).get('bytes_downloaded',0)
        if meta: papers.append({n:meta.get(n) for n in PAPER_SCHEMA.names})
        dedup={}
        for raw in ref.get('rows',[]):
            r=raw.get('citedPaper') or {}; rid=(r.get('externalIds') or {}).get('ArXiv')
            if not rid: continue
            rid=re.sub(r'v\d+$','',rid)
            try: other=read_json(root/'metadata'/f'{key(rid)}.json')
            except ValueError: continue
            dedup[rid]=dict(arxiv_id=pid,ref_arxiv_id=rid,ref_title=r.get('title'),ref_authors=[x['name'] for x in (r.get('authors') or []) if x.get('name')],ref_submission_date=dates.get(rid) or (other.get('submission_date') if other else None),ref_s2_id=r.get('paperId'))
        refs.extend(dedup.values())
        records.append(dict(arxiv_id=pid,metadata_ok=bool(meta),expected_versions=expected,tex_versions=ok,non_tex_versions=empty,
            unresolved_versions=expected-ok-empty,references_ok=sr.get('status')=='success',references_total=len(ref.get('rows',[])),references_arxiv=len(dedup),
            bytes_before=before,bytes_after=after,bytes_downloaded=downloaded,source_seconds=stat.get('seconds',0),s2_seconds=sr.get('seconds',0),paper_span_seconds=(max(stat['finished_monotonic'],sr['finished_monotonic'])-min(stat['started_monotonic'],sr['started_monotonic'])) if stat.get('run_id') and stat.get('run_id')==sr.get('run_id') else None))
    df=pd.DataFrame(records);df.to_csv(out/'paper_stats.csv',index=False)
    for name,rows,schema in [('papers',papers,PAPER_SCHEMA),('references',refs,REF_SCHEMA)]:
        folder=root/'tables'/name;folder.mkdir(parents=True,exist_ok=True)
        for old in folder.glob('part-*.parquet'): old.unlink()
        for i in range(0,max(1,len(rows)),10000):
            pq.write_table(pa.Table.from_pylist(rows[i:i+10000],schema=schema),folder/f'part-{i//10000:05d}.parquet')
    total=len(df); complete=df.metadata_ok & (df.unresolved_versions==0) & df.references_ok
    summary=dict(assigned_ids=total,metadata_success=int(df.metadata_ok.sum()),complete_publications=int(complete.sum()),
        complete_rate=float(complete.mean()),expected_versions=int(df.expected_versions.sum()),tex_versions=int(df.tex_versions.sum()),
        non_tex_versions=int(df.non_tex_versions.sum()),unresolved_versions=int(df.unresolved_versions.sum()),
        reference_api_success=int(df.references_ok.sum()),reference_api_success_rate=float(df.references_ok.mean()),
        mean_references_successful=float(df.loc[df.references_ok,'references_total'].mean()) if df.references_ok.any() else None,
        mean_bytes_before_complete_sources=float(df.loc[df.metadata_ok & (df.unresolved_versions==0),'bytes_before'].mean()) if df.metadata_ok.any() else None,
        ref_submission_dates_missing=sum(r['ref_submission_date'] is None for r in refs),
        last_run=read_json(root/'last_run.json'))
    write_json(out/'summary.json',summary);return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,default=Path('data'));p.add_argument('--out',type=Path,default=Path('outputs'))
    a=p.parse_args();print(analyze(a.data_dir,a.out))
