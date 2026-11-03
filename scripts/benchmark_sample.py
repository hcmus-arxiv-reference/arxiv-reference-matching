"""Measure the original crawler on a fresh ten-ID local sample, never old caches."""
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import threading
import time
from urllib.error import HTTPError

import psutil
from filelock import FileLock

from src.common.config import get_settings, load_env
from src.crawl import source as source_module
from src.crawl.semantic_scholar import reference_rows
from src.crawl.split import make_pipeline
from src.crawl.storage import write_json
from src.crawl.source import verified_source


def summarize(pipeline, ids):
    """Count verified output after timing; include non-TeX Versions as valid."""
    counts = dict(publications_found=0,publications_complete=0,versions_expected=0,
                  versions_ok=0,versions_non_tex=0,versions_failed=0,
                  references_total=0,references_with_arxiv_id=0,publications_s2_ok=0)
    for identifier in ids:
        try:
            publication = pipeline._load_publication(identifier)
        except (OSError,ValueError,KeyError,TypeError):
            continue
        counts['publications_found'] += 1
        counts['versions_expected'] += publication.versions
        complete = True
        for version in range(1,publication.versions+1):
            record = pipeline.manifest.get(identifier,version)
            result = verified_source(pipeline.sources.root/identifier.replace('.','-')/f'v{version}')
            if result and record and result.status==record.status and result.checksum==record.checksum:
                counts['versions_ok'] += 1
                counts['versions_non_tex'] += int(result.status=='non_tex')
            else:
                complete = False
        try:
            rows = pipeline._load_references(identifier)
            counts['publications_s2_ok'] += 1
            counts['references_total'] += len(rows)
            counts['references_with_arxiv_id'] += sum(bool(((r.get('citedPaper') or {}).get('externalIds') or {}).get('ArXiv')) for r in rows)
            counts['publications_complete'] += int(complete)
        except (OSError,ValueError,KeyError,TypeError):
            pass
    counts['versions_failed'] = counts['versions_expected']-counts['versions_ok']
    return counts


def measure_call(stats, name, function):
    """Include rate-limit/backoff waiting in the stage's wall time."""
    def measured(*args, **kwargs):
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            stats[name]['seconds'] += time.perf_counter() - started
    return measured


def instrument_client(client, stats, choose_stage):
    """Count real transport attempts; cache hits never reach this wrapper."""
    original_get, original_transport = client.get, client._transport
    context = {'stage': None, 'attempt': 0}
    def transport(request, timeout):
        stage = stats[context['stage']]
        stage['requests'] += 1
        stage['retries'] += int(context['attempt'] > 0)
        context['attempt'] += 1
        try:
            response = original_transport(request, timeout)
            if response.status >= 400:
                stage['errors_by_type'][str(response.status)] += 1
            return response
        except Exception as error:
            label = str(error.code) if isinstance(error, HTTPError) else type(error).__name__
            stage['errors_by_type'][label] += 1
            raise
    def get(url):
        context.update(stage=choose_stage(url), attempt=0)
        return original_get(url)
    client._transport, client.get = transport, get


def disk_bytes(root):
    total = 0
    for directory, _, names in os.walk(root):
        for name in names:
            try:
                total += (Path(directory)/name).stat().st_size
            except FileNotFoundError:
                pass
    return total


