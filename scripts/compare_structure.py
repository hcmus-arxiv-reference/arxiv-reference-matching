"""Compare heading tokens on the shared M2 sample and score the reviewed Versions.

The optional benchmark dependency is pylatexenc==2.10 (LatexWalker.get_token):
https://pylatexenc.readthedocs.io/en/latest/latexwalker/
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from scripts.m2_sample import verify_sample
from src.common.corpus import file_digest
from src.common.json_io import write_json
from src.common.schema import publication_key
from src.parse.source import _scan, assemble_source
from src.parse.structure import build_structure
from src.parse.types import SECTION_KINDS, Section

HEADINGS = set(SECTION_KINDS) - {"document"}


def custom_tokens(text):
    commands = []
    _scan(text, "", commands)
    return {(t.start, t.name) for t in commands if t.name in HEADINGS}


def walker_tokens(text):
    from pylatexenc.latexwalker import LatexWalker, LatexWalkerEndOfStream

    walker = LatexWalker(text)
    pos = 0
    result = set()
    while pos < len(text):
        try:
            token = walker.get_token(pos)
        except LatexWalkerEndOfStream:
            break
        if token.tok == "macro" and token.arg in HEADINGS:
            result.add((token.pos, token.arg))
        pos = token.pos + token.len
    return result


def headings(section):
    """Yield all non-root heading nodes in reading order."""
    for child in section.children:
        if isinstance(child, Section):
            yield child
            yield from headings(child)


def evaluate(plan_path, labels_path, corpus):
    import pylatexenc

    plan = json.loads(plan_path.read_bytes())
    check = verify_sample(plan, corpus)
    if plan["data_origin"] != "corpus" or check["verified"] != len(plan["publications"]):
        raise ValueError("Benchmark requires the complete verified real sample")
    totals = Counter()
    times = Counter()
    errors = []
    for paper in plan["publications"]:
        for entry in paper["versions"]:
            directory = corpus / "raw" / publication_key(paper["arxiv_id"]) / f'v{entry["version"]}'
            source = assemble_source(directory, require_receipt=True)
            totals[source.status] += 1
            if source.status in {"empty_non_tex", "error"}:
                continue
            tokens = []
            for scanner in (custom_tokens, walker_tokens):
                start = perf_counter()
                try:
                    tokens.append(scanner(source.text))
                except (ValueError, RecursionError) as error:
                    errors.append([paper["arxiv_id"], entry["version"], scanner.__name__, str(error)])
                    break
                finally:
                    times[scanner.__name__] += perf_counter() - start
            if len(tokens) == 2:
                a, b = tokens
                totals.update(compared_versions=1, common=len(a & b), custom_only=len(a-b),
                              walker_only=len(b-a))
    rows = []
    lexical_scores = {name: Counter() for name in ("custom_tokens", "walker_tokens")}
    labels = json.loads(labels_path.read_bytes())
    for row in labels["items"]:
        aid, version = row["arxiv_id"], row["version"]
        directory = corpus / "raw" / publication_key(aid) / f"v{version}"
        source = assemble_source(directory, require_receipt=True)
        if source.status == "error" or sha256(source.text.encode()).hexdigest() != row["assembled_sha256"]:
            raise ValueError(f"Label source mismatch: {aid}v{version}")
        expected = {(p, k) for k, offsets in row["offsets_by_kind"].items() for p in offsets}
        for scanner in (custom_tokens, walker_tokens):
            candidates = scanner(source.text)
            lexical_scores[scanner.__name__].update(correct=len(expected & candidates),
                                                    extra=len(candidates - expected),
                                                    missed=len(expected - candidates))
        tree, _ = build_structure(source, aid, version, directory)
        actual = {(n.span[0], n.kind) for n in headings(tree.root)}
        rows.append(dict(arxiv_id=aid, expected=len(expected), correct=len(actual & expected),
                         missing=sorted(expected-actual), extra=sorted(actual-expected)))
    return dict(seed=plan["seed"], plan_sha256=file_digest(plan_path),
                dataset_revision=labels["dataset_revision"], publications=len(plan["publications"]),
                pylatexenc=pylatexenc.__version__, totals=dict(totals), errors=errors,
                seconds={k:round(v,3) for k,v in times.items()}, labels_sha256=file_digest(labels_path),
                heading_expected=sum(r["expected"] for r in rows),
                heading_correct=sum(r["correct"] for r in rows), reviewed_versions=rows,
                labeled_token_counts=lexical_scores)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "labels", "corpus", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    write_json(args.output, evaluate(args.plan, args.labels, args.corpus))
