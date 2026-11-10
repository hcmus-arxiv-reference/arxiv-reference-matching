"""Build aggregate M1 report evidence from the verified integrated cache.

No Manifest constructor is used: reporting must not repair/truncate checkpoints.
The output excludes source text, paper titles, authors, references and secrets.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
from types import SimpleNamespace

from src.common.schema import read_table
from src.make_stats import load_timings
from src.crawl.manifest import TaskRecord
from src.crawl.corpus import CorpusReader
from src.crawl.storage import key


def digest(path):
    """Stream a file digest without logging its contents."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def distribution(values, edges):
    """Return disjoint integer bins, including an unbounded final bin."""
    counts = [0] * len(edges)
    for value in values:
        index = next((i for i in range(len(edges)-1) if value < edges[i+1]), len(edges)-1)
        counts[index] += 1
    return [{"lower": lower, "upper_exclusive": edges[i+1] if i+1 < len(edges) else None,
             "count": counts[i]} for i, lower in enumerate(edges)]


def describe(values):
    """Missing observations remain null, never zero-filled."""
    return {"n": len(values), "sum": sum(values),
            "mean": statistics.mean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "max": max(values) if values else None}


def benchmark_block(benchmark, timings, identifiers):
    """Performance numbers from a merged benchmark and ``manifests/timings.jsonl``.

    ``benchmark`` is ``benchmark_total.json`` of ``src.merge_benchmarks`` (MB = 2**20
    bytes, as ``src.benchmark`` writes them); ``timings`` maps arxiv_id to summed
    (seconds, discovery_seconds) over every visit. Unknown values stay null.
    """
    if benchmark is None:
        return {"testbed": "not measured on Colab", "total_wall_seconds": None,
                "mean_seconds_per_publication": None, "discovery_seconds": None,
                "peak_rss_bytes": None, "mean_rss_bytes": None, "peak_disk_bytes": None}
    to_bytes = lambda mb: None if mb is None else round(mb * 2**20)
    seconds = [timings[i][0] for i in identifiers if i in timings]
    return {"testbed": benchmark.get("testbed", "Google Colab CPU"),
            "segments": benchmark["segments"],
            "total_wall_seconds": benchmark["total_wall_seconds"],
            "wall_seconds_per_assigned_publication": benchmark["total_wall_seconds"] / len(identifiers),
            "publications_timed": len(seconds),
            "seconds_per_publication": describe(seconds),
            "mean_seconds_per_publication": statistics.mean(seconds) if seconds else None,
            "discovery_seconds": (sum(timings[i][1] for i in identifiers if i in timings)
                                  if seconds else None),
            "peak_rss_bytes": to_bytes(benchmark.get("peak_rss_mb")),
            "mean_rss_bytes": to_bytes(benchmark.get("avg_rss_mb")),
            "peak_disk_bytes": to_bytes(benchmark.get("peak_disk_mb")),
            "final_disk_bytes": to_bytes(benchmark.get("final_disk_mb"))}


