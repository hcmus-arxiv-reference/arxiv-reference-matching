"""Discover every Version for a Range and write inputs for the crawler notebooks.

Uses the existing Atom parser, with direct requests and the configured contact
email. Checkpoints contain metadata only; this does not download source or S2.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.common.config import ArxivRange, get_settings


def prepare_ids(identifiers, output_dir, fetch, batch_size=50):
    """Retry missing IDs on rerun; retain successful metadata atomically."""
    identifiers = list(identifiers)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = root / "arxiv_metadata.json"
    records = {}
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if saved["ids"] != identifiers:
            raise ValueError("Checkpoint range mismatch; select another output directory")
        records = {paper["arxiv_id"]: paper for paper in saved["papers"]}

    def save():
        papers = [records[identifier] for identifier in identifiers if identifier in records]
        payload = {"ids": identifiers, "papers": papers,
                   "missing_ids": [i for i in identifiers if i not in records]}
        temporary = checkpoint.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(checkpoint)
        for name, lines in (
            ("arxiv_id.txt", [v for paper in papers for v in paper["versions"]]),
            ("arxiv_id_no_version.txt", [paper["arxiv_id"] for paper in papers]),
        ):
            target = root / name
            temporary = target.with_suffix(".txt.tmp")
            temporary.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
            temporary.replace(target)
        return payload

    pending = [i for i in identifiers if i not in records]
    # Regenerate notebook input files even when discovery was already complete.
    save()
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        found = fetch(batch)
        for identifier in batch:
            if identifier in found:
                records[identifier] = found[identifier]
        save()
        print(f"Metadata: {len(records)}/{len(identifiers)} Publications", flush=True)
    return save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--start", required=True, type=int)
    parser.add_argument("--end", required=True, type=int)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    identifiers = ArxivRange(args.prefix, args.start, args.end).ids()
    settings = get_settings()
    user_agent = settings.user_agent()
    from src import get_id_range_script as discovery
    # Never use the legacy script's embedded proxy configuration.
    discovery.PROXY_ENABLED = False
    discovery.session.headers.update({"User-Agent": user_agent})
    result = prepare_ids(identifiers, args.output_dir, discovery.fetch_papers)
    missing = len(result["missing_ids"])
    print(f"Saved notebook inputs in {args.output_dir.resolve()}; missing={missing}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
