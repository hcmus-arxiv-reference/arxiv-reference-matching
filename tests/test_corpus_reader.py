"""The read-only corpus contract used by runners, exports and reports."""
import hashlib
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from src.common.json_io import write_json
from src.crawl.corpus import CorpusReader
from src.crawl.discovery import Publication
from src.crawl.export import export_publications
from src.crawl.manifest import TaskRecord
from src.common.schema import read_table


def test_reader_rejects_modified_cache_without_repair(tmp_path):
    pid = '2508.02872'
    publication = Publication(pid, 'Title', [], '2025-08-04', [], None, 1)
    path = tmp_path / 'metadata/2508-02872.json'
    write_json(path, {'format': 1, 'publication': asdict(publication)})
    record = TaskRecord(pid, kind='discovery', status='success',
                        checksum=hashlib.sha256(path.read_bytes()).hexdigest())
    reader = CorpusReader(tmp_path, SimpleNamespace(get=lambda *args: record))
    assert reader.load_publication(pid) == publication
    path.write_text('{}')
    with pytest.raises(ValueError, match='Unverified'):
        reader.load_publication(pid)
    assert path.read_text() == '{}'
    assert not (tmp_path / 'manifests').exists()


def test_export_empty_selection_without_network_or_checkpoint_writer(tmp_path):
    reader = CorpusReader(tmp_path, SimpleNamespace(get=lambda *args: None))
    bundles, tables = export_publications(reader, tmp_path / 'raw', ['2508.02872'])
    assert bundles == []
    assert read_table('papers', tables['papers']).num_rows == 0
    assert read_table('references', tables['references']).num_rows == 0
    assert not (tmp_path / 'manifests').exists()


def test_atomic_json_keeps_previous_document_on_encoding_failure(tmp_path):
    path = tmp_path / 'checkpoint.json'
    write_json(path, {'complete': True})
    before = path.read_bytes()
    with pytest.raises(TypeError):
        write_json(path, {'unsupported': object()})
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('.checkpoint-*'))


def test_legacy_runner_and_cli_remain_importable():
    from scripts.crawl_range import run_range as legacy
    from src.crawl.runner import run_range
    from src.crawl.lieu_pipeline import main
    assert legacy is run_range
    with pytest.raises(SystemExit) as result:
        main(['--help'])
    assert result.value.code == 0
