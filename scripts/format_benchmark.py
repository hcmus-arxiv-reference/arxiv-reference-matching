"""Format measured Hai sample output using the supplied segment/profile layout."""
from collections import Counter
import csv
import json
import math
from pathlib import Path
import statistics

from src.common.schema import read_table, validate


def percentile(values, percent):
    """Linear interpolation, with the first and last observations at 0/100."""
    values = sorted(values)
    position = (len(values)-1)*percent/100
    lower, upper = math.floor(position), math.ceil(position)
    return values[lower] + (values[upper]-values[lower])*(position-lower)


def format_report(measurement, output, evidence):
    """Use only the indicated run: performance, cache files and exported tables."""
    output, evidence = Path(output), Path(evidence)
    total = measurement['totals']
    tables = {name:read_table(name,output/'tables'/f'{name}.parquet') for name in ('papers','references')}
    for name, table in tables.items():
        validate(table,name)
    papers = tables['papers'].to_pylist()
    references = tables['references'].to_pylist()
    complete_ids = {r['arxiv_id'] for r in papers}
    latest = {}
    for line in (output/'manifests/crawl.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        latest[(row['arxiv_id'],row.get('version'),row['kind'])] = row
    versions = Counter()
    for path in (output/'metadata').glob('*.json'):
        versions[json.loads(path.read_text(encoding='utf-8'))['publication']['versions']] += 1
    source_files = []
    for receipt in (output/'raw').glob('*/v*/source.json'):
        payload = json.loads(receipt.read_text(encoding='utf-8'))
        if payload['arxiv_id'] in complete_ids:
            source_files.extend(receipt.parent/name for name in payload['files'])
    source_bytes = sum(p.stat().st_size for p in source_files)
    categories = Counter()
    for path in output.rglob('*'):
        if path.is_file():
            relative = path.relative_to(output)
            categories[relative.parts[0] if len(relative.parts)>1 else 'root_files'] += path.stat().st_size
    assert sum(categories.values())/1024**2 == total['output_mb']
    assert len(papers)==total['publications_complete']
    per_paper = Counter(r['arxiv_id'] for r in references)
    values = [per_paper[i] for i in sorted(complete_ids)]
    assert values, 'No complete Publications available for the profile'
    with (evidence/'references_per_paper.csv').open('w',newline='',encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['arxiv_id','arxiv_reference_count'])
        writer.writerows((i,per_paper[i]) for i in sorted(complete_ids))
    statuses = Counter(r['status'] for r in latest.values() if r['kind']=='references')
    raw_rows = []
    for identifier in sorted(complete_ids):
        raw_rows.extend(json.loads((output/'references'/f"{identifier.replace('.','-')}.json").read_text(encoding='utf-8'))['rows'])
    raw_arxiv = sum(bool(((r.get('citedPaper') or {}).get('externalIds') or {}).get('ArXiv')) for r in raw_rows)
    assert len(raw_rows)==total['references_total'] and raw_arxiv==total['references_with_arxiv_id']
    histogram = Counter()
    for count in values:
        bucket = '0' if count==0 else '1-9' if count<10 else '10-24' if count<25 else '25-49' if count<50 else '50-99' if count<100 else '100+'
        histogram[bucket] += 1
    wall = total['wall_seconds']
    prefix = measurement['range']['prefix']
    missing = sum(not (output/'references'/f'{prefix}-{i:05d}.json').is_file()
                  for i in range(measurement['range']['start'],measurement['range']['end']+1))
    report = dict(segments=1,total_wall_seconds=round(wall,2),total_wall_hours=round(wall/3600,4),
        total_cooldown_seconds=0,wall_seconds_excl_cooldown=round(wall,2),
        peak_rss_mb=round(total['peak_rss_mb'],2),avg_rss_mb=round(total['avg_rss_mb'],2),
        peak_disk_mb=round(total['peak_disk_mb'],4),final_disk_mb=round(total['output_mb'],4),
        per_segment=[dict(name=evidence.name,wall_seconds=round(wall,2),peak_rss_mb=round(total['peak_rss_mb'],2),
            done_papers_at_start=0,done_papers_at_end=len(papers),cooldown_seconds=0,
            ended='complete' if len(papers)==measurement['ids_attempted'] else 'incomplete')])
    report['measurement_scope'] = dict(source_files=[
        'benchmarks/ngochai06-sample10.json', f'data/{evidence.name}/samples.csv',
        f'data/{evidence.name}/validation-report.json',f'data/{evidence.name}/references_per_paper.csv',
        f'data/{evidence.name}/output/manifests/crawl.jsonl',f'data/{evidence.name}/output/tables/*.parquet'],
        member=measurement['member'],branch=measurement['branch'],commit=measurement['commit'],
        range=measurement['range'],run=measurement['run'],
        timing='One measured cold local 10-ID run; not a 5000-ID full-range runtime. Wall excludes post-run validation.',
        disk='Actual end-of-run logical output bytes; peak sampled every second and includes final output.',
        ram='Process-tree RSS sampled every second; avg is the arithmetic mean of samples.',
        cooldown='Zero inter-pass cooldown: one pass only. HTTP rate-limit and retry/backoff waits remain included in wall and stages.',
        profiles='Source and reference profiles use complete exported Publications; Version distribution uses all discovered Publications.',
        unit_note='Legacy *_mb fields use MiB (1024^2 bytes), matching the original measurement; seconds rounded to 2 decimals.')
    report['run_details'] = [dict(name=evidence.name,elapsed_seconds=round(wall,2),elapsed_hours=round(wall/3600,4),
        passes=1,status=report['per_segment'][0]['ended'])]
    report['disk_snapshot'] = dict(total_bytes=sum(categories.values()),total_mib=round(sum(categories.values())/1024**2,4),
        by_category={k:dict(bytes=v,mib=round(v/1024**2,4)) for k,v in sorted(categories.items())})
    report['crawl_summary'] = dict(requested_papers=measurement['ids_attempted'],completed_papers=len(papers),
        incomplete_papers=measurement['ids_attempted']-len(papers),success_rate_percent=100*len(papers)/measurement['ids_attempted'],
        total_versions=total['versions_expected'],average_versions_per_paper=total['versions_expected']/total['publications_found'],
        version_distribution={str(k):v for k,v in sorted(versions.items())},total_arxiv_references=len(references),
        average_arxiv_references_per_paper=statistics.mean(values),median_arxiv_references=statistics.median(values),
        max_arxiv_references=max(values),papers_without_arxiv_references=values.count(0))
    report['source_profile'] = dict(papers_analyzed=len(papers),tex_files=sum(p.suffix.lower()=='.tex' for p in source_files),
        bib_files=sum(p.suffix.lower()=='.bib' for p in source_files),total_tex_bib_files=len(source_files),
        total_extracted_bytes=source_bytes,total_extracted_mib=round(source_bytes/1024**2,4),
        average_extracted_bytes_per_paper=source_bytes/len(papers))
    report['reference_profile'] = dict(raw_semantic_scholar_references=len(raw_rows),references_with_arxiv_id=raw_arxiv,
        arxiv_id_coverage_percent=100*raw_arxiv/len(raw_rows) if raw_rows else 0,
        average_raw_references_per_paper=len(raw_rows)/len(papers),missing_reference_files=missing,
        reference_api_statuses=dict(statuses),reference_api_success_rate_percent=100*statuses['success']/sum(statuses.values()),
        reference_counts_from_csv=dict(rows=len(values),total=sum(values),mean=statistics.mean(values),median=statistics.median(values),
            min=min(values),max=max(values),zero_reference_papers=values.count(0),
            percentiles={str(p):percentile(values,p) for p in (25,50,75,90,95,99)},
            count_buckets={k:histogram[k] for k in ('0','1-9','10-24','25-49','50-99','100+')}))
    report['data_validation'] = {name:dict(rows=t.num_rows,validation_errors=[],null_counts={n:t[n].null_count for n in t.column_names})
                                 for name,t in tables.items()}
    report['data_validation']['cross_table'] = dict(unknown_citing_ids=sorted({r['arxiv_id'] for r in references}-complete_ids))
    report['data_quality_notes'] = [
        'Only 10 IDs from Hai crawler were measured. No numbers copied from nghiem.json.',
        '9/10 Publications complete; 2412.08852 lacks S2 after HTTP 429. All 15 expected source Versions valid, including one non-TeX.',
        '15 HTTP 429 responses and 14 retries are HTTP attempts, not 15 failed Publications.',
        'ref_submission_date remains null; S2 publicationDate is not mapped to arXiv submission date.',
        'Zero arXiv-reference counts on successful S2 responses do not imply API failure.',
        'First ~130 seconds overlapped separate offline test collection; not an isolated Colab comparison.',
        measurement['notes']]
    report['stage_measurements'] = measurement['stages']
    return report


if __name__ == '__main__':
    repo = Path(__file__).resolve().parents[1]
    original = json.loads((repo/'benchmarks/ngochai06-sample10.json').read_text(encoding='utf-8'))
    evidence = repo/'data/sample10-20261103-103748'
    report = format_report(original,evidence/'output',evidence)
    text = json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    for name in ('ngochai06.json','hai.json'):
        (repo/'benchmarks'/name).write_text(text,encoding='utf-8')
    print('Wrote benchmarks/ngochai06.json and benchmarks/hai.json from measured Hai output.')