def main():
    repo = Path(__file__).resolve().parents[1]
    load_env(repo/'.env')
    settings = get_settings()
    settings.user_agent()
    tag = datetime.now(timezone(timedelta(hours=7))).strftime('%Y%m%d-%H%M%S')
    evidence = repo/'data'/f'sample10-{tag}'
    output = evidence/'output'
    evidence.mkdir(parents=True)
    ids = [f'2412.{i:05d}' for i in range(8848,8858)]
    stats = {name: {'seconds':0.0, 'requests':0, 'retries':0, 'errors_by_type':Counter()}
             for name in ('discovery','source','references')}
    stats['export'] = {'seconds':0.0}
    retained = {'before':0,'after':0,'successful_payloads':0}
    pipeline = make_pipeline(replace(settings,data_dir=output), 's2')
    references = pipeline.references
    instrument_client(pipeline.sources.client, stats,
                      lambda url: 'source' if '/src/' in url else 'discovery')
    instrument_client(references.client, stats, lambda _: 'references')
    for obj, name, stage in [(pipeline.discovery,'prefetch','discovery'),
                             (pipeline.discovery,'discover','discovery'),
                             (pipeline.sources,'download','source'),
                             (references,'references','references'),
                             (pipeline,'export','export')]:
        setattr(obj,name,measure_call(stats,stage,getattr(obj,name)))
    extraction = source_module.extract_source
    def extract(payload, destination):
        result = extraction(payload,destination)
        raw = gzip.decompress(payload) if payload.startswith(b'\x1f\x8b') else payload
        try:
            with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
                size = sum(m.size for m in archive if m.isfile())
        except tarfile.ReadError:
            size = len(raw)
        retained['before'] += size
        retained['after'] += sum((destination/name).stat().st_size for group in result for name in group)
        retained['successful_payloads'] += 1
        return result
    source_module.extract_source = extract
    stop = threading.Event()
    samples = []
    started = time.perf_counter()
    started_at = datetime.now(timezone(timedelta(hours=7))).isoformat()
    process = psutil.Process()
    def sample():
        with (evidence/'samples.csv').open('w',newline='',encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['elapsed_seconds','tree_rss_bytes','output_bytes'])
            while True:
                rss = 0
                for p in [process,*process.children(recursive=True)]:
                    try:
                        rss += p.memory_info().rss
                    except psutil.Error:
                        pass
                row = [time.perf_counter()-started,rss,disk_bytes(output)]
                samples.append(row)
                writer.writerow(row)
                stream.flush()
                if stop.wait(1):
                    break
    sampler = threading.Thread(target=sample,daemon=True)
    sampler.start()
    failure = None
    try:
        with FileLock(str(repo/'data/.sample-crawl.lock'),timeout=0), \
             FileLock(str(repo/'data/local-sequential/.local-run.lock'),timeout=0):
            print('Cold run:', ids[0], 'through', ids[-1], flush=True)
            pipeline.references = None
            pipeline.discovery.prefetch(ids)
            pipeline.crawl_ids(ids)
            pipeline.references = references
            for identifier in ids:
                try:
                    rows = references.references(identifier)
                    reference_rows(identifier,rows)
                    path = pipeline._references_path(identifier)
                    write_json(path,{'format':1,'arxiv_id':identifier,'rows':rows})
                    pipeline._record(identifier,None,'references','success',
                        checksum=hashlib.sha256(path.read_bytes()).hexdigest(),local_path=str(path))
                except Exception as error:
                    pipeline._failure(identifier,None,'references',error)
                    print('S2 failed:',identifier,type(error).__name__,getattr(error,'status',None),flush=True)
            with FileLock(str(output/'.crawl.lock'),timeout=0):
                pipeline.export(ids)
    except BaseException as error:
        failure = type(error).__name__
    finally:
        wall = time.perf_counter()-started
        stop.set()
        sampler.join()
        source_module.extract_source = extraction
    template = json.loads((repo/'docs/benchmark/benchmark.template.json').read_text(encoding='utf-8'))
    template.update(member='ngochai06',branch='Hai_crawler',
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
        range={'prefix':'2412','start':8848,'end':8857}, ids_attempted=10)
    template['run'] = dict(cold_run=True,resumed_passes=0,started_at=started_at,
        finished_at=datetime.now(timezone(timedelta(hours=7))).isoformat(),
        machine=f'{platform.platform()}; {platform.machine()}; {psutil.cpu_count()} logical CPUs; {psutil.virtual_memory().total/1024**3:.2f} GiB RAM',
        python=platform.python_version(),s2_api_key=bool(settings.s2_api_key),
        measured_by='scripts.benchmark_sample; psutil process-tree RSS and output disk sampled every 1s; transport attempts and per-stage perf_counter')
    template['stages'] = stats
    template['totals'] = {name:None for name in template['totals']}
    template['totals'].update(wall_seconds=wall,peak_rss_mb=max(r[1] for r in samples)/1024**2,
        avg_rss_mb=sum(r[1] for r in samples)/len(samples)/1024**2,
        peak_disk_mb=max([r[2] for r in samples]+[disk_bytes(output)])/1024**2,
        output_mb=disk_bytes(output)/1024**2,
        bytes_before_figure_removal=retained['before'],bytes_after_figure_removal=retained['after'])
    template['totals'].update(summarize(pipeline,ids))
    template['notes'] = (f'Fresh local sample only, NOT historical 5000-ID totals or common Colab comparison. Output: {output.relative_to(repo).as_posix()}. '
        'Original crawler code restored before run; instrumentation wraps calls without altering HTTP intervals/retry policy. '
        'Archive sizes are measured on successful extraction payloads (regular tar members, otherwise decompressed payload bytes); retained bytes count TeX/BibTeX only. '
        'Sampling thread is included in process-tree RSS; final disk sample includes export. Wrapper/archive measurement adds small instrumentation overhead. '
        f'Run-level exception: {failure}. No old cache imported. Historical benchmark remains benchmarks/ngochai06.json.')
    path = repo/'benchmarks/ngochai06-sample10.json'
    write_json(path,template)
    write_json(evidence/'measurement.json',{'benchmark':str(path),'output':str(output),'sample_count':len(samples),'failure':failure})
    print('MEASUREMENT_READY',evidence,flush=True)
    print(json.dumps({'wall_seconds':wall,'stages':stats,'failure':failure},indent=2),flush=True)
    return bool(failure)


if __name__ == '__main__':
    sys.exit(main())
