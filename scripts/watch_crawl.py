"""Notify on this Mac when the local Range crawler finishes or stops.

This read-only watcher does not crawl, upload, or change the worker. A receipt
records whether macOS accepted the notification request, not whether the user
actually saw it (Focus and notification settings can hide notifications).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

from filelock import FileLock
from src.crawl.storage import write_json


def terminal_message(report, worker_alive=True):
    """Return (outcome, message) only for an unambiguous terminal condition."""
    status = report.get("status")
    total = report.get("requested", 0)
    complete = report.get("counts", {}).get("complete", 0)
    if (status == "complete" and total > 0 and complete == total
            and report.get("exported_publications") == total
            and report.get("pending_ids") == []):
        return "complete", f"Đã tải đủ {total}/{total} Publication về local và xuất bảng tổng hợp."
    if status in {"complete", "incomplete", "stopped", "failed"}:
        return "incomplete", f"Crawler đã kết thúc: {complete}/{total} Publication đủ dữ liệu. Cần kiểm tra phần còn thiếu."
    if not worker_alive:
        return "interrupted", f"Crawler không còn chạy: gần nhất {complete}/{total} Publication đủ dữ liệu. Có thể tiếp tục từ checkpoint."
    return None


def notify(message):
    """Pass text as argv so no notification content becomes AppleScript code."""
    script = ('on run argv\n'
              'display notification (item 1 of argv) with title "arXiv — Crawl Range" sound name "Glass"\n'
              'end run')
    result = subprocess.run(["/usr/bin/osascript", "-e", script, message],
                            capture_output=True, timeout=30)
    return result.returncode == 0


def worker_exists(pid):
    """Check existence without signalling or otherwise changing the worker."""
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def watch(data_dir, interval=30):
    """Watch persisted progress, then send one terminal notification per run."""
    manifests = data_dir / "manifests"
    state_path = manifests / "range-run.json"
    receipt_path = manifests / "range-notification.json"
    with FileLock(str(manifests / ".range-notify.lock"), timeout=0):
        while True:
            try:
                report = json.loads(state_path.read_text())
            except (OSError, ValueError):
                time.sleep(interval)
                continue
            outcome = terminal_message(report, worker_exists(report.get("pid")))
            if outcome is None:
                time.sleep(interval)
                continue
            # Allow atomic status updates / a replacement worker to settle.
            if outcome[0] == "interrupted":
                time.sleep(interval)
                report = json.loads(state_path.read_text())
                outcome = terminal_message(report, worker_exists(report.get("pid")))
                if outcome is None:
                    continue
            try:
                previous = json.loads(receipt_path.read_text())
            except (OSError, ValueError):
                previous = {}
            if (previous.get("run_started_at") == report.get("started_at")
                    and previous.get("notification_accepted")):
                return
            accepted = notify(outcome[1])
            write_json(receipt_path, {"run_started_at": report.get("started_at"),
                       "outcome": outcome[0], "message": outcome[1],
                       "notification_accepted": accepted,
                       "updated_at": datetime.now(timezone.utc).isoformat()})
            print(json.dumps({"outcome": outcome[0], "notification_accepted": accepted}), flush=True)
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    watch(args.data_dir)


if __name__ == "__main__":
    main()
