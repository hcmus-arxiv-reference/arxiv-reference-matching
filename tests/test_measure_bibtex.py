"""Exercise the offline BibTeX benchmark using a synthetic crawl cache."""
from dataclasses import asdict

from scripts.measure_bibtex import build_bib_source, run
from src.common.corpus import Publication, file_digest
from src.common.json_io import write_json


ARXIV_ID = "2508.02872"
KEY = "2508-02872"


def test_build_bib_source_reads_only_declared_receipt_files(tmp_path):
    (tmp_path / "included.bib").write_text("@misc{a, title={A}}", encoding="utf-8")
    (tmp_path / "unlisted.bib").write_text("@misc{fake}", encoding="utf-8")
    text = r"""
        \addbibresource[location=local]{included.bib}
        \bibliography{missing,unlisted}
        \cite{preamble}
        \begin{document}
        % \cite{comment}
        \verb|\cite{literal} %| \citep[see][p. 2]{a, b}
        \begin{verbatim}\cite{literal}\end{verbatim}
        \parencites{c}[p. 4]{d}
        \begin{thebibliography}{9}
        \bibitem{b} J. Smith. A title. \cite{bibliography}
        \end{thebibliography}
    """
    source = build_bib_source(ARXIV_ID, 1, tmp_path, "main.tex", text, {"included.bib"})
    assert source.bib_files == {"included.bib": "@misc{a, title={A}}"}
    assert source.missing_bib == ["missing.bib", "unlisted.bib"]
    assert source.cite_keys_used == ["a", "b", "c", "d"]
    assert source.bibitems_raw == [r"\bibitem{b} J. Smith. A title. \cite{bibliography}"]


def test_measure_counts_entries_across_versions_and_includes_non_tex(tmp_path):
    publication = Publication(ARXIV_ID, "Test", [], "2025-08-04",
                              ["2025-08-05", "2025-08-06"], None, 3)
    write_json(tmp_path / "metadata" / f"{KEY}.json",
               {"format": 1, "publication": asdict(publication)})
    versions = [
        {
            "main.tex": r"\documentclass{article}\begin{document}\cite{old,missing}"
                        r"\bibliography{refs}\end{document}",
            "refs.bib": "@misc{old, title={Example title}, year={2020}}",
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

    report = run(tmp_path, size=1, seed=42)
    assert report["sample"]["arxiv_ids"] == [ARXIV_ID]
    assert report["versions_by_assembly_status"] == {"ready": 2, "empty_non_tex": 1}
    assert report["entry_before"] == 2 and report["entry_after"] == 1
    assert report["from_bib"] == report["from_bibitem"] == 1
    assert report["duplicates_removed"] == 1
    assert report["unresolved_by_reason"] == {"missing_entry": 1}
    assert report["versions_without_bibliography"] == 1
    assert report["checks"]["repeatable_bib_results"] == 1
    if report["checks"]["shared_types_available"]:
        assert report["checks"]["bib_source_passed"] == 3
        assert report["checks"]["bib_result_failed"] == 1
