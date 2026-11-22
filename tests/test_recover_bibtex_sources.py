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


class _FakeClient:
    """Serve prepared archive bytes per URL and count requests (no network)."""

    def __init__(self, archives):
        self.archives, self.calls = archives, []

    def get(self, url, resume=True):
        self.calls.append(url)
        body = self.archives.get(url)

        class Response:
            status = 200 if body is not None else 404

        Response.body = body
        return Response()


def _range_corpus(tmp_path, papers):
    """Corpus in M1 layout: metadata/<key>.json and raw/<key>/v1 with a valid receipt."""
    import hashlib
    import json

    corpus = tmp_path / "corpus"
    for aid, tex in papers.items():
        key = aid.replace(".", "-")
        write_json(corpus / "metadata" / f"{key}.json", {"format": 1, "publication": {
            "arxiv_id": aid, "title": "T", "authors": ["A"], "submission_date": "2025-08-04",
            "revised_dates": [], "venue": None, "versions": 1}})
        directory = corpus / "raw" / key / "v1"
        directory.mkdir(parents=True)
        (directory / "main.tex").write_bytes(tex.encode())
        files = {"main.tex": file_digest(directory / "main.tex")}
        write_json(directory / "source.json", {
            "format": 1, "arxiv_id": aid, "version": 1, "status": "success", "files": files,
            "checksum": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()})
    return corpus


def test_range_mode_recovers_only_missing_bibliography_and_resumes(tmp_path):
    from scripts.recover_bibtex_sources import recover_corpus

    needs = r"\documentclass{article}\begin{document}\cite{k}\bibliography{refs}\end{document}"
    fine = r"\documentclass{article}\begin{document}No citations.\end{document}"
    corpus = _range_corpus(tmp_path, {"2508.02872": needs, "2508.02873": fine})
    url = "https://export.arxiv.org/src/2508.02872v1"
    client = _FakeClient({url: archive_file(tmp_path, {"main.tex": needs, "refs.bib": "@misc{k}"}).read_bytes()})
    out = tmp_path / "supplement"

    report = recover_corpus(corpus, tmp_path / "archives", out, client=client, keep_archives=False)
    assert client.calls == [url], "only the Version that declares a missing .bib is downloaded"
    assert report["by_status"] == {"verified": 1}
    assert (out / "2508-02872/v1/files/refs.bib").read_text() == "@misc{k}"
    assert not (tmp_path / "archives/2508.02872v1.source").exists()

    again = recover_corpus(corpus, tmp_path / "archives", out, client=client)
    assert client.calls == [url], "an existing sidecar is reused without a new request"
    assert again["versions"][0]["resumed"] is True


def test_range_mode_reports_mismatching_archive_and_continues(tmp_path):
    from scripts.recover_bibtex_sources import recover_corpus

    tex = r"\documentclass{article}\begin{document}\cite{k}\bibliography{refs}\end{document}"
    corpus = _range_corpus(tmp_path, {"2508.02872": tex, "2508.02874": tex})
    client = _FakeClient({
        "https://export.arxiv.org/src/2508.02872v1": archive_file(tmp_path, {"main.tex": "changed"}).read_bytes(),
    })
    report = recover_corpus(corpus, tmp_path / "archives", tmp_path / "out", client=client)
    assert report["by_status"] == {"archive_mismatch": 1, "http_error": 1}


def test_range_mode_records_unparseable_version_and_continues(tmp_path):
    from scripts.recover_bibtex_sources import recover_corpus

    broken = r"\documentclass{article} no document environment \bibliography{refs}"
    needs = r"\documentclass{article}\begin{document}\cite{k}\bibliography{refs}\end{document}"
    corpus = _range_corpus(tmp_path, {"2508.02872": broken, "2508.02873": needs})
    url = "https://export.arxiv.org/src/2508.02873v1"
    client = _FakeClient({url: archive_file(tmp_path, {"main.tex": needs, "refs.bib": "@misc{k}"}).read_bytes()})
    report = recover_corpus(corpus, tmp_path / "archives", tmp_path / "out", client=client)
    assert report["by_status"] == {"source_failed": 1, "verified": 1}
    assert client.calls == [url]
