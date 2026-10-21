"""Run one sequential arXiv worker and one independent S2 worker."""
import argparse, os, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from filelock import FileLock
from .http_client import HttpClient
from .source import ArxivSourceDownloader
from .metadata import discover
from .references import fetch
from .storage import key, read_json, write_json

def main():
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    p=argparse.ArgumentParser()
    p.add_argument('--start',type=int,default=8594); p.add_argument('--end',type=int,default=13593)
    p.add_argument('--month',default='2409'); p.add_argument('--limit',type=int)
    p.add_argument('--data-dir',type=Path,default=Path('data')); p.add_argument('--refresh',action='store_true')
    a=p.parse_args()
    if a.start<1 or a.end<a.start or a.end>99999 or len(a.month)!=4 or not a.month.isdigit(): p.error('Invalid range')
    if a.limit is not None and a.limit<1: p.error('--limit must be positive')
    email=os.getenv('CONTACT_EMAIL','').strip(); secret=os.getenv('S2_API_KEY','').strip()
    if not email or not secret: p.error('Set CONTACT_EMAIL and S2_API_KEY in .env first')
    ids=[f'{a.month}.{i:05d}' for i in range(a.start,a.end+1)][:a.limit]
    a.data_dir.mkdir(parents=True,exist_ok=True)
    with FileLock(str(a.data_dir/'.run.lock'),timeout=0):
        run(a,ids,email,secret)

def run(a,ids,email,secret):
    started=time.perf_counter(); stamp=datetime.now(timezone.utc).isoformat()
    arxiv=HttpClient(f'IntroDS-M1/1.0 (mailto:{email})',min_interval=3.1)
    s2=HttpClient(f'IntroDS-M1/1.0 (mailto:{email})',min_interval=1.1,headers={'x-api-key':secret})
    downloader=ArxivSourceDownloader(arxiv,a.data_dir/'raw')
    write_json(a.data_dir/'assignment.json',{'ids':ids,'started_at':stamp})
    dt=time.perf_counter(); discovery_errors=discover(arxiv,ids,a.data_dir,a.refresh)
    discovery_seconds=time.perf_counter()-dt
    write_json(a.data_dir/'discovery_errors.json',discovery_errors)
    valid=[pid for pid in ids if pid not in discovery_errors]
    def s2_worker():
        for pid in valid:
            t=time.perf_counter()
            try: fetch(s2,pid,a.data_dir,a.refresh); status='success'; error=None
            except Exception as e: status='error'; error=str(e)
            write_json(a.data_dir/'s2_status'/f'{key(pid)}.json',dict(status=status,error=error,seconds=time.perf_counter()-t,started_monotonic=t,finished_monotonic=time.perf_counter(),run_id=stamp))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(s2_worker)
        for i,pid in enumerate(valid,1):
            t=time.perf_counter(); meta=read_json(a.data_dir/'metadata'/f'{key(pid)}.json'); states=[]
            for version in range(1,meta['versions']+1):
                vt=time.perf_counter()
                try:
                    r=downloader.download(pid,version)
                    state=dict(version=version,status=r.status,cached=r.cached,error=None)
                except Exception as e:
                    state=dict(version=version,status='error',cached=False,error=type(e).__name__)
                state['seconds']=time.perf_counter()-vt; states.append(state)
                write_json(a.data_dir/'status'/f'{key(pid)}.json',{'arxiv_id':pid,'versions':states,'seconds':time.perf_counter()-t,'started_monotonic':t,'finished_monotonic':time.perf_counter(),'run_id':stamp})
            print(f'Sources {i}/{len(valid)} {pid}: '+','.join(s['status'] for s in states),flush=True)
        future.result()
    write_json(a.data_dir/'last_run.json',dict(started_at=stamp,requested=len(ids),discovery_seconds=discovery_seconds,
        wall_seconds=time.perf_counter()-started,refresh=a.refresh))
    from .analyze import analyze
    summary=analyze(a.data_dir,Path('outputs'))
    print(summary)
    print('Resume/retry by running the same command. API keys were not written to outputs.')

if __name__=='__main__': main()
