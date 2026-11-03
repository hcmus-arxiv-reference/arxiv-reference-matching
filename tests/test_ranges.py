"""Multi-segment Ranges in configs/ranges.toml, the --member CLI option and the validator."""
import json
import subprocess
import sys

import pytest

from src.common.config import ArxivRange, SegmentedRange, load_ranges, member_ids
from src.crawl.validation import validate_crawl
from tests.test_crawl_validation import make_run

TOML = '''ids_per_member = {size}
[[members]]
name = "a"
github = "user-a"
verified = true
segments = [{{ prefix = "2409", start = 99998, end = 99999 }}, {{ prefix = "2410", start = 1, end = 1 }}]
[[members]]
name = "b"
github = "user-b"
verified = {verified}
segments = [{{ prefix = "2409", start = {b_start}, end = {b_end} }}]
'''


def write(tmp_path, size=3, verified="true", b_start=1, b_end=3):
    path = tmp_path / 'ranges.toml'
    path.write_text(TOML.format(size=size, verified=verified, b_start=b_start, b_end=b_end))
    return path


def test_group_config_has_disjoint_5000_id_ranges():
    members = load_ranges()
    assert all(len(m.range) == 5000 for m in members.values())
    minh = members['minh'].range
    assert ['2409.20569', '2410.00001'] == list(minh.ids())[1975:1977]
    assert '2409.20570' not in minh and '2410.03024' in minh and '2410.03025' not in minh
    assert len(set(member_ids('all'))) == 5000 * len(members)


def test_segments_cross_month_boundary(tmp_path):
    ids = list(member_ids('a', write(tmp_path)))
    assert ids == ['2409.99998', '2409.99999', '2410.00001']


@pytest.mark.parametrize('kwargs, message', [
    ({'size': 4}, 'cần đúng 4'),
    ({'b_start': 99997, 'b_end': 99999}, 'chồng'),
])
def test_invalid_config_is_rejected(tmp_path, kwargs, message):
    with pytest.raises(ValueError, match=message):
        load_ranges(write(tmp_path, **kwargs))


def test_overlapping_segments_within_a_range_are_rejected():
    with pytest.raises(ValueError, match='chồng'):
        SegmentedRange((ArxivRange('2409', 1, 10), ArxivRange('2409', 10, 12)))


def test_unknown_or_unverified_member_is_refused(tmp_path):
    path = write(tmp_path, verified='false')
    with pytest.raises(KeyError, match='có: a, b'):
        member_ids('c', path)
    with pytest.raises(ValueError, match='chưa xác minh: b'):
        member_ids('all', path)


def test_cli_rejects_unknown_member():
    result = subprocess.run([sys.executable, '-m', 'src.milestone1_crawler', '--member', 'nobody'],
                            capture_output=True, text=True)
    assert result.returncode == 2 and "Không có Range cho 'nobody'" in result.stderr


def test_validator_accepts_segmented_range(tmp_path):
    data = make_run(tmp_path)  # one Publication 2508.02872
    path = tmp_path / 'benchmark.json'

    def check(segments):
        path.write_text(json.dumps({'schema_version': 1, 'member': 'test', 'ids_attempted': 1,
                                    'range': {'segments': segments}, 'totals': {}}))
        return validate_crawl(data, path)

    report = check([{'prefix': '2507', 'start': 1, 'end': 1}, {'prefix': '2508', 'start': 2872, 'end': 2872}])
    assert report['ok'], report['findings']
    assert report['range']['size'] == 2 and len(report['range']['segments']) == 2
    outside = check([{'prefix': '2507', 'start': 1, 'end': 2}])
    assert 'manifest_out_of_range' in {f['code'] for f in outside['findings']}
    overlap = check([{'prefix': '2508', 'start': 1, 'end': 3000}, {'prefix': '2508', 'start': 2872, 'end': 2900}])
    assert [f['code'] for f in overlap['findings']] == ['benchmark_range']


@pytest.mark.parametrize('members', ['', 'members = []\n', 'members = "invalid"\n', 'members = [1]\n'])
def test_missing_or_invalid_members_are_rejected(tmp_path, members):
    path = tmp_path / 'ranges.toml'
    path.write_text('ids_per_member = 5000\n' + members)
    with pytest.raises(ValueError):
        list(member_ids('all', path))


def test_public_cli_passes_cross_month_ids_to_runner(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from src.crawl import cli, runner
    from src.milestone1_crawler import main

    path = write(tmp_path)
    settings = SimpleNamespace(data_dir=tmp_path, user_agent=lambda: 'offline', s2_api_key=None,
                               arxiv_range=ArxivRange('2508', 2872, 7871))
    monkeypatch.setattr(cli, 'get_settings', lambda: settings)
    monkeypatch.setattr(cli, 'member_ids', lambda name: member_ids(name, path))
    monkeypatch.setattr(cli, 'HttpClient', Mock())
    pipeline = Mock()
    monkeypatch.setattr(cli, 'LieuPipeline', Mock(return_value=pipeline))
    monkeypatch.setattr(cli.signal, 'signal', lambda *args: None)
    run = Mock(return_value={'status': 'complete'})
    monkeypatch.setattr(runner, 'run_range', run)

    assert main(['--member', 'a']) == 0
    assert run.call_args.args == (pipeline, ['2409.99998', '2409.99999', '2410.00001'])


@pytest.mark.parametrize('source', ['member', 'file'])
def test_explicit_empty_cli_selection_never_falls_back(tmp_path, monkeypatch, source):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from src.crawl import cli

    settings = SimpleNamespace(arxiv_range=ArxivRange('2508', 2872, 7871))
    monkeypatch.setattr(cli, 'get_settings', lambda: settings)
    monkeypatch.setattr(cli, 'member_ids', lambda name: iter([]))
    client = Mock(side_effect=AssertionError('must fail before HTTP setup'))
    monkeypatch.setattr(cli, 'HttpClient', client)
    path = tmp_path / 'ids.txt'
    path.write_text('# no IDs\n')
    args = ['--member', 'all'] if source == 'member' else ['--ids-file', str(path)]
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2
    client.assert_not_called()
