"""Rebuild tables/<member>/papers.parquet and references.parquet from raw/<member>/ on the team HF dataset.

Why: before the fix in ``src/crawl/publish.py`` (20/11/2026) the Hub listed at most
100,000 files, so batch uploads stopped seeing ``tables/<member>/`` and each batch
replaced the tables instead of merging. ``raw/`` was uploaded correctly: every
Version folder carries ``source.json``, and ``metadata.json`` plus ``references.json``
of its Publication. Those files are enough to rebuild both tables exactly as
Export writes them (``src/crawl/export.py``: a ``papers`` row is the Publication
without ``versions``; ``references`` rows come from ``CitationList``).

A Publication is rebuilt only when its metadata and references caches are valid and
``source.json`` exists for every Version ``v1..vN`` (N from the metadata). Its TeX
files were checked against those receipts by the publisher before upload, so they
are not downloaded here.

Dry run by default: prints counts next to the current remote tables. ``--upload``
writes both tables in one commit on a private dataset, and refuses to shrink a
table unless ``--allow-shrink``. Run it only after the member's own uploads have
finished, or an upload from an older Engine would replace the tables again.

  python scripts/rebuild_tables.py --member lieu
  python scripts/rebuild_tables.py --member lieu --upload
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.corpus import FileCorpus  # noqa: E402
from src.common.hf_io import table_path  # noqa: E402
from src.common.schema import from_records, read_table, write_table  # noqa: E402

_VERSION_FILE = re.compile(r"raw/(?P<member>[^/]+)/(?P<key>[^/]+)/v(?P<version>\d+)/(?P<name>[^/]+)$")


def plan(paths: list[str], member: str) -> dict[str, dict]:
    """Per Publication key: Version numbers with a receipt, and whether v1 has both caches."""
    found: dict[str, dict] = defaultdict(lambda: {"receipts": set(), "v1": set()})
    for path in paths:
        match = _VERSION_FILE.match(path)
        if not match or match["member"] != member:
            continue
        entry = found[match["key"]]
        if match["name"] == "source.json":
            entry["receipts"].add(int(match["version"]))
        if match["version"] == "1" and match["name"] in {"metadata.json", "references.json"}:
            entry["v1"].add(match["name"])
    return dict(found)


def rebuild(raw_member_dir: Path, keys: dict[str, dict]) -> tuple[list[dict], list[dict], dict]:
    """Rows for both tables from downloaded v1 caches, plus a report of skipped Publications."""
    papers, references, skipped = [], [], defaultdict(list)
    with tempfile.TemporaryDirectory(prefix="rebuild-") as temporary:
        corpus_dir = Path(temporary)
        (corpus_dir / "metadata").mkdir()
        (corpus_dir / "references").mkdir()
        corpus = FileCorpus(corpus_dir)
        for key, entry in sorted(keys.items()):
            if entry["v1"] != {"metadata.json", "references.json"}:
                skipped["missing_v1_cache"].append(key)
                continue
            version_dir = raw_member_dir / key / "v1"
            try:
                arxiv_id = json.loads((version_dir / "metadata.json").read_text())["publication"]["arxiv_id"]
                shutil.copyfile(version_dir / "metadata.json", corpus.metadata_path(arxiv_id))
                shutil.copyfile(version_dir / "references.json", corpus.references_path(arxiv_id))
                publication = corpus.read_publication(arxiv_id)
                citations = corpus.read_references(arxiv_id)
            except (OSError, ValueError, KeyError, TypeError) as error:
                skipped[f"invalid_cache:{type(error).__name__}"].append(key)
                continue
            if entry["receipts"] != set(range(1, publication.versions + 1)):
                skipped["incomplete_versions"].append(key)
                continue
            row = asdict(publication)
            row.pop("versions")
            papers.append(row)
            references.extend(citations.references)
    papers.sort(key=lambda r: r["arxiv_id"])
    references.sort(key=lambda r: (r["arxiv_id"], r["ref_arxiv_id"]))
    return papers, references, {k: sorted(v) for k, v in skipped.items()}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--member", required=True)
    parser.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()) / "rebuild-tables-cache")
    parser.add_argument("--upload", action="store_true", help="commit both tables to the dataset")
    parser.add_argument("--allow-shrink", action="store_true", help="allow a table with fewer rows than now")
    args = parser.parse_args(argv)

    from huggingface_hub import CommitOperationAdd, HfApi, snapshot_download

    from src.common.config import get_settings

    settings = get_settings()
    settings.require_hf()
    api, repo = HfApi(token=settings.hf_token), settings.hf_repo_id
    info = api.repo_info(repo_id=repo, repo_type="dataset")
    if info.private is not True:
        raise SystemExit("Dataset must be private")
    member = args.member
    paths = [item.path for item in api.list_repo_tree(repo_id=repo, repo_type="dataset", revision=info.sha,
                                                      path_in_repo=f"raw/{member}", recursive=True)
             if hasattr(item, "blob_id")]
    keys = plan(paths, member)
    print(f"raw/{member}: {len(keys)} Publication, {sum(len(e['receipts']) for e in keys.values())} Version")
    snapshot_download(repo_id=repo, repo_type="dataset", revision=info.sha, token=settings.hf_token,
                      local_dir=str(args.cache), max_workers=16,
                      allow_patterns=[f"raw/{member}/*/v1/metadata.json", f"raw/{member}/*/v1/references.json"])
    papers, references, skipped = rebuild(args.cache / "raw" / member, keys)
    print(f"rebuilt: papers {len(papers)}, references {len(references)}; skipped "
          f"{ {reason: len(items) for reason, items in skipped.items()} }")

    out = args.cache / "tables" / member
    out.mkdir(parents=True, exist_ok=True)
    current, operations = {}, []
    for name, rows in (("papers", papers), ("references", references)):
        path = out / f"{name}.parquet"
        write_table(from_records(rows, name), name, path)
        remote = table_path(member, name)
        try:
            current[name] = read_table(name, api.hf_hub_download(repo_id=repo, repo_type="dataset", filename=remote,
                                                                 revision=info.sha)).num_rows
        except Exception:            # table not on the Hub yet
            current[name] = 0
        print(f"  {remote}: now {current[name]} rows -> rebuilt {len(rows)} rows")
        if len(rows) < current[name] and not args.allow_shrink:
            raise SystemExit(f"{remote} would shrink; check skipped Publications or pass --allow-shrink")
        operations.append(CommitOperationAdd(path_in_repo=remote, path_or_fileobj=str(path)))
    report = {"member": member, "papers": len(papers), "references": len(references),
              "before": current, "skipped": skipped}
    if args.upload:
        commit = api.create_commit(repo_id=repo, repo_type="dataset", operations=operations,
                                   parent_commit=info.sha,
                                   commit_message=f"tables: rebuild {member} from raw ({len(papers)} publications)")
        report["commit"] = commit.oid
        print("uploaded:", commit.oid)
    else:
        print("dry run: add --upload to commit")
    return report


if __name__ == "__main__":
    main()
