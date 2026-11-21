"""Đo kết quả của bộ phân tích Leaves trên bộ mẫu M2."""
import argparse
import json
import traceback
from collections import Counter
from pathlib import Path
from statistics import mean, median
from time import perf_counter

from src.common.corpus import file_digest
from src.common.json_io import write_json
from src.common.schema import publication_key
from src.parse.leaves import build_leaves
from src.parse.source import assemble_source
from src.parse.structure import build_structure
from src.parse.types import Block, Leaf, validate_B, validate_C


def walk(node):
    yield node
    for child in getattr(node, "children", ()):
        yield from walk(child)


def main():
    started = perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", nargs="?", type=Path, default=Path("configs/m2-sample-100.json"))
    parser.add_argument("corpus", nargs="?", type=Path, default=Path("data/m2-sample"))
    parser.add_argument("output", nargs="?", type=Path, default=Path("metrics/leaves.json"))
    args = parser.parse_args()
    plan_path = args.plan
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    corpus = args.corpus
    papers = plan["publications"]
    if plan["data_origin"] != "corpus" or len(papers) != 100:
        raise ValueError("Cần dùng danh sách mẫu thật gồm 100 bài.")

    counts = Counter()
    lengths = []
    failures = []
    validated = 0
    skipped = 0
    unsplit = 0

    for index, paper in enumerate(papers, 1):
        aid = paper["arxiv_id"]
        for entry in paper["versions"]:
            version = entry["version"]
            if entry["status"] == "non_tex":
                skipped += 1
                continue

            directory = corpus / "raw" / publication_key(aid) / f"v{version}"
            stage = "source"
            try:
                source = assemble_source(directory, require_receipt=True)
                stage = "structure"
                tree, _ = build_structure(source, aid, version, directory)
                validate_B(tree, source.text)

                stage = "leaves"
                result = build_leaves(tree)
                validate_C(result, tree)
                leaves = [node for node in walk(result.root) if isinstance(node, Leaf)]
                sentences = [leaf for leaf in leaves if leaf.kind == "sentence"]
                sentence_spans = {tuple(leaf.span) for leaf in sentences}

                # Đếm block môi trường được giữ nguyên thành một lá sentence.
                unsplit += sum(
                    isinstance(node, Block)
                    and node.type == "env"
                    and tuple(node.span) in sentence_spans
                    for node in walk(tree.root)
                )
                counts.update(leaf.kind for leaf in leaves)
                lengths.extend(len(leaf.raw) for leaf in sentences)
                validated += 1
            except Exception as error:
                failures.append({
                    "arxiv_id": aid,
                    "version": version,
                    "stage": stage,
                    "traceback": traceback.format_exc(limit=-3),
                    "error": f"{type(error).__name__}: {error}",
                })

        if index % 10 == 0:
            print(f"Đã xử lý {index}/{len(papers)} bài", flush=True)

    report = {
        "data_origin": plan["data_origin"],
        "plan_sha256": file_digest(plan_path),
        "publications": len(papers),
        "versions": sum(len(paper["versions"]) for paper in papers),
        "validated_versions": validated,
        "non_tex_versions": skipped,
        "failed_versions": len(failures),
        "failures": failures,
        "leaf_counts": {kind: counts[kind] for kind in ("sentence", "formula", "figure")},
        "sentence_length_unit": "characters in raw LaTeX",
        "sentence_length_mean": mean(lengths) if lengths else None,
        "sentence_length_median": median(lengths) if lengths else None,
        "unsplit_blocks": unsplit,
        "unsplit_definition": "Environment blocks preserved as one sentence with the same span, on validated versions.",
        "elapsed_seconds": round(perf_counter() - started, 3),
    }
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, report)
    print(f"{output}: {validated} validated, {skipped} non-TeX, {len(failures)} failed")


if __name__ == "__main__":
    main()
