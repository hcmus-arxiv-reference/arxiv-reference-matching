"""Offline integration checks for the benchmark merger received from upstream."""
import json
import subprocess
import sys

from src.merge_benchmarks import read_run


def test_interrupted_segment_uses_last_complete_sample(tmp_path):
    (tmp_path / "benchmark_start.json").write_text('{"started_at": 100}')
    (tmp_path / "benchmark_samples.csv").write_text(
        "t_seconds,rss_mb,disk_mb\n0,20,1\n5,40,2\n6,unfinished")
    result = read_run(tmp_path)
    assert result["started_at"] == 100
    assert result["wall"] == 5 and result["final_disk"] == 2
    assert result["rows"] == [(0, 20, 1), (5, 40, 2)]
    assert result["meta"] == {}


def test_merge_cli_combines_segments_and_known_cooldown(tmp_path):
    runs = tmp_path / "runs"
    for name, meta, csv in [
        ("run_01", {"started_at": 100, "wall_seconds": 10, "final_disk_mb": 2},
         "0,20,1\n10,40,2\n"),
        ("run_02", {"started_at": 200, "wall_seconds": 20, "final_disk_mb": 5,
                    "interrupted": True}, "0,30,2\n20,50,4\n"),
    ]:
        directory = runs / name
        directory.mkdir(parents=True)
        (directory / "benchmark.json").write_text(json.dumps(meta))
        (directory / "benchmark_samples.csv").write_text("t_seconds,rss_mb,disk_mb\n" + csv)
    cooldown = tmp_path / "cooldowns.jsonl"
    cooldown.write_text('{"start_epoch":102,"seconds":2}\n{"start_epoch":205,"seconds":3}\n')
    output = tmp_path / "merged"
    result = subprocess.run([sys.executable, "-m", "src.merge_benchmarks",
                             "--runs", str(runs), "--out", str(output),
                             "--cooldown-log", str(cooldown)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    summary = json.loads((output / "benchmark_total.json").read_text())
    assert summary["segments"] == 2 and summary["total_wall_seconds"] == 30
    assert summary["total_cooldown_seconds"] == 5 and summary["wall_seconds_excl_cooldown"] == 25
    assert summary["peak_rss_mb"] == 50 and summary["avg_rss_mb"] == 35
    assert summary["peak_disk_mb"] == 5 and summary["final_disk_mb"] == 5
    assert summary["per_segment"][1]["ended"] == "Ctrl+C"
    lines = (output / "benchmark_samples_all.csv").read_text().splitlines()
    assert [float(line.split(",")[0]) for line in lines[1:]] == [0, 10, 10, 30]
