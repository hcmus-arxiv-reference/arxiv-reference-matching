"""Exercise the offline BibTeX benchmark using a synthetic crawl cache."""
from dataclasses import asdict

import pytest

from scripts.measure_bibtex import run
from scripts.m2_sample import make_plan
from src.common.corpus import Publication, file_digest
from src.common.json_io import write_json


ARXIV_ID = "2508.02872"
KEY = "2508-02872"


def test_measure_counts_entries_across_versions_and_includes_non_tex(tmp_path):
    publication = Publication(ARXIV_ID, "Test", [], "2025-08-04",
                              ["2025-08-05", "2025-08-06"], None, 3)
    write_json(tmp_path / "metadata" / f"{KEY}.json",
               {"format": 1, "publication": asdict(publication)})
    versions = [
        {
            "main.tex": r"\documentclass{article}\begin{document}\cite{old,missing}"
                        r"\bibliography{refs}\end{document}",
            "refs.bib": "@misc{old, title={Example title}, year={2020}}\n@misc{unused, title={Unused}}",
        },
        {
            "main.tex": r"\documentclass{article}\begin{document}\cite{new}"
                        r"\begin{thebibliography}{9}\bibitem{new} J. Smith. Example title. 2020."
                        r"\end{thebibliography}\end{document}",
        },
        {},
    ]
    for version, files in enumerate(versions, start=1):
        directory = tmp_path / "raw" / KEY / f"v{version}"
        directory.mkdir(parents=True)
        for name, text in files.items():
            (directory / name).write_text(text, encoding="utf-8")
        write_json(directory / "source.json", {
            "arxiv_id": ARXIV_ID, "version": version, "format": 1,
            "status": "success" if files else "non_tex", "checksum": "fixture",
            "files": {name: file_digest(directory / name) for name in files},
        })
        (directory / "metadata.json").write_bytes((tmp_path / "metadata" / f"{KEY}.json").read_bytes())

    report = run(tmp_path, size=1, seed=42)
    assert report["sample"]["arxiv_ids"] == [ARXIV_ID]
    assert report["versions_by_assembly_status"] == {"ready": 2, "empty_non_tex": 1}
    assert report["entry_before"] == 3 and report["entry_after"] == 1
    assert report["from_bib"] == 2 and report["from_bibitem"] == 1
    assert report["groups_before_filter"] == 2 and report["groups_filtered_out"] == 1
    assert report["duplicates_removed"] == 1
    assert report["unresolved_by_reason"] == {"missing_entry": 1}
    assert report["versions_without_bibliography"] == 1
    assert report["checks"]["repeatable_bib_results"] == 1
    assert report["checks"]["bib_source_passed"] == 3
    assert report["checks"]["bib_result_failed"] == 1

    plan = make_plan(tmp_path, size=1)
    plan_path = tmp_path / "sample.json"
    write_json(plan_path, plan)
    measured = run(tmp_path, sample_path=plan_path)
    assert measured["sample"]["arxiv_ids"] == [ARXIV_ID]
    assert measured["sample"]["seed"] == 20261112
    assert measured["sample"]["plan_sha256"] == file_digest(plan_path)
    assert measured["sample"]["data_origin"] == "corpus"
    assert measured["versions_expected"] == 3

    with pytest.raises(ValueError, match="cannot be combined"):
        run(tmp_path, size=1, seed=42, sample_path=plan_path)

    missing_source = tmp_path / "raw" / KEY / "v1" / "main.tex"
    missing_source.unlink()
    partial = run(tmp_path, size=1, seed=42)
    assert partial["publications_missing_assembled_versions"] == [ARXIV_ID]
    assert partial["assembly_failures"] == [{
        "arxiv_id": ARXIV_ID, "version": 1, "codes": ["invalid_receipt"],
    }]
    with pytest.raises(ValueError, match="Sample verification failed"):
        run(tmp_path, sample_path=plan_path)
