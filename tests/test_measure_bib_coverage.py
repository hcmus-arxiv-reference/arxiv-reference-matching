"""Static bibliography-source classification used for the report's coverage table."""
import hashlib
import json

from scripts.measure_bib_coverage import classify_version, measure
from src.common.corpus import file_digest
from src.common.json_io import write_json


def _version(root, aid, files, status="success"):
    key = aid.replace(".", "-")
    write_json(root / "metadata" / f"{key}.json", {"format": 1, "publication": {"arxiv_id": aid, "versions": 1}})
    directory = root / "raw" / key / "v1"
    directory.mkdir(parents=True)
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    digests = {name: file_digest(directory / name) for name in files}
    write_json(directory / "source.json", {
        "format": 1, "arxiv_id": aid, "version": 1, "status": status, "files": digests,
        "checksum": hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest()})
    return directory


def test_classes_follow_shipped_files_and_ignore_comments(tmp_path):
    doc = r"\documentclass{article}\begin{document}%s\end{document}"
    assert classify_version(_version(tmp_path / "a", "2508.00001",
                                     {"m.tex": doc % r"\bibliography{r}", "r.bib": "@misc{k}"})) == "bib_or_bibitem"
    assert classify_version(_version(tmp_path / "b", "2508.00002",
                                     {"m.tex": doc % r"\bibitem{k} A."})) == "bib_or_bibitem"
    assert classify_version(_version(tmp_path / "c", "2508.00003",
                                     {"m.tex": doc % r"\bibliography{refs}"})) == "declared_missing"
    assert classify_version(_version(tmp_path / "d", "2508.00004",
                                     {"m.tex": doc % r"\input{main.bbl}"})) == "declared_missing"
    assert classify_version(_version(tmp_path / "e", "2508.00005",
                                     {"m.tex": doc % "% \\bibliography{refs}\nNo refs."})) == "no_bibliography"
    assert classify_version(_version(tmp_path / "f", "2508.00006", {}, status="non_tex")) is None


def test_measure_counts_recovered_sidecars(tmp_path):
    corpus = tmp_path / "corpus"
    doc = r"\documentclass{article}\begin{document}\cite{k}\bibliography{refs}\end{document}"
    _version(corpus, "2508.00001", {"m.tex": doc})
    _version(corpus, "2508.00002", {"m.tex": doc})
    supplement = tmp_path / "supplement"
    write_json(supplement / "2508-00001" / "v1" / "manifest.json", {"format": 1})
    write_json(supplement / "recovery-report.json", {"by_status": {"verified": 1, "http_error": 1}})
    result = measure(corpus, supplement, "bao")
    assert result["versions"] == {"bib_or_bibitem": 0, "declared_missing": 2, "no_bibliography": 0}
    assert result["declared_missing_recovered"] == 1
    assert result["recovery_report"] == {"verified": 1, "http_error": 1}
