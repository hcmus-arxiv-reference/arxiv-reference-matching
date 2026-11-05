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
    assert result['storage']['before_extraction_bytes'] is None
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


def test_hai_entrypoint_checks_without_touching_cache(tmp_path):
    from scripts.report_m1 import report
    discovery, refs = Mock(), Mock()
    identifier = '2412.08848'
    discovery.discover.return_value = Publication(identifier,'Paper',['A'],'2024-12-01',[],None,1)
    refs.references.return_value = []
    transport = Mock(return_value=HttpResponse(200,{},b'\\documentclass{article}'))
    cache = tmp_path/'cache'
    pipeline = CrawlPipeline(discovery,ArxivSourceDownloader(
        HttpClient('test',transport=transport),cache/'raw'),cache,refs)
    pipeline.crawl_ids([identifier])
    pipeline.export([identifier])
    manifest = cache/'manifests/crawl.jsonl'
    before = manifest.read_bytes()
    transport.reset_mock()
    output = tmp_path/'hai-validated.json'
    result = report(cache,[identifier],member='hai',output=output,workers=2)
    assert result['member']=='hai' and result['scope'].startswith('hai only')
    assert result['range']=={'first':identifier,'last':identifier}
    assert result['counts']['complete']==1
    assert result['checks']['tables']['papers']['valid']
    assert json.loads(output.read_text())['provenance']['report_command']=='python -m scripts.report_m1'
    assert manifest.read_bytes()==before
    transport.assert_not_called()
    with pytest.raises(ValueError,match='outside'):
        report(cache,[identifier],member='hai',output=cache/'report.json')
