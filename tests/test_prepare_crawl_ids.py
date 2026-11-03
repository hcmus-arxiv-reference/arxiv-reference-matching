"""Offline checks for Range input preparation and interrupted discovery."""
import json
from unittest.mock import Mock

import pytest

from scripts.prepare_crawl_ids import prepare_ids


def paper(identifier, versions=1):
    return {"arxiv_id": identifier,
            "versions": [f"{identifier}v{v}" for v in range(1, versions + 1)]}


def test_resume_retries_missing_and_preserves_version_order(tmp_path):
    ids = ["2412.08848", "2412.08849"]
    fetch = Mock(return_value={ids[1]: paper(ids[1], 2)})
    result = prepare_ids(ids, tmp_path, fetch)
    assert result["missing_ids"] == [ids[0]]
    fetch = Mock(return_value={ids[0]: paper(ids[0])})
    prepare_ids(ids, tmp_path, fetch)
    fetch.assert_called_once_with([ids[0]])
    assert (tmp_path / "arxiv_id.txt").read_text().splitlines() == [
        "2412.08848v1", "2412.08849v1", "2412.08849v2"]
    assert (tmp_path / "arxiv_id_no_version.txt").read_text().splitlines() == ids
    fetch.reset_mock()
    prepare_ids(ids, tmp_path, fetch)
    fetch.assert_not_called()
    with pytest.raises(ValueError, match="range mismatch"):
        prepare_ids(["2412.00001"], tmp_path, fetch)


def test_failed_batch_keeps_prior_checkpoint(tmp_path):
    ids = ["2412.08848", "2412.08849"]
    fetch = Mock(side_effect=[{ids[0]: paper(ids[0])}, RuntimeError("network")])
    with pytest.raises(RuntimeError, match="network"):
        prepare_ids(ids, tmp_path, fetch, batch_size=1)
    saved = json.loads((tmp_path / "arxiv_metadata.json").read_text())
    assert saved["missing_ids"] == [ids[1]]
    assert saved["papers"] == [paper(ids[0])]
