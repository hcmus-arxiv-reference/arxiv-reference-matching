"""The manual-labelling page embeds every sheet row and candidate, and nothing escapes the script."""
import csv
import json
import re
from pathlib import Path

import pytest

from scripts.m3_label_ui import DATA_PLACEHOLDER, TEMPLATE, load_sheets, main, render

COLUMNS = ["arxiv_id", "citation_key", "ref_arxiv_id", "confidence", "labeler", "note", "entry",
           "hint_1", "score_1", "hint_title_1"]


def _write(path: Path, columns, rows, bom=False):
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _work(tmp_path: Path) -> Path:
    (tmp_path / "candidates").mkdir()
    rows = [
        {"arxiv_id": "2508.00001", "citation_key": "a", "ref_arxiv_id": "", "confidence": "", "labeler": "x",
         "note": "", "entry": '@article{a, title={Attention, "all" you need}}', "hint_1": "1706.03762",
         "score_1": "1.0", "hint_title_1": "Attention Is All You Need"},
        {"arxiv_id": "2508.00001", "citation_key": "b", "ref_arxiv_id": "", "confidence": "", "labeler": "x",
         "note": "", "entry": "\\bibitem{b} </script><script>alert(1)</script>", "hint_1": "",
         "score_1": "", "hint_title_1": ""},
    ]
    _write(tmp_path / "labels-x-r.csv", COLUMNS, rows, bom=True)
    _write(tmp_path / "candidates" / "2508-00001.csv",
           ["ref_arxiv_id", "ref_title", "ref_authors", "ref_submission_date"],
           [{"ref_arxiv_id": "1706.03762", "ref_title": "Attention Is All You Need", "ref_authors": "",
             "ref_submission_date": "2017-06-12"}])
    return tmp_path


def _embedded(html: str) -> list[dict]:
    match = re.search(r"const SHEETS = (.*);\n", html)
    return json.loads(match[1].replace("<\\/", "</"))


def test_template_has_one_placeholder():
    assert TEMPLATE.count(DATA_PLACEHOLDER) == 1


def test_page_embeds_rows_columns_and_candidates(tmp_path):
    sheets = load_sheets(_work(tmp_path))
    data = _embedded(render(sheets))
    assert [s["name"] for s in data] == ["labels-x-r.csv"]
    assert data[0]["columns"] == COLUMNS
    assert [r["citation_key"] for r in data[0]["rows"]] == ["a", "b"]
    assert data[0]["rows"][0]["entry"] == '@article{a, title={Attention, "all" you need}}'
    assert data[0]["candidates"]["2508.00001"][0]["ref_arxiv_id"] == "1706.03762"


def test_entry_cannot_close_the_script_block(tmp_path):
    html = render(load_sheets(_work(tmp_path)))
    script = html.split("<script>", 1)[1]
    assert script.count("</script>") == 1          # only the real end tag of the page script
    assert _embedded(html)[0]["rows"][1]["entry"].endswith("</script>")


def test_cli_writes_page_and_rejects_empty_folder(tmp_path):
    (tmp_path / "w").mkdir()
    work = _work(tmp_path / "w")
    assert main(["--work-dir", str(work)]) == 0
    assert (work / "gan-nhan.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit):
        main(["--work-dir", str(tmp_path / "empty")])
