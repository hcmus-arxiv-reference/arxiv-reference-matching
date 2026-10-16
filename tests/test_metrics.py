import json
import time

from src.common.metrics import append_jsonl, dir_size_mb, measure, peak_rss_mb


def test_measure_records_time():
    with measure("sleep") as m:
        time.sleep(0.05)
    assert m.label == "sleep"
    assert m.seconds >= 0.04


def test_measure_records_time_even_on_error():
    try:
        with measure("boom") as m:
            raise RuntimeError
    except RuntimeError:
        pass
    assert m.seconds >= 0


def test_peak_rss_is_positive_or_none():
    value = peak_rss_mb()
    assert value is None or value > 0


def test_dir_size_and_jsonl(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x" * 1024 * 1024)
    assert 0.99 < dir_size_mb(tmp_path) < 1.01
    assert 0.99 < dir_size_mb(tmp_path / "a.txt") < 1.01

    log = tmp_path / "logs" / "m.jsonl"
    append_jsonl(log, {"a": 1})
    append_jsonl(log, {"b": "é"})
    lines = log.read_text(encoding="utf-8").splitlines()
    assert [json.loads(x) for x in lines] == [{"a": 1}, {"b": "é"}]
