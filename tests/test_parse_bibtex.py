"""M2.4b fixtures cover merging, schema compatibility and unresolved citations."""
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from src.common.schema import from_records, validate
from src.parse.bibtex import BibSource, merge_bibtex


ARXIV_ID = "2508.02872"
GOLDEN = Path(__file__).parent / "fixtures/m2/two-versions-cite-rename"


def _source(version, bib="", items=(), cites=()):
    return BibSource(ARXIV_ID, version, {"refs.bib": bib} if bib else {}, [], list(items), list(cites))


def test_two_versions_cite_rename_golden_and_parquet_schema():
    inputs = [BibSource(**json.loads((GOLDEN / f"B'.v{v}.json").read_text(encoding="utf-8"))) for v in (1, 2)]
    expected = json.loads((GOLDEN / "D.json").read_text(encoding="utf-8"))
    result = merge_bibtex(ARXIV_ID, inputs)
    assert asdict(result) == expected
    assert asdict(merge_bibtex(ARXIV_ID, list(reversed(inputs)))) == expected
    assert validate(from_records(result.entries, "bibtex"), "bibtex") == []


def test_bibtex_macros_crossref_and_author_lists():
    result = merge_bibtex(ARXIV_ID, [_source(1, r'''
@string{j = "Journal of " # "Examples"}
@proceedings{parent, title={Conference}, year=2019, journal=j, doi={10.1234/parent}}
@inproceedings{child, crossref={parent}, title={Child}, author={J. Smith and {Research and Development}}}
''', cites=["child"])])
    rows = {row["citation_key"]: row for row in result.entries}
    assert rows["child"]["year"] == 2019
    assert rows["child"]["journal"] == "Journal of Examples"
    assert rows["child"]["authors"] == ["J. Smith", "{Research and Development}"]
    assert rows["child"]["doi"] is None and len(rows) == 2


def test_newest_conflicting_value_with_complementary_fields_and_log():
    v1 = _source(1, "@article{old, title={Old title}, year=2020, doi={10.1234/EXAMPLE}}", cites=["old"])
    v2 = _source(2, "@article{new, title={New title}, doi={10.1234/example}}", cites=["new"])
    result = merge_bibtex(ARXIV_ID, [v2, v1])
    assert len(result.entries) == 1
    assert result.entries[0]["title"] == "New title"
    assert result.entries[0]["year"] == 2020
    assert result.key_map == {"1": {"old": "new"}, "2": {"new": "new"}}
    assert result.stats["conflicts"] == [{
        "citation_key": "new", "field": "title", "chosen": "New title", "chosen_version": 2,
        "alternatives": [{"version": 1, "key": "old", "value": "Old title"}],
    }]


def test_arxiv_identity_ignores_version_suffix_and_matches_bibitem():
    v1 = _source(1, items=[r"\bibitem[Smith]{old} J. Smith. \emph{Example title}. arXiv:2310.12345v1"], cites=["old"])
    v2 = _source(2, "@misc{new, title={Example title}, eprint={2310.12345v2}, archivePrefix={arXiv}}", cites=["new"])
    result = merge_bibtex(ARXIV_ID, [v1, v2])
    assert len(result.entries) == 1
    assert result.entries[0]["title"] == "Example title"
    assert result.entries[0]["year"] is None
    assert result.key_map["1"]["old"] == "new"


def test_missing_key_and_invalid_year_are_logged_without_fabricated_entries():
    v1 = _source(1, "@misc{real, title={A title}, year={forthcoming}}", cites=["real", "missing", "missing"])
    v2 = _source(2, items=[r"\bibitem{other} A. Doe. \emph{Another title}."], cites=["other"])
    result = merge_bibtex(ARXIV_ID, [v1, v2])
    assert all(entry["year"] is None for entry in result.entries)
    assert result.raw_years == {"real": "forthcoming"}
    assert result.stats["invalid_years"] == [{"version": 1, "key": "real", "value": "forthcoming"}]
    assert result.key_map["1"]["missing"] == "missing"
    assert result.stats["unresolved"] == 1
    assert result.stats["unresolved_keys"] == [{"version": 1, "key": "missing", "reason": "missing_entry"}]
    assert {entry["citation_key"] for entry in result.entries} == {"real", "other"}


def test_conflicting_strong_ids_do_not_merge_via_same_title_year():
    result = merge_bibtex(ARXIV_ID, [
        _source(1, "@article{same,title={Title},year=2020,doi={10.1234/a}}", cites=["same"]),
        _source(2, "@article{same,title={Title},year=2020,doi={10.1234/b}}", cites=["same"]),
        _source(3, "@article{uncertain,title={Title},year=2020}", cites=["uncertain"]),
    ])
    assert len(result.entries) == 3
    assert result.key_map == {"1": {"same": "same__2"}, "2": {"same": "same"}, "3": {"uncertain": "uncertain"}}
    assert {i["code"] for i in result.stats["issues"]} == {"ambiguous_title_year", "canonical_key_collision"}
    assert validate(from_records(result.entries, "bibtex"), "bibtex") == []


def test_duplicate_bib_key_retains_complementary_fields():
    result = merge_bibtex(ARXIV_ID, [_source(1, """
@string{j = "Journal"}
@article{same, title={Title}, year=2020}
@article{same, title={Title}, year=2020, journal=j}
""", cites=["same"])])
    assert len(result.entries) == 1
    assert result.entries[0]["journal"] == "Journal"
    assert result.stats["entry_before"] == 2
    assert result.stats["issues"][0]["code"] == "DuplicateBlockKeyBlock"


def test_empty_input_and_mixed_publications():
    result = merge_bibtex(ARXIV_ID, [])
    assert result.entries == [] and result.key_map == {}
    other = BibSource("2508.02873", 1, {}, [], [], [])
    with pytest.raises(ValueError, match="requested Publication"):
        merge_bibtex(ARXIV_ID, [other])


def test_bibitem_explicit_fields_and_quote_precedence():
    result = merge_bibtex(ARXIV_ID, [_source(1, items=[
        r"\bibitem{short} \bibinfo{author}{A. Example}. \bibinfo{journal}{A Journal}. \bibinfo{year}{2020}.",
        r"\bibitem{full} \bibinfo{author}{B. Example}. \bibinfo{title}{A {Nested} Title}. \bibinfo{year}{2021}.",
        r"\bibitem{quoted} C. Example \textit{et al.}, ``Quoted Title,'' J. Example (2022).",
        r"\bibitem{plain} Example, A., Test, B., Comma-style Title, {\it J. Example} (2023).",
    ])])
    rows = {row["citation_key"]: row for row in result.entries}
    assert rows["short"]["title"] is None and rows["short"]["journal"] == "A Journal"
    assert rows["full"]["title"] == "A {Nested} Title"
    assert rows["quoted"]["title"] == "Quoted Title"
    assert rows["plain"]["title"] == "Comma-style Title"
    assert result.stats["issues"] == [{"version": 1, "key": "short", "code": "missing_bibitem_title"}]
