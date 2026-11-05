"""Runner policy through the Engine seam, with an in-memory Engine.

No files besides ``STOP_RANGE`` and ``range-run.json``, no network, no locks:
each test states what the Engine does and checks what the Runner decides.
"""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from src.crawl.runner import Engine, run_range


class FakeEngine:
    """Engine whose crawl outcome per call is scripted by ``plan``.

    ``plan(engine, arxiv_id)`` runs inside ``crawl_ids`` and returns whether
    the Publication is now complete; default: complete on first crawl.
    """
    engine = "fake"

    def __init__(self, data_dir: Path, plan=None, export_error=None):
        self.data_dir = data_dir
        self.plan = plan or (lambda engine, arxiv_id: True)
        self.export_error = export_error
        self.done: set[str] = set()
        self.crawls: list[tuple[list[str], list[str]]] = []
        self.exports: list[list[str]] = []
        self.inside_exclusive = False

    @contextmanager
    def exclusive(self):
        self.inside_exclusive = True
        try:
            yield
        finally:
            self.inside_exclusive = False

    def status(self, arxiv_id):
        complete = arxiv_id in self.done
        return SimpleNamespace(publication=object(), expected_versions=1,
                               verified_versions=int(complete), non_tex_versions=0,
                               references_ok=complete, complete=complete)

    def crawl_ids(self, ids, *, upcoming=()):
        assert self.inside_exclusive
        self.crawls.append((list(ids), list(upcoming)))
        for arxiv_id in ids:
            if self.plan(self, arxiv_id):
                self.done.add(arxiv_id)
        return {}

    def export(self, ids):
        assert self.inside_exclusive
        self.exports.append(list(ids))
        if self.export_error:
            raise self.export_error
        ready = [i for i in ids if i in self.done]
        return ready, {}

    def issues(self, arxiv_id):
        return [] if arxiv_id in self.done else [{"kind": "references", "status": "error"}]


IDS = ["2508.02872", "2508.02873", "2508.02874"]


def crawled(engine):
    return [ids[0] for ids, _ in engine.crawls]


def receipt(tmp_path):
    return json.loads((tmp_path / "manifests" / "range-run.json").read_text())


def test_fake_engine_satisfies_the_seam(tmp_path):
    engine: Engine = FakeEngine(tmp_path)  # checked by type checkers
    assert run_range(engine, IDS[:1], min_free_bytes=0)["engine"] == "fake"


def test_retries_only_incomplete_publications(tmp_path):
    attempts = {}

    def plan(_engine, arxiv_id):
        attempts[arxiv_id] = attempts.get(arxiv_id, 0) + 1
        return arxiv_id != IDS[1] or attempts[arxiv_id] == 2

    engine = FakeEngine(tmp_path, plan)
    result = run_range(engine, IDS, retry_delay=0, min_free_bytes=0)
    assert result["status"] == "complete" and result["pass"] == 2
    assert crawled(engine) == [*IDS, IDS[1]]
    assert engine.exports == [IDS, IDS]


def test_already_complete_publications_are_never_crawled(tmp_path):
    engine = FakeEngine(tmp_path)
    engine.done.add(IDS[0])
    run_range(engine, IDS, min_free_bytes=0)
    assert crawled(engine) == IDS[1:]


def test_upcoming_is_the_rest_of_the_pass_in_order(tmp_path):
    engine = FakeEngine(tmp_path)
    run_range(engine, IDS, min_free_bytes=0)
    assert [upcoming for _, upcoming in engine.crawls] == [IDS[1:], IDS[2:], []]


def test_stop_range_is_checked_before_each_publication(tmp_path):
    def plan(engine, _arxiv_id):
        (engine.data_dir / "STOP_RANGE").touch()
        return True

    engine = FakeEngine(tmp_path, plan)
    result = run_range(engine, IDS, min_free_bytes=0)
    assert result["status"] == "stopped" and crawled(engine) == IDS[:1]
    assert engine.exports == [IDS] and result["exported_publications"] == 1


def test_stop_range_interrupts_the_cooldown(tmp_path):
    sleeps = []

    def sleeper(seconds):
        sleeps.append(seconds)
        (tmp_path / "STOP_RANGE").touch()

    engine = FakeEngine(tmp_path, lambda *_: False)
    result = run_range(engine, IDS[:1], max_passes=2, retry_delay=1800,
                       sleeper=sleeper, min_free_bytes=0)
    assert result["status"] == "stopped" and sleeps == [30]
    assert crawled(engine) == IDS[:1]


def test_low_disk_space_fails_before_crawling(tmp_path):
    engine = FakeEngine(tmp_path)
    with pytest.raises(OSError):
        run_range(engine, IDS, min_free_bytes=1 << 62)
    assert engine.crawls == []
    assert receipt(tmp_path)["status"] == "failed"
    assert receipt(tmp_path)["error_type"] == "OSError"


def test_ctrl_c_still_exports_progress(tmp_path):
    def plan(_engine, arxiv_id):
        if arxiv_id == IDS[1]:
            raise KeyboardInterrupt
        return True

    engine = FakeEngine(tmp_path, plan)
    result = run_range(engine, IDS, min_free_bytes=0)
    assert result["status"] == "stopped" and result["exported_publications"] == 1
    assert engine.exports == [IDS]


def test_export_failure_is_reported_as_failed(tmp_path):
    engine = FakeEngine(tmp_path, export_error=RuntimeError("disk"))
    with pytest.raises(RuntimeError):
        run_range(engine, IDS, min_free_bytes=0)
    assert receipt(tmp_path)["status"] == "failed"
    assert receipt(tmp_path)["error_type"] == "RuntimeError"


def test_progress_lines_come_from_engine_issues(tmp_path, capsys):
    engine = FakeEngine(tmp_path, lambda *_: False)
    run_range(engine, IDS[:1], max_passes=1, min_free_bytes=0)
    line = json.loads(capsys.readouterr().out.splitlines()[0])
    assert line["issues"] == [{"kind": "references", "status": "error"}]
