"""Reporting must distinguish missing data, verified empty source, and unknown metrics."""
import json
from unittest.mock import Mock

import pytest
from src.crawl.discovery import Publication
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.pipeline import CrawlPipeline
from src.crawl.source import ArxivSourceDownloader
from src.reporting.m1 import snapshot, distribution


def test_snapshot_checks_cache_without_repair_or_network(tmp_path):
    discovery, refs = Mock(), Mock()
    discovery.discover.side_effect=lambda pid:Publication(pid,'Private title',['Private author'],'2025-08-04',[],None,1)
    refs.references.return_value=[]
    http=HttpClient('offline',min_interval=0,transport=lambda request,*_:HttpResponse(
        200 if '02872' in request.full_url else 404,{},b'%PDF-1.7'))
    pipeline=CrawlPipeline(discovery,ArxivSourceDownloader(http,tmp_path/'raw'),tmp_path,refs)
    ids=['2508.02872','2508.02873']
    pipeline.crawl_ids(ids)
    pipeline.export(ids)
    manifest=tmp_path/'manifests/crawl.jsonl'
    before=manifest.read_bytes()
    result=snapshot(tmp_path,ids)
    assert result['counts']['complete']==1
    assert result['counts']['non_tex']==1
    assert result['counts']['unavailable']==1
    assert result['counts']['references_success']==2
    assert result['references']['per_successful_publication']['mean']==0
    assert result['benchmark']['mean_rss_bytes'] is None
    # 02872 v1 is an 8-byte PDF: 8 bytes before extraction, nothing kept after.
    assert result['storage']['before_extraction_bytes']==8
    assert result['storage']['size_reduction_fraction']==1
    assert result['storage']['publications_with_before_size']==1
    assert 'Private title' not in json.dumps(result)
    assert manifest.read_bytes()==before
    assert discovery.discover.call_count==refs.references.call_count==2
    manifest.write_bytes(before+b'{')
    with pytest.raises(ValueError,match='Incomplete manifest'):
        snapshot(tmp_path,ids)
    assert manifest.read_bytes()==before+b'{'  # No truncation/repair.


def test_aggregate_bins_have_no_overlap():
    bins=distribution([0,1,9,10,20],[0,1,10])
    assert [b['count'] for b in bins]==[1,2,2]


def make_cache(tmp_path):
    discovery, refs = Mock(), Mock()
    discovery.discover.side_effect=lambda pid:Publication(pid,'T',['A'],'2025-08-04',[],None,1)
    refs.references.return_value=[]
    http=HttpClient('offline',min_interval=0,transport=lambda *_:HttpResponse(200,{},b'\\documentclass{article}'))
    pipeline=CrawlPipeline(discovery,ArxivSourceDownloader(http,tmp_path/'raw'),tmp_path,refs)
    ids=['2508.02872','2508.02873']
    pipeline.crawl_ids(ids)
    pipeline.export(ids)
    return ids


def test_receipts_without_size_fields_keep_before_unknown(tmp_path):
    ids=make_cache(tmp_path)
    receipt=tmp_path/'raw/2508-02872/v1/source.json'
    payload=json.loads(receipt.read_text()); del payload['content_bytes']
    receipt.write_text(json.dumps(payload))
    storage=snapshot(tmp_path,ids)['storage']
    assert storage['publications_with_before_size']==1          # only 02873 is measurable
    assert storage['complete_publication_before_bytes']['n']==1


def test_benchmark_block_uses_merged_totals_and_timings(tmp_path):
    ids=make_cache(tmp_path)
    total={'segments':2,'total_wall_seconds':40.0,'peak_rss_mb':100.0,'avg_rss_mb':50.0,
           'peak_disk_mb':2.0,'final_disk_mb':1.5}
    block=snapshot(tmp_path,ids,benchmark=total)['benchmark']
    assert block['segments']==2 and block['wall_seconds_per_assigned_publication']==20
    assert block['publications_timed']==2 and block['discovery_seconds'] is not None
    assert block['peak_rss_bytes']==100*2**20 and block['final_disk_bytes']==round(1.5*2**20)
    assert snapshot(tmp_path,ids)['benchmark']['total_wall_seconds'] is None


def test_cli_reports_the_given_ids_and_member(tmp_path):
    from scripts.report_m1 import main
    cache=tmp_path/'cache'; cache.mkdir()
    ids=make_cache(cache)
    (tmp_path/'ids.txt').write_text('\n'.join(ids)+'\n')
    (tmp_path/'bench.json').write_text(json.dumps({'segments':1,'total_wall_seconds':10.0}))
    out=tmp_path/'report/snapshots/minh.json'
    main(['--cache',str(cache),'--output',str(out),'--member','minh','--ids-file',str(tmp_path/'ids.txt'),
          '--benchmark',str(tmp_path/'bench.json'),'--crawl-note','Colab run X'])
    result=json.loads(out.read_text())
    assert result['member']=='minh' and result['counts']['assigned']==2
    assert result['range']=={'first':'2508.02872','last':'2508.02873'}
    assert result['crawl']['note']=='Colab run X' and result['benchmark']['segments']==1
