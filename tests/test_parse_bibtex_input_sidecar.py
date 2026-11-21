"""Check reviewed root provenance and archive bibliography through normal APIs."""
import json
from pathlib import Path

import pytest

from src.common.corpus import file_digest
from src.common.json_io import write_json
from src.parse.bibtex import merge_bibtex
from src.parse.bibtex_input import build_bib_source, load_root_reviews
from src.parse.types import validate_D


ID = "2508.02872"


def version(tmp_path, files):
    directory = tmp_path / "raw" / "2508-02872" / "v1"
    directory.mkdir(parents=True)
    for name, text in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    write_json(directory / "source.json", {
        "format": 1, "arxiv_id": ID, "version": 1, "status": "success", "checksum": "fixture",
        "files": {name: file_digest(directory / name) for name in files},
    })
    return directory


def supplement(tmp_path, directory, files):
    root = tmp_path / "supplement"
    target = root / "2508-02872" / "v1"
    for name, text in files.items():
        path = target / "files" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    write_json(target / "manifest.json", {
        "format": 1, "arxiv_id": ID, "version": 1,
        "receipt_sha256": file_digest(directory / "source.json"), "archive_sha256": "a" * 64,
        "files": {name: file_digest(target / "files" / name) for name in files},
    })
    return root


@pytest.mark.parametrize("command,filename", [
    (r"\bibliography{refs}", "main.bbl"),
    (r"\input{refs.bbl}", "refs.bbl"),
])
def test_declared_bbl_supplement_restores_entries_without_touching_raw(tmp_path, command, filename):
    directory = version(tmp_path, {"main.tex": r"\documentclass{article}\begin{document}\cite{k}" + command + r"\end{document}"})
    receipt_before = (directory / "source.json").read_bytes()
    root = supplement(tmp_path, directory, {
        filename: r"\begin{thebibliography}{1}\bibitem{k} A. Doe. Title. 2020.\end{thebibliography}",
        "unused.bib": "@misc{unused, title={Unused}}",
    })
    bundle, bib, provenance = build_bib_source(ID, 1, directory, supplement_dir=root)
    result = merge_bibtex(ID, [bib])
    assert validate_D(result, [bib]) == []
    assert result.key_map == {"1": {"k": "k"}}
    assert list(provenance["files"]) == [filename]
    assert bib.bib_files == {}
    assert (directory / "source.json").read_bytes() == receipt_before
    assert not (directory / filename).exists()


def test_missing_bib_is_recovered_and_checksum_changes_are_rejected(tmp_path):
    directory = version(tmp_path, {"main.tex": r"\documentclass{article}\begin{document}\cite{k}\bibliography{refs}\end{document}"})
    root = supplement(tmp_path, directory, {"refs.bib": "@misc{k,title={Title}}"})
    _, bib, _ = build_bib_source(ID, 1, directory, supplement_dir=root)
    assert bib.missing_bib == [] and list(bib.bib_files) == ["refs.bib"]
    path = root / "2508-02872/v1/files/refs.bib"
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        build_bib_source(ID, 1, directory, supplement_dir=root)


def test_root_review_selects_a_real_root_and_is_bound_to_receipt(tmp_path):
    text = r"\documentclass{article}\begin{document}Body\end{document}"
    directory = version(tmp_path, {"paper.tex": text, "supplement.tex": text})
    review = {"arxiv_id": ID, "version": 1, "root_file": "paper.tex",
              "receipt_sha256": file_digest(directory / "source.json"),
              "root_sha256": file_digest(directory / "paper.tex"), "reason": "Reviewed main paper"}
    path = tmp_path / "roots.json"
    write_json(path, {"format": 1, "reviews": [review]})
    reviews = load_root_reviews(path)
    bundle, _, _ = build_bib_source(ID, 1, directory, root_review=reviews[(ID, 1)])
    assert bundle.root == "paper.tex"
    review["receipt_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="no longer matches"):
        build_bib_source(ID, 1, directory, root_review=review)
    write_json(path, {"format": 1, "reviews": [review, review]})
    with pytest.raises(ValueError, match="Duplicate"):
        load_root_reviews(path)
