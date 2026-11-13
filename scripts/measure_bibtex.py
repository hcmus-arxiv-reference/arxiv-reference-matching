"""Measure M2.4b offline on a seeded sample of a local crawl cache.

The literal LaTeX reader below supplies BibSource for this benchmark until the
M2.2 Structure parser is integrated. It reads source from verified receipts.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path, PurePosixPath
import random
import re
import subprocess
from time import perf_counter

from src.common.corpus import FileCorpus, file_digest, safe_member
from src.common.json_io import write_json
from src.common.metrics import measure
from src.common.schema import from_records
from src.parse import types as shared_types
from src.parse.bibtex import BIBTEX_VERSION, merge_bibtex
from src.parse.normalize import _group_end
from src.parse.source import assemble_source
from src.parse.types import BibSource


_IGNORED = re.compile(
    r"(?P<comment>(?<!\\)(?:\\\\)*%[^\r\n]*)|"
    r"\\begin\s*\{(?P<env>verbatim\*?|Verbatim|lstlisting|minted|comment)\}"
    r".*?\\end\s*\{(?P=env)\}|"
    r"\\(?:verb|lstinline)\*?(?P<sep>[^\sA-Za-z@])(?:(?!(?P=sep))[^\r\n])*(?P=sep)",
    re.S,
)
_BIBLIOGRAPHY = re.compile(r"\\begin\s*\{thebibliography\}(.*?)\\end\s*\{thebibliography\}", re.S)
_DOCUMENT = re.compile(r"\\begin\s*\{document\}")
_COMMAND = re.compile(r"\\(?:([A-Za-z@]+)\*?|[^\r\n])")
_CITE = re.compile(
    r"(?:cite(?:p|t|alt|alp|author|year(?:par)?|title|url|online|num)?|"
    r"(?:auto|paren|text|foot|footfull|smart|super|full)cite)(s)?", re.I
)
_ID = re.compile(r"\d{4}-\d{4,5}")
_TOTALS = ("entry_before", "entry_after", "from_bib", "from_bibitem", "unresolved",
           "field_conflicts", "versions_without_bibliography")


def _arguments(text: str, pos: int, *, multiple: bool = False):
    """Yield braced arguments, allowing optional arguments before each group."""
    while True:
        while (end := _group_end(text, pos, "[")) is not None:
            pos = end
        if (end := _group_end(text, pos, "{")) is None:
            return
        start = text.index("{", pos, end)
        yield text[start + 1:end - 1]
        if not multiple:
            return
        pos = end


def _bibitems(text: str) -> list[str]:
    items = []
    for environment in _BIBLIOGRAPHY.finditer(text):
        start, stop = environment.span(1)
        offsets = [m.start() for m in _COMMAND.finditer(text, start, stop) if m[1] == "bibitem"]
        items.extend(text[start:end].strip() for start, end in zip(offsets, offsets[1:] + [stop]))
    return items


def _read_bib(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def build_bib_source(arxiv_id: str, version: int, directory: Path,
                     root: str, text: str, receipt_files: set[str]) -> BibSource:
    """Extract literal references and citation keys for a verified Version."""
    text = _IGNORED.sub(lambda m: m[0].split("%", 1)[0] if m["comment"] else " ", text)
    prose = _BIBLIOGRAPHY.sub(" ", text)
    bib_files, missing = {}, set()
    for command in _COMMAND.finditer(prose):
        if command[1] not in {"bibliography", "addbibresource"}:
            continue
        argument = next(_arguments(prose, command.end()), "")
        names = argument.split(",") if command[1] == "bibliography" else [argument]
        for name in names:
            name = name.strip()
            if not name:
                continue
            if command[1] == "bibliography" and not name.lower().endswith(".bib"):
                name += ".bib"
            if not safe_member(name) or any(char in name for char in "#{}~$"):
                missing.add(name)
                continue
            relative = PurePosixPath(name)
            candidates = ((PurePosixPath(root).parent / relative).as_posix(), relative.as_posix())
            match = next((p for p in candidates if p in receipt_files and p.lower().endswith(".bib")), None)
            if match is None:
                missing.add(name)
            elif match not in bib_files:
                bib_files[match] = _read_bib(directory / match)

    if document := _DOCUMENT.search(prose):
        prose = prose[document.end():]
    cite_keys = []
    for command in _COMMAND.finditer(prose):
        if command[1] and (cite := _CITE.fullmatch(command[1])):
            for argument in _arguments(prose, command.end(), multiple=bool(cite[1])):
                cite_keys.extend(key.strip() for key in argument.split(",") if key.strip())
    return BibSource(arxiv_id, version, bib_files, sorted(missing), _bibitems(text), cite_keys)


def run(data_dir: Path, size: int, seed: int) -> dict:
    corpus = FileCorpus(data_dir)
    ids = sorted(path.stem.replace("-", ".") for path in (data_dir / "metadata").glob("*.json")
                 if _ID.fullmatch(path.stem))
    if not 1 <= size <= len(ids):
        raise ValueError(f"Requested {size} Publications, found {len(ids)} metadata files")
    sample = sorted(random.Random(seed).sample(ids, size))
    totals = dict.fromkeys(_TOTALS, 0)
    versions, issues, source_issues, unresolved = Counter(), Counter(), Counter(), Counter()
    checks = Counter()
    invalid_metadata, partial, failures, entry_counts = [], [], [], []
    assembly_failures = []
    merge_seconds = repeat_seconds = 0.0

    with measure("bibtex sample") as timing:
        for arxiv_id in sample:
            try:
                publication = corpus.read_publication(arxiv_id)
            except (OSError, KeyError, TypeError, ValueError):
                invalid_metadata.append(arxiv_id)
                continue
            sources = []
            for version in range(1, publication.versions + 1):
                directory = corpus.version_path(arxiv_id, version)
                bundle = assemble_source(directory, require_receipt=True)
                versions[bundle.status] += 1
                source_issues.update(issue.code for issue in bundle.issues)
                if bundle.status == "error":
                    assembly_failures.append({
                        "arxiv_id": arxiv_id,
                        "version": version,
                        "codes": sorted({issue.code for issue in bundle.issues if issue.severity == "error"}),
                    })
                    continue
                if bundle.status == "empty_non_tex":
                    source = BibSource(arxiv_id, version, {}, [], [], [])
                else:
                    receipt = json.loads((directory / "source.json").read_bytes())
                    source = build_bib_source(arxiv_id, version, directory, bundle.root,
                                              bundle.text, set(receipt["files"]))
                sources.append(source)
                errors = shared_types.validate_B_prime(source, raise_on_error=False)
                checks["bib_source_failed" if errors else "bib_source_passed"] += 1
                if errors:
                    failures.append({"arxiv_id": arxiv_id, "version": version,
                                     "check": "validate_B_prime", "error_count": len(errors),
                                     "example": errors[0]})
            if len(sources) != publication.versions:
                partial.append(arxiv_id)
            if not sources:
                continue

            start = perf_counter()
            result = merge_bibtex(arxiv_id, sources)
            merge_seconds += perf_counter() - start
            for key in _TOTALS:
                totals[key] += result.stats[key]
            entry_counts.append({"arxiv_id": arxiv_id, "versions": len(sources),
                                 "entry_before": result.stats["entry_before"],
                                 "entry_after": result.stats["entry_after"]})
            issues.update(issue["code"] for issue in result.stats["issues"])
            unresolved.update(issue["reason"] for issue in result.stats["unresolved_keys"])
            checks["invalid_years"] += len(result.stats["invalid_years"])
            checks["publications_processed"] += 1
            checks["multi_version_publications_processed"] += len(sources) > 1
            blank_keys = sum(not row["citation_key"].strip() for row in result.entries)
            checks["blank_citation_key_entries"] += blank_keys
            checks["publications_with_blank_citation_keys"] += blank_keys > 0
            from_records(result.entries, "bibtex")
            checks["bibtex_schema_passed"] += 1
            errors = shared_types.validate_D(result, sources, raise_on_error=False)
            checks["bib_result_failed" if errors else "bib_result_passed"] += 1
            if errors:
                failures.append({"arxiv_id": arxiv_id, "check": "validate_D", "error_count": len(errors),
                                 "example": errors[0]})
            start = perf_counter()
            repeat = merge_bibtex(arxiv_id, list(reversed(sources)))
            repeat_seconds += perf_counter() - start
            if json.dumps(asdict(repeat)) != json.dumps(asdict(result)):
                raise ValueError(f"Unstable BibResult for {arxiv_id}")
            checks["repeatable_bib_results"] += 1

    return {
        "bibtex_version": BIBTEX_VERSION,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "sample": {"data_dir": data_dir.as_posix(), "size": size, "seed": seed, "arxiv_ids": sample},
        "input_method": "Literal bibliography declarations and citation commands in assembled TeX (benchmark adapter)",
        "versions_by_assembly_status": dict(versions),
        "versions_expected": sum(versions.values()),
        "invalid_metadata_publications": invalid_metadata,
        "publications_missing_assembled_versions": partial,
        "assembly_failures": assembly_failures,
        **totals,
        "duplicates_removed": totals["entry_before"] - totals["entry_after"],
        "largest_bibliographies": sorted(entry_counts, key=lambda row: -row["entry_before"])[:5],
        "unresolved_by_reason": dict(unresolved),
        "bibtex_issues_by_code": dict(issues),
        "source_issues_by_code": dict(source_issues),
        "checks": {
            "shared_types_available": True,
            "shared_types_sha256": file_digest(Path(shared_types.__file__)),
            **checks,
        },
        "boundary_failures": failures,
        "timing": {**timing.to_dict(), "merge_seconds": round(merge_seconds, 6),
                   "repeat_merge_seconds": round(repeat_seconds, 6)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("metrics/bibtex.json"))
    args = parser.parse_args()
    metrics = run(args.data_dir, args.size, args.seed)
    write_json(args.output, metrics)
    print(args.output)


if __name__ == "__main__":
    main()
