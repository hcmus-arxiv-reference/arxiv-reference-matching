"""Verify recovery against synthetic archives, without network requests."""
import io
import tarfile

import pytest

from scripts.recover_bibtex_sources import prepare_sidecar
from src.common.corpus import file_digest
from src.common.json_io import write_json


def archive_file(tmp_path, members):
    path = tmp_path / "archive.source"
    with tarfile.open(path, mode="w:gz") as tar:
        for name, text in members.items():
            data = text.encode("utf-8")
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    return path


def test_sidecar_creation_reuses_identical_output_and_rejects_changed_source(tmp_path):
    directory = tmp_path / "raw/2508-02872/v1"
    directory.mkdir(parents=True)
    text = r"\documentclass{article}\begin{document}Body\end{document}"
    (directory / "main.tex").write_bytes(text.encode())
    write_json(directory / "source.json", {
        "format": 1, "arxiv_id": "2508.02872", "version": 1, "status": "success",
        "checksum": "fixture", "files": {"main.tex": file_digest(directory / "main.tex")},
    })
    archive = archive_file(tmp_path, {"main.tex": text, "main.bbl": "Bibliography", "figure.pdf": "Ignored"})
    destination = tmp_path / "supplement/2508-02872/v1"
    manifest = prepare_sidecar(archive, directory, destination)
    assert list(manifest["files"]) == ["main.bbl"]
    assert (destination / "files/main.bbl").read_text() == "Bibliography"
    assert prepare_sidecar(archive, directory, destination) == manifest
    changed = archive_file(tmp_path, {"main.tex": "Changed", "main.bbl": "Bibliography"})
    with pytest.raises(ValueError, match="differs from original"):
        prepare_sidecar(changed, directory, tmp_path / "bad")


def test_sidecar_rejects_path_escape_before_writing(tmp_path):
    directory = tmp_path / "raw/2508-02872/v1"
    directory.mkdir(parents=True)
    text = r"\documentclass{article}"
    (directory / "main.tex").write_bytes(text.encode())
    write_json(directory / "source.json", {
        "format": 1, "arxiv_id": "2508.02872", "version": 1, "status": "success",
        "checksum": "fixture", "files": {"main.tex": file_digest(directory / "main.tex")},
    })
    archive = archive_file(tmp_path, {"main.tex": text, "../escape.bbl": "Bad"})
    with pytest.raises(ValueError, match="Unsafe"):
        prepare_sidecar(archive, directory, tmp_path / "supplement")
    assert not (tmp_path / "escape.bbl").exists()
