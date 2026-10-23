"""CLI scope verification without network or credentials."""
import pytest
from scripts.crawl_m1 import main


def test_full_range_dry_run(capsys):
    assert main(['--limit', '5000', '--dry-run']) == 0
    assert 'Selected 5000 IDs: 2412.08848 -> 2412.13847' in capsys.readouterr().out


def test_default_sample(capsys):
    assert main(['--dry-run']) == 0
    assert 'Selected 3 IDs' in capsys.readouterr().out


def test_invalid_limit():
    with pytest.raises(SystemExit):
        main(['--limit', '0', '--dry-run'])
