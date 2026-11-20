"""M3 labelling tools: scripts/m3_label_sheet.py and scripts/m3_check_labels.py (docs/m3-gan-nhan.md)."""
import csv
import json

from scripts import m3_check_labels as checker
from scripts import m3_label_sheet as sheet
from src.common.corpus import file_digest
from src.common.schema import publication_key

PID = "2508.03014"


def _write_version(root, pid, cited, extra_bib=0, bibitem=False):
    """One verified Version v1 citing ``cited`` keys, each with a .bib entry, plus uncited ones.

    Returns the Publication folder (``<root>/<publication key>``) as the crawler lays it out."""
    directory = root / publication_key(pid) / "v1"
    directory.mkdir(parents=True)
    keys = [f"k{i}" for i in range(cited)]
    body = " ".join(f"Claim \\cite{{{k}}}." for k in keys)
    if bibitem:
        items = "".join(f"\\bibitem{{{k}}} A. Author. Paper number {k}. 2020.\n" for k in keys)
        tex = f"\\documentclass{{article}}\\begin{{document}}{body}\n\\begin{{thebibliography}}{{9}}\n{items}\\end{{thebibliography}}\\end{{document}}"
        files = {"main.tex": tex}
    else:
        bib = "".join(f"@article{{{k}, title={{Paper number {k}}}, year={{2020}}}}\n"
                      for k in keys + [f"unused{i}" for i in range(extra_bib)])
        files = {"main.tex": f"\\documentclass{{article}}\\begin{{document}}{body}\\bibliography{{refs}}\\end{{document}}",
                 "refs.bib": bib}
    for name, text in files.items():
        (directory / name).write_text(text)
    (directory / "source.json").write_text(json.dumps({
        "format": 1, "arxiv_id": pid, "version": 1, "status": "success", "checksum": "0" * 64,
        "files": {name: file_digest(directory / name) for name in files}}))
    return directory.parent


class FakeSource:
    def __init__(self, dirs, refs):
        self.dirs, self.refs = dirs, refs

    def ids(self):
        return sorted(self.dirs)

    def references(self, arxiv_id):
        return self.refs.get(arxiv_id, [])

    def publication_dir(self, arxiv_id):
        return self.dirs[arxiv_id]


def _refs(n):
    return [{"ref_arxiv_id": f"2001.{i:05d}", "ref_title": f"Paper number k{i}"} for i in range(n)]


def test_bib_entry_text_keeps_the_first_copy_and_skips_strings():
    bib = {"a.bib": "@string{x = {y}}\n@article{k, title={One {Nested} brace}}\n@article{k, title={Two}}"}
    entries = sheet.bib_entries(bib)
    assert list(entries) == ["k"] and entries["k"].endswith("{One {Nested} brace}}")


def test_hint_prefers_a_written_arxiv_id_then_title_overlap():
    refs = [{"ref_arxiv_id": "1706.03762", "ref_title": "Attention is all you need"},
            {"ref_arxiv_id": "1810.04805", "ref_title": "BERT: Pre-training of deep bidirectional transformers"}]
    assert sheet.hints("Vaswani et al. Attention is all you need. NeurIPS 2017.", refs)[0][:2] == ("1706.03762", 1.0)
    assert sheet.hints("Devlin. Something else. arXiv:1810.04805v2", refs)[0][:2] == ("1810.04805", 1.0)
    assert sheet.hints("Unrelated book on cooking.", refs) == []


def test_only_cited_entries_count_and_the_range_rule_applies(tmp_path):
    dirs = {"2508.00001": _write_version(tmp_path, "2508.00001", cited=25, extra_bib=500),  # uncited ignored
            "2508.00002": _write_version(tmp_path, "2508.00002", cited=12),                 # too few
            "2508.00003": _write_version(tmp_path, "2508.00003", cited=22, bibitem=True)}   # via \bibitem
    source = FakeSource(dirs, {pid: _refs(30) for pid in dirs})
    chosen, tried = sheet.select(source, count=3, spare=0, log=lambda *_: None)  # asks for 3: all are tried
    assert sorted(p["arxiv_id"] for p in chosen) == ["2508.00001", "2508.00003"]
    assert {p["arxiv_id"]: len(p["rows"]) for p in chosen} == {"2508.00001": 25, "2508.00003": 22}
    assert {t["arxiv_id"]: t.get("reason") for t in tried}["2508.00002"] == "entries_below_range"


def test_selection_is_seeded_and_skips_publications_with_few_references(tmp_path):
    dirs = {pid: _write_version(tmp_path, pid, cited=21) for pid in (f"2508.{i:05d}" for i in range(1, 9))}
    refs = {pid: _refs(30 if pid != "2508.00001" else 3) for pid in dirs}
    first, _ = sheet.select(FakeSource(dirs, refs), count=3, spare=1, log=lambda *_: None)
    again, _ = sheet.select(FakeSource(dirs, refs), count=3, spare=1, log=lambda *_: None)
    assert [p["arxiv_id"] for p in first] == [p["arxiv_id"] for p in again]
    assert "2508.00001" not in {p["arxiv_id"] for p in first}
    # Excluding a chosen Publication moves the next one (the spare) up.
    excluded = first[0]["arxiv_id"]
    replaced, _ = sheet.select(FakeSource(dirs, refs), count=3, spare=0, exclude={excluded}, log=lambda *_: None)
    assert [p["arxiv_id"] for p in replaced] == [p["arxiv_id"] for p in first[1:]]


def test_sheet_then_checker_round_trip(tmp_path):
    dirs = {PID: _write_version(tmp_path, PID, cited=20)}
    source = FakeSource(dirs, {PID: _refs(20)})
    out = tmp_path / "out"
    summary = sheet.main(["--labeler", "bao", "--out", str(out), "--count", "1", "--spare", "0"], source=source)
    path = out / summary["sheet"]
    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 20 and rows[0]["hint_1"] == "2001.00000"

    refs = {PID: {r["ref_arxiv_id"] for r in source.references(PID)}}
    errors, _ = checker.check(rows, list(rows[0]), refs)
    assert any("confidence" in e for e in errors)          # untouched sheet is not labelled yet

    for row in rows:
        row["ref_arxiv_id"], row["confidence"] = row["hint_1"], "sure"
    rows[1]["ref_arxiv_id"], rows[2]["ref_arxiv_id"] = "", "arXiv:2001.00002v1"
    rows[3]["ref_arxiv_id"] = "9999.99999"
    errors, summary = checker.check(rows, list(rows[0]), refs)
    assert len(errors) == 2
    assert "sai dạng" in errors[0] and "không có trong references" in errors[1]
    assert summary["empty"] == 1

    rows[2]["ref_arxiv_id"], rows[3]["ref_arxiv_id"] = "2001.00002", "2001.00003"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    clean = tmp_path / "bao.csv"
    assert checker.main([str(path), "--out", str(clean)]) == 0
    written = list(csv.DictReader(clean.open()))
    assert list(written[0]) == checker.LABEL_COLUMNS and len(written) == 20


def test_checker_flags_duplicates_and_small_publications():
    rows = [{"arxiv_id": PID, "citation_key": "a", "ref_arxiv_id": "", "confidence": "sure",
             "labeler": "bao", "note": ""}] * 2
    errors, _ = checker.check(rows, checker.LABEL_COLUMNS, None)
    assert any("xuất hiện 2 lần" in e for e in errors)
    assert any("cần ít nhất 20" in e for e in errors)
