"""Optional arXiv verification of reference submission dates (additional API calls)."""
import argparse, os, re
from pathlib import Path
from dotenv import load_dotenv
from filelock import FileLock
from .storage import read_json, write_json, key
from .metadata import query
from .http_client import HttpClient

def main():
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,default=Path('data'));a=p.parse_args()
    email=os.getenv('CONTACT_EMAIL','')
    if not email:p.error('CONTACT_EMAIL is required')
    client=HttpClient(f'IntroDS-M1/1.0 (mailto:{email})',min_interval=3.1)
    with FileLock(str(a.data_dir/'.run.lock'),timeout=0):
        dates=read_json(a.data_dir/'reference_dates.json') or {};ids=set()
        for path in (a.data_dir/'references').glob('*.json'):
            for row in (read_json(path) or {}).get('rows',[]):
                value=((row.get('citedPaper') or {}).get('externalIds') or {}).get('ArXiv')
                if value:
                    value=re.sub(r'v\d+$','',value)
                    try:key(value);ids.add(value)
                    except ValueError:pass
        pending=sorted(ids-set(dates));errors={}
        for i in range(0,len(pending),50):
            chunk=pending[i:i+50]
            try:
                rows=query(client,chunk)
                for pid in chunk:
                    if pid in rows and rows[pid]['submission_date']: dates[pid]=rows[pid]['submission_date']
                    else:errors[pid]='Metadata not returned'
            except Exception as e:
                errors.update({pid:type(e).__name__ for pid in chunk})
            write_json(a.data_dir/'reference_dates.json',dates)
            print(f'Reference dates {min(i+50,len(pending))}/{len(pending)}',flush=True)
        write_json(a.data_dir/'reference_date_errors.json',errors)
    from .analyze import analyze
    analyze(a.data_dir,Path('outputs'))
if __name__=='__main__':main()
