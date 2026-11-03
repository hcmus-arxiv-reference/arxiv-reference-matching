"""Counters observe real transport attempts rather than logical cache tasks."""
from unittest.mock import Mock
from collections import Counter

from scripts.benchmark_sample import instrument_client, measure_call
from src.crawl.http_client import HttpClient, HttpResponse


def test_sample_counts_retry_attempts_and_http_errors():
    transport = Mock(side_effect=[HttpResponse(429,{},b''),HttpResponse(200,{},b'ok')])
    client = HttpClient('test',min_interval=0,max_retries=1,transport=transport,sleeper=lambda _:None)
    stats = {'references':dict(seconds=0,requests=0,retries=0,errors_by_type=Counter())}
    instrument_client(client,stats,lambda _: 'references')
    assert client.get('https://example.test/ref').status == 200
    assert stats['references']['requests'] == 2
    assert stats['references']['retries'] == 1
    assert stats['references']['errors_by_type'] == {'429':1}


def test_sample_measures_failed_stage_time():
    stats = {'source':{'seconds':0}}
    import pytest
    with pytest.raises(ValueError):
        measure_call(stats,'source',Mock(side_effect=ValueError()))()
    assert stats['source']['seconds'] > 0
