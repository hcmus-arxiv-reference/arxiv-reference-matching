"""Notification must never confuse an ended process with complete data."""
from scripts.watch_crawl import terminal_message


def test_notify_success_requires_full_verified_export():
    report = {"status": "complete", "requested": 5000, "counts": {"complete": 5000},
              "exported_publications": 5000, "pending_ids": []}
    assert terminal_message(report)[0] == "complete"
    report["exported_publications"] = 4999
    assert terminal_message(report)[0] == "incomplete"


def test_running_is_silent_and_interruption_is_not_success():
    report = {"status": "running", "requested": 5000, "counts": {"complete": 237}}
    assert terminal_message(report) is None
    assert terminal_message(report, worker_alive=False)[0] == "interrupted"
    report["status"] = "incomplete"
    assert terminal_message(report)[0] == "incomplete"
