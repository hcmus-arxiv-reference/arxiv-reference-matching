"""File-only corpus view: verified Versions and complete Publications (data contract 3.2-3.3)."""
from dataclasses import asdict
import hashlib
import json

from src.common.corpus import FileCorpus, Publication

PID = "2508.02872"
KEY = "2508-02872"


def write_version(root, version, files, status=None):
    directory = root / "raw" / KEY / f"v{version}"
    directory.mkdir(parents=True)
    for name, text in files.items():
        (directory / name).write_text(text)
    digests = {n: hashlib.sha256((directory / n).read_bytes()).hexdigest() for n in files}
    status = status or ("success" if any(n.endswith(".tex") for n in files) else "non_tex")
    (directory / "source.json").write_text(json.dumps({
        "format": 1, "arxiv_id": PID, "version": version, "status": status,
        "checksum": "payload-sha", "files": digests}))
    return directory


def make_corpus(root, *, versions=2, references=True):
    publication = Publication(PID, "Title", ["A"], "2025-08-04",
                              ["2025-08-05"] * (versions - 1), None, versions)
    (root / "metadata").mkdir()
    (root / "metadata" / f"{KEY}.json").write_text(
        json.dumps({"format": 1, "publication": asdict(publication)}))
    write_version(root, 1, {"main.tex": "\\documentclass{article}", "refs.bib": "@misc{a,}"})
    if versions > 1:
        write_version(root, 2, {})  # PDF-only Version: verified but non_tex
    if references:
        (root / "references").mkdir()
        rows = [{"citedPaper": {"paperId": "s2", "externalIds": {"ArXiv": "2401.00001v2"}}}]
        (root / "references" / f"{KEY}.json").write_text(
            json.dumps({"format": 1, "arxiv_id": PID, "rows": rows}))
    return FileCorpus(root)


def test_complete_publication_counts_non_tex_as_verified(tmp_path):
    state = make_corpus(tmp_path).publication(PID)
    assert state.complete and state.sources_complete
    assert (state.expected_versions, state.verified_versions, state.non_tex_versions) == (2, 2, 1)
    assert [s.status for s in state.sources()] == ["success", "non_tex"]
    assert all(v.task is None for v in state.versions)


def test_edited_source_file_is_not_a_verified_version(tmp_path):
    corpus = make_corpus(tmp_path)
    (tmp_path / "raw" / KEY / "v1" / "main.tex").write_text("edited by hand")
    state = corpus.publication(PID)
    assert not state.sources_complete and state.verified_versions == 1
    assert state.versions[0].source is None


def test_missing_version_directory_keeps_expected_count(tmp_path):
    corpus = make_corpus(tmp_path, versions=1)
    metadata = tmp_path / "metadata" / f"{KEY}.json"
    payload = json.loads(metadata.read_text())
    payload["publication"].update(versions=2, revised_dates=["2025-08-05"])
    metadata.write_text(json.dumps(payload))
    state = corpus.publication(PID)
    assert state.expected_versions == 2 and state.verified_versions == 1
    assert not state.complete


def test_missing_references_only_breaks_complete(tmp_path):
    state = make_corpus(tmp_path, references=False).publication(PID)
    assert state.sources_complete and not state.references_ok and not state.complete


def test_missing_or_invalid_metadata_has_no_versions(tmp_path):
    corpus = make_corpus(tmp_path)
    metadata = tmp_path / "metadata" / f"{KEY}.json"
    payload = json.loads(metadata.read_text())
    payload["publication"]["revised_dates"] = []  # two Versions need one revision date
    metadata.write_text(json.dumps(payload))
    state = corpus.publication(PID)
    assert state.publication is None and state.versions == () and not state.sources_complete
    metadata.unlink()
    assert corpus.publication(PID).publication is None


def test_references_for_another_publication_are_rejected(tmp_path):
    corpus = make_corpus(tmp_path)
    path = tmp_path / "references" / f"{KEY}.json"
    payload = json.loads(path.read_text())
    payload["arxiv_id"] = "2508.02873"
    path.write_text(json.dumps(payload))
    assert not corpus.publication(PID).references_ok


def test_crawl_modules_reexport_moved_names():
    from src.common import corpus
    from src.crawl import discovery, semantic_scholar, source, storage
    assert source.verified_source is corpus.verified_source
    assert source.SourceResult is corpus.SourceResult
    assert discovery.Publication is corpus.Publication
    assert semantic_scholar.reference_rows is corpus.reference_rows
    assert storage.require_id("2508.02872") == "2508.02872"
