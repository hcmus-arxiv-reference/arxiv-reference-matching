"""Read-only quality checks for a crawler run and its benchmark summary."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.common.config import ArxivRange, SegmentedRange
from .manifest import TaskRecord
from .semantic_scholar import reference_rows
from .source import verified_source
from .storage import key


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_crawl(data_dir: str | Path, benchmark_path: str | Path) -> dict[str, Any]:
    """Validate a ``src/crawl`` run against the submitted benchmark JSON.

    The function never repairs, truncates, or rewrites candidate output. It
    verifies manifest-backed metadata, each Version receipt and Semantic
    Scholar cache, then compares counters reported in ``totals`` with counts
    derived from those files. A finding makes ``ok`` false.
    """
    root, benchmark_file = Path(data_dir), Path(benchmark_path)
    findings: list[dict[str, str]] = []

    def finding(code: str, message: str) -> None:
        findings.append({"code": code, "message": message})

    try:
        benchmark = _read_json(benchmark_file)
    except (OSError, json.JSONDecodeError) as error:
        return {"ok": False, "findings": [{"code": "benchmark_read", "message": str(error)}]}
    if not isinstance(benchmark, dict) or benchmark.get("schema_version") != 1:
        return {"ok": False, "findings": [{"code": "benchmark_schema", "message": "Expected a schema_version 1 object"}]}

    range_data = benchmark.get("range")
    try:
        if not isinstance(range_data, dict):
            raise ValueError("range must be an object")
        # One segment as {prefix,start,end}, or several as {"segments": [...]}.
        parts = range_data["segments"] if "segments" in range_data else [range_data]
        if not isinstance(parts, list) or not all(isinstance(part, dict) for part in parts):
            raise ValueError("range.segments must be a list of objects")
        segments = []
        for part in parts:
            if (not isinstance(part.get("prefix"), str)
                    or type(part.get("start")) is not int
                    or type(part.get("end")) is not int):
                raise ValueError("range prefix/start/end have invalid types")
            segments.append(ArxivRange(part["prefix"], part["start"], part["end"]))
        arxiv_range = SegmentedRange(tuple(segments))
    except (KeyError, TypeError, ValueError) as error:
        return {"ok": False, "findings": [{"code": "benchmark_range", "message": str(error)}]}

    if type(benchmark.get("ids_attempted")) is not int or benchmark["ids_attempted"] < 0:
        finding("benchmark_ids_attempted", "ids_attempted must be a non-negative integer")
    if type(benchmark.get("ids_attempted")) is int and benchmark["ids_attempted"] > len(arxiv_range):
        finding("benchmark_ids_attempted", "ids_attempted exceeds the assigned Range size")

    manifest_path = root / "manifests" / "crawl.jsonl"
    latest: dict[tuple[str, int | None, str], TaskRecord] = {}
    if not manifest_path.is_file():
        finding("manifest_missing", f"Missing {manifest_path}")
    else:
        try:
            manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            manifest_lines = []
            finding("manifest_read", str(error))
        for line_no, line in enumerate(manifest_lines, 1):
            try:
                record = TaskRecord(**json.loads(line))
                if (not isinstance(record.arxiv_id, str)
                        or (record.version is not None and (type(record.version) is not int or record.version < 1))
                        or not isinstance(record.kind, str) or not isinstance(record.status, str)
                        or type(record.attempts) is not int or record.attempts < 0):
                    raise ValueError("invalid manifest field type/value")
                allowed_statuses = {
                    "discovery": {"success", "error"},
                    "source": {"success", "non_tex", "unavailable", "error"},
                    "references": {"success", "error"},
                }
                expected_version = record.kind == "source"
                if (record.kind not in allowed_statuses
                        or (record.version is not None) != expected_version
                        or record.status not in allowed_statuses[record.kind]):
                    raise ValueError("invalid manifest task kind, Version, or status")
                if record.arxiv_id not in arxiv_range:
                    finding("manifest_out_of_range", f"Line {line_no}: {record.arxiv_id} is outside the submitted Range")
                    continue
                latest[record.key] = record
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                finding("manifest_invalid_record", f"Line {line_no}: {error}")

    discovery_records = {arxiv_id: rec for (arxiv_id, version, kind), rec in latest.items()
                         if version is None and kind == "discovery"}
    attempted = sum(record.attempts > 0 for record in discovery_records.values())
    publications: dict[str, dict[str, Any]] = {}
    versions_expected = versions_ok = versions_non_tex = 0
    publications_complete = references_total = references_with_arxiv_id = publications_s2_ok = 0

    for arxiv_id, discovery in discovery_records.items():
        if discovery.status != "success":
            continue
        meta_path = root / "metadata" / f"{key(arxiv_id)}.json"
        try:
            meta_record = _read_json(meta_path)
            if discovery.checksum != _digest(meta_path):
                raise ValueError("discovery checksum mismatch")
            payload = meta_record["publication"]
            if meta_record.get("format") != 1 or payload.get("arxiv_id") != arxiv_id:
                raise ValueError("wrong discovery identity or format")
            count = payload["versions"]
            revised_dates = payload["revised_dates"]
            if type(count) is not int or count < 1 or not isinstance(revised_dates, list) or len(revised_dates) != count - 1:
                raise ValueError("invalid version count or revision dates")
            publications[arxiv_id] = payload
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            finding("metadata_invalid", f"{arxiv_id}: {error}")
            continue

    for arxiv_id, payload in publications.items():
        complete_sources = True
        count = payload["versions"]
        versions_expected += count
        for version in range(1, count + 1):
            record = latest.get((arxiv_id, version, "source"))
            source = verified_source(root / "raw" / key(arxiv_id) / f"v{version}")
            if (record is None or record.status not in {"success", "non_tex"} or source is None
                    or source.status != record.status or source.checksum != record.checksum):
                complete_sources = False
                continue
            versions_ok += 1
            versions_non_tex += int(source.status == "non_tex")

        ref_record = latest.get((arxiv_id, None, "references"))
        ref_path = root / "references" / f"{key(arxiv_id)}.json"
        refs_ok = False
        try:
            refs_data = _read_json(ref_path)
            raw_rows = refs_data["rows"]
            if (not ref_record or ref_record.status != "success"
                    or ref_record.checksum != _digest(ref_path)
                    or refs_data.get("format") != 1 or refs_data.get("arxiv_id") != arxiv_id
                    or not isinstance(raw_rows, list)):
                raise ValueError("missing/mismatched reference receipt or payload")
            normalized = reference_rows(arxiv_id, raw_rows)
            refs_ok = True
            references_total += len(raw_rows)
            references_with_arxiv_id += sum(bool(((row.get("citedPaper") or {}).get("externalIds") or {}).get("ArXiv"))
                                             for row in raw_rows)
            # Keep this call explicit: it ensures all arXiv IDs in the S2 cache
            # pass the same shape and identifier checks as the production path.
            del normalized
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            finding("references_invalid", f"{arxiv_id}: {error}")
        if refs_ok:
            publications_s2_ok += 1
        if complete_sources and refs_ok:
            publications_complete += 1

    observed = {
        "ids_attempted": attempted,
        "publications_found": len(publications),
        "publications_complete": publications_complete,
        "versions_expected": versions_expected,
        "versions_ok": versions_ok,
        "versions_non_tex": versions_non_tex,
        "versions_failed": versions_expected - versions_ok,
        "references_total": references_total,
        "references_with_arxiv_id": references_with_arxiv_id,
        "publications_s2_ok": publications_s2_ok,
    }
    if type(benchmark.get("ids_attempted")) is int and benchmark["ids_attempted"] != attempted:
        finding("counter_mismatch", f"ids_attempted: benchmark={benchmark['ids_attempted']}, observed={attempted}")
    totals = benchmark.get("totals")
    if not isinstance(totals, dict):
        finding("benchmark_totals", "totals must be an object")
    else:
        for name, actual in observed.items():
            if name == "ids_attempted":
                continue
            declared = totals.get(name)
            if declared is not None and (type(declared) is not int or declared != actual):
                finding("counter_mismatch", f"totals.{name}: benchmark={declared!r}, observed={actual}")

    return {"ok": not findings, "member": benchmark.get("member"),
            "range": {"segments": [{"prefix": s.prefix, "start": s.start, "end": s.end}
                                   for s in arxiv_range.segments], "size": len(arxiv_range)},
            "observed": observed, "findings": findings}