def snapshot(cache, identifiers, *, member="bao", trial=None, smoke=None, benchmark=None,
             crawl_note=None):
    """Validate local evidence and return an aggregate, publication-safe snapshot.

    ``benchmark`` (merged ``benchmark_total.json``) fills the performance block;
    without it the block stays null. ``crawl_note`` describes how the corpus was made.
    """
    cache = Path(cache)
    identifiers = list(identifiers)
    if len(identifiers) != len(set(identifiers)) or not identifiers:
        raise ValueError("IDs must be a nonempty unique list")
    manifest_path = cache / "manifests/crawl.jsonl"
    body = manifest_path.read_bytes()
    if body and not body.endswith(b"\n"):
        raise ValueError("Incomplete manifest tail; stop the writer before reporting")
    records = {}
    for line in body.splitlines():
        rec = TaskRecord(**json.loads(line))
        records[rec.key] = rec
    status_path = cache / "manifests/range-run.json"
    state_bytes = status_path.read_bytes() if status_path.exists() else None
    state = json.loads(state_bytes) if state_bytes else {}
    if state.get("status") in {"running", "retry_wait"}:
        raise ValueError("Crawler is active; take a stable snapshot after it stops")
    manifest = SimpleNamespace(get=lambda pid, v, kind="source": records.get((pid,v,kind)))
    corpus = CorpusReader(cache, manifest)
    counts = Counter(assigned=len(identifiers), discovered=0, complete=0, references_success=0,
                     expected_versions=0, success=0, non_tex=0, unavailable=0,
                     download_error=0, not_attempted=0)
    versions_hist, retained_sizes, complete_sizes, ref_counts = Counter(), [], [], []
    # Before/after compared on the same complete Publications: those whose every
    # Version receipt records downloaded_bytes and content_bytes (PR #27 onward).
    sized_before, sized_downloaded, sized_after = [], [], []
    # Same Publications, one value per Version: (before, downloaded, after).
    sized_versions, complete_version_sizes = [], []
    raw_refs = arxiv_refs = unique_refs = empty_refs = legacy_refs = 0
    failures, unexpected_files = [], []
    input_hashes = {"manifests/crawl.jsonl": hashlib.sha256(body).hexdigest()}
    metadata_issues = Counter()
    for identifier in identifiers:
        pub_state = corpus.status(identifier)
        publication = pub_state.publication
        if publication is None:
            failures.append({"arxiv_id": identifier, "version": None, "kind": "discovery", "status": "unknown"})
            continue  # Unknown expected Version count is not represented as zero.
        counts["discovered"] += 1
        counts["expected_versions"] += publication.versions
        versions_hist[publication.versions] += 1
        if any(not a.strip() for a in publication.authors):
            metadata_issues["empty_author"] += 1
        rel = f"metadata/{key(identifier)}.json"
        input_hashes[rel] = digest(cache / rel)
        verified = size = 0
        before = downloaded = 0     # None once a Version lacks the size fields
        version_sizes = []          # (before, downloaded, after) per verified Version
        for item in pub_state.versions:
            version, source, rec = item.version, item.source, item.task
            directory = corpus.files.version_path(identifier, version)
            if item.verified:
                status = source.status
                verified += 1
                kept = sum((directory / name).stat().st_size for name in (*source.tex_files,*source.bib_files))
                size += kept
                receipt = json.loads((directory / 'source.json').read_text(encoding='utf-8'))
                version_sizes.append((receipt.get('content_bytes'), receipt.get('downloaded_bytes'), kept))
                if before is not None and 'content_bytes' in receipt and 'downloaded_bytes' in receipt:
                    before += receipt['content_bytes']
                    downloaded += receipt['downloaded_bytes']
                else:
                    before = downloaded = None
                input_hashes[str((directory/'source.json').relative_to(cache))] = digest(directory/'source.json')
            else:
                status = ("unavailable" if rec and rec.status == "unavailable" else
                          "download_error" if rec and rec.status != "pending" else "not_attempted")
                failures.append({"arxiv_id": identifier, "version": version, "kind": "source",
                                 "status": status, "http_status": rec.http_status if rec else None})
            counts[status] += 1
        retained_sizes.append(size)
        has_refs = False
        citations = pub_state.references
        if citations is not None:
            has_refs = True
            counts["references_success"] += 1
            raw_refs += citations.total
            ref_counts.append(citations.total)
            empty_refs += citations.total == 0
            arxiv_refs += citations.with_arxiv_id
            unique_refs += len(citations.references)
            legacy_refs += citations.legacy_ids
            rel = f"references/{key(identifier)}.json"
            input_hashes[rel] = digest(cache / rel)
        else:
            rec = manifest.get(identifier, None, "references")
            failures.append({"arxiv_id": identifier, "version": None, "kind": "references",
                             "status": rec.status if rec else "not_attempted",
                             "http_status": rec.http_status if rec else None})
        if has_refs and verified == publication.versions:
            counts["complete"] += 1
            complete_sizes.append(size)
            complete_version_sizes.extend(after for _, _, after in version_sizes)
            if before is not None:
                sized_before.append(before)
                sized_downloaded.append(downloaded)
                sized_after.append(size)
                sized_versions.extend(version_sizes)
    disk = {}
    for category in ("raw", "metadata", "references", "tables"):
        disk[category] = sum(p.stat().st_size for p in (cache/category).rglob('*') if p.is_file())
    for path in (cache/'raw').rglob('*'):
        if path.is_file() and path.name != 'source.json' and path.suffix.lower() not in {'.tex','.bib'}:
            unexpected_files.append(str(path.relative_to(cache)))
    tables = {}
    for name in ('papers','references'):
        path = cache/'tables'/f'{name}.parquet'
        try:
            table = read_table(name,path)
            ids = table['arxiv_id'].to_pylist()
            primary = ('arxiv_id',) if name=='papers' else ('arxiv_id','ref_arxiv_id')
            keys = list(zip(*(table[k].to_pylist() for k in primary)))
            tables[name] = {"valid": True, "rows": table.num_rows,
                "duplicate_keys": len(keys)-len(set(keys)), "outside_range": len(set(ids)-set(identifiers)),
                "fields": [{"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in table.schema]}
            input_hashes[str(path.relative_to(cache))] = digest(path)
        except Exception as exc:
            tables[name] = {"valid": False, "error_type": type(exc).__name__}
    launch_path = cache/'manifests/range-launch.json'
    launch = json.loads(launch_path.read_text()) if launch_path.exists() else {}
    timings = {}
    timings_path = cache / 'manifests/timings.jsonl'
    if timings_path.exists():
        timings = load_timings(timings_path)
        input_hashes['manifests/timings.jsonl'] = digest(timings_path)
    before_stats = describe(sized_before)
    result = {"format": 1, "member": member, "scope": f"Range {member} only; other Ranges have their own snapshot",
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        "range": {"first": identifiers[0], "last": identifiers[-1]}, "counts": dict(counts),
        "crawl": {"engine": state.get('engine'), "last_worker_commit": launch.get('code_commit'),
                  "finished_at": state.get('updated_at'), "status": state.get('status'),
                  "note": crawl_note or "Corpus accumulated across several runs/commits; not a single benchmark."},
        "versions_distribution": [{"versions":n,"publications":v} for n,v in sorted(versions_hist.items())],
        "references": {"all_records":raw_refs,"with_arxiv_before_dedup":arxiv_refs,
            "unique_arxiv_pairs":unique_refs,"legacy_arxiv_pairs":legacy_refs,
            "successfully_empty_publications":empty_refs,"per_successful_publication":describe(ref_counts),
            "histogram":distribution(ref_counts,[0,1,10,25,50,100,200,500,1000])},
        "storage": {"active_output_bytes":disk, "retained_tex_bib_bytes":sum(retained_sizes),
            "complete_publication_retained_bytes":describe(complete_sizes),
            # Mean per complete Publication, before removing figures/non-.tex/.bib files.
            "before_extraction_bytes":before_stats["mean"],
            "complete_publication_before_bytes":before_stats,
            "complete_publication_downloaded_bytes":describe(sized_downloaded),
            "publications_with_before_size":len(sized_before),
            # The same byte totals per Version: every Version of the Publications above.
            "complete_version_retained_bytes":describe(complete_version_sizes),
            "sized_version_before_bytes":describe([v[0] for v in sized_versions]),
            "sized_version_downloaded_bytes":describe([v[1] for v in sized_versions]),
            "sized_version_after_bytes":describe([v[2] for v in sized_versions]),
            "size_reduction_fraction":(1 - sum(sized_after) / sum(sized_before)) if sum(sized_before) else None,
            "note":("Before/after compared on complete Publications whose receipts record sizes; "
                    "before = bytes after decompression, before keeping .tex/.bib. "
                    "Disk is a current logical-size snapshot, not historical peak.")},
        "checks": {"tables":tables,"unexpected_raw_files":unexpected_files,"metadata_issues":dict(metadata_issues)},
        "failures":failures,
        "provenance": {"verified_input_files":len(input_hashes),
            "aggregate_input_hash":hashlib.sha256(json.dumps(input_hashes,sort_keys=True).encode()).hexdigest(),
            "manifest_sha256":input_hashes['manifests/crawl.jsonl']},
        "benchmark": benchmark_block(benchmark, timings, identifiers)}
    if trial:
        evidence=json.loads(Path(trial).read_text())
        result['retry_trial']={k:evidence[k] for k in ('status','updated_at','elapsed_seconds','requested',
            'visited','recovered_publications','source_outcomes','reference_outcomes')}
        result['retry_trial']['note']='Standalone e5be40e missing-task retry on macOS; not fresh crawl or Colab benchmark.'
    if smoke:
        samples=[]
        for path in sorted(Path(smoke).glob('*/done.json')):
            d=json.loads(path.read_text())
            samples.append({k:d[k] for k in ['id','n_versions','bytes_downloaded','bytes_before','bytes_after',
                                            'n_refs','n_refs_with_arxiv_id','seconds','discover_seconds','rss_mb']})
        result['smoke_samples']=samples
    if manifest_path.read_bytes()!=body or (state_bytes and status_path.read_bytes()!=state_bytes):
        raise ValueError("Cache checkpoint changed during reporting; discard the snapshot")
    return result
