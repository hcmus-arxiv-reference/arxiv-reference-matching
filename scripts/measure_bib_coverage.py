"""Measure bibliography coverage of a Range before and after sidecar recovery.

M1 keeps only ``.tex``/``.bib`` (crawling statement), so a Version whose author shipped a
compiled ``.bbl`` instead of the ``.bib`` has citations but no bibliography in the corpus.
``scripts/recover_bibtex_sources.py --all`` restores those files into a sidecar. This script
counts, per TeX Version, where its bibliography comes from, so the report can state the gap
and how much recovery closes.

Classification of a TeX Version (static scan, comments ignored):

- ``bib_or_bibitem``: ships a ``.bib`` file or contains ``\\bibitem``;
- ``declared_missing``: declares ``\\bibliography``/``\\addbibresource`` or ``\\input``s a
  ``.bbl`` but ships neither, i.e. the case recovery targets;
- ``no_bibliography``: declares no bibliography at all.

``declared_missing`` Versions with a sidecar manifest are counted as ``recovered``; the
recovery report's statuses (``verified``, ``http_error``, ``archive_mismatch`` …) are copied
as given.

  python -m scripts.measure_bib_coverage --member bao --data-dir data/crawl-smoke \\
      --supplement-dir data/supplement/bao --output metrics/bib_coverage/bao.json
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from src.common.corpus import verified_source
from src.common.json_io import write_json
from src.common.schema import publication_key

_COMMENT = re.compile(r"(?<!\\)%.*")
_DECLARES = re.compile(r"\\(?:bibliography|addbibresource)\s*(?:\[[^\]]*\])?\s*\{|\\input\s*\{[^}]*\.bbl\s*\}")
_BIBITEM = re.compile(r"\\bibitem\b")


def classify_version(directory: Path) -> str | None:
    """Bibliography source class of one Version, or ``None`` for a Version without TeX."""
    source = verified_source(directory)
    if source is None or source.status != "success":
        return None
    tex, has_bib = [], False
    for path in sorted(directory.rglob("*")):
        if path.suffix.lower() == ".tex":
            text = path.read_text(encoding="utf-8", errors="replace")
            tex.append("\n".join(_COMMENT.sub("", line) for line in text.splitlines()))
        elif path.suffix.lower() == ".bib":
            has_bib = True
    if not tex:
        return None
    text = "\n".join(tex)
    if has_bib or _BIBITEM.search(text):
        return "bib_or_bibitem"
    return "declared_missing" if _DECLARES.search(text) else "no_bibliography"


def measure(data_dir: Path, supplement_dir: Path | None, member: str) -> dict:
    """Count TeX Versions by class and, for ``declared_missing``, by recovery outcome."""
    classes, publications = Counter(), {}
    recovered = 0
    for metadata in sorted((data_dir / "metadata").glob("*.json")):
        aid = json.loads(metadata.read_text(encoding="utf-8"))["publication"]["arxiv_id"]
        root = data_dir / "raw" / publication_key(aid)
        if not root.is_dir():
            continue
        for directory in sorted(p for p in root.iterdir() if p.name.startswith("v")):
            kind = classify_version(directory)
            if kind is None:
                continue
            classes[kind] += 1
            publications.setdefault(kind, set()).add(aid)
            manifest = (supplement_dir / publication_key(aid) / directory.name / "manifest.json"
                        if supplement_dir is not None else None)
            if kind == "declared_missing" and manifest is not None and manifest.is_file():
                recovered += 1
    report_path = supplement_dir / "recovery-report.json" if supplement_dir is not None else None
    recovery = (json.loads(report_path.read_text(encoding="utf-8")).get("by_status")
                if report_path is not None and report_path.is_file() else None)
    tex_versions = sum(classes.values())
    return {
        "format": 1,
        "member": member,
        "tex_versions": tex_versions,
        "versions": {kind: classes[kind] for kind in ("bib_or_bibitem", "declared_missing", "no_bibliography")},
        "publications": {kind: len(publications.get(kind, ())) for kind in
                         ("bib_or_bibitem", "declared_missing", "no_bibliography")},
        "declared_missing_recovered": recovered,
        "recovery_report": recovery,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--member", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--supplement-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = measure(args.data_dir, args.supplement_dir, args.member)
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
