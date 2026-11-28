"""M2.4b fixtures cover merging, schema compatibility and unresolved citations."""
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from src.common.schema import from_records, validate
from src.parse.bibtex import BIBTEX_VERSION, merge_bibtex
from src.parse.types import BibSource, validate_B_prime, validate_D


ARXIV_ID = "2508.02872"
GOLDEN = Path(__file__).parent / "fixtures/m2/two-versions-cite-rename"


def _source(version, bib="", items=(), cites=()):
    return BibSource(ARXIV_ID, version, {"refs.bib": bib} if bib else {}, [], list(items), list(cites))


def test_two_versions_cite_rename_golden_and_parquet_schema():
    inputs = [BibSource.from_dict(json.loads((GOLDEN / f"B'.v{version}.json").read_text(encoding="utf-8")))
              for version in (1, 2)]
    for source in inputs:
        assert validate_B_prime(source) == []

    # The shared golden records the hand-written [D] contract. The parser
    # adds the Publication ID on each row for Parquet, and its own version
    # and diagnostic fields.
    expected = json.loads((GOLDEN / "D.json").read_text(encoding="utf-8"))
    for row in expected["entries"]:
        row["arxiv_id"] = expected["arxiv_id"]
    expected["bibtex_version"] = BIBTEX_VERSION
    expected["stats"].update({
        "unresolved_keys": [], "field_conflicts": 0, "conflicts": [],
        "invalid_years": [], "issues": [], "versions_without_bibliography": 0,
        "groups_before_filter": 1, "groups_filtered_out": 0,
        "cross_version_resolved": 0, "cross_version_keys": [],
    })

    result = merge_bibtex(ARXIV_ID, inputs)
    assert validate_D(result, inputs) == []
    assert result.to_dict() == expected
    assert asdict(merge_bibtex(ARXIV_ID, list(reversed(inputs)))) == expected
    assert validate(from_records(result.entries, "bibtex"), "bibtex") == []


def test_year_matches_shared_contract_range():
    inputs = [_source(1, """
@misc{below, year={0999}}
@misc{first, year={1000}}
@misc{last, year={2999}}
@misc{above, year={3000}}
""", cites=["below", "first", "last", "above"])]
    assert validate_B_prime(inputs[0]) == []
    result = merge_bibtex(ARXIV_ID, inputs)
    assert validate_D(result, inputs) == []
    assert {row["citation_key"]: row["year"] for row in result.entries} == {
        "below": None, "first": 1000, "last": 2999, "above": None,
    }
    assert result.raw_years == {"below": "0999", "above": "3000"}
    assert {item["value"] for item in result.stats["invalid_years"]} == {"0999", "3000"}


def test_merged_valid_year_excludes_invalid_year_from_raw_years():
    inputs = [
        _source(1, "@misc{old, year={forthcoming}, doi={10.1234/example}}", cites=["old"]),
        _source(2, "@misc{new, year={2020}, doi={10.1234/example}}", cites=["new"]),
    ]
    for source in inputs:
        assert validate_B_prime(source) == []
    result = merge_bibtex(ARXIV_ID, inputs)
    assert validate_D(result, inputs) == []
    assert len(result.entries) == 1 and result.entries[0]["year"] == 2020
    assert result.raw_years == {}
    assert result.stats["invalid_years"] == [{"version": 1, "key": "old", "value": "forthcoming"}]


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
    assert result.key_map["1"] == {"real": "real"}
    assert result.stats["unresolved"] == 1
    assert result.stats["unresolved_keys"] == [{"version": 1, "key": "missing", "reason": "missing_entry"}]
    assert {entry["citation_key"] for entry in result.entries} == {"real", "other"}
    assert validate_D(result, [v1, v2]) == []


def test_all_missing_citations_are_logged_without_dangling_mappings():
    sources = [_source(1, cites=["ghost", "ghost"])]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert result.entries == [] and result.key_map == {"1": {}}
    assert result.stats["unresolved"] == 1
    assert result.stats["unresolved_keys"] == [{"version": 1, "key": "ghost", "reason": "missing_entry"}]


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


def test_duplicate_key_without_year_merges_and_logs_conflicts():
    sources = [_source(1, """
@article{dup, title={Attention Is All You Need}, year={2017}}
@article{dup, title={Attention is all you need}, author={Vaswani, A.}}
""", cites=["dup"])]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert len(result.entries) == 1
    assert result.entries[0]["year"] == 2017
    assert result.entries[0]["authors"] == ["Vaswani, A."]
    assert result.key_map == {"1": {"dup": "dup"}}
    assert result.stats["unresolved"] == 0
    assert result.stats["field_conflicts"] == 1


@pytest.mark.parametrize("year", [", year={2017}", ""])
def test_same_key_with_corrected_title_merges_across_versions(year):
    sources = [
        _source(1, "@article{k, title={Atention is all you need}" + year + "}", cites=["k"]),
        _source(2, "@article{k, title={Attention is all you need}" + year + "}", cites=["k"]),
    ]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert len(result.entries) == 1
    assert result.entries[0]["title"] == "Attention is all you need"
    assert result.key_map == {"1": {"k": "k"}, "2": {"k": "k"}}
    assert result == merge_bibtex(ARXIV_ID, list(reversed(sources)))


def test_same_key_with_unrelated_titles_stays_separate():
    sources = [
        _source(1, "@article{k, title={Quantum gravity}}", cites=["k"]),
        _source(2, "@article{k, title={Neural machine translation}}", cites=["k"]),
    ]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert len(result.entries) == 2
    assert result.key_map["1"]["k"] != result.key_map["2"]["k"]


def test_empty_bibtex_key_is_logged_and_excluded():
    sources = [_source(1, "@misc{, title={Invalid}}\n@misc{valid, title={Valid}}", cites=["valid"])]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert [row["citation_key"] for row in result.entries] == ["valid"]
    assert any(issue["code"] == "empty_key" for issue in result.stats["issues"])


def test_only_cited_groups_survive_after_crossref_and_version_union():
    sources = [
        _source(1, """
@proceedings{parent, title={Proceedings}, year={2020}, booktitle={Conference}}
@inproceedings{old, title={Example}, crossref={parent}, doi={10.1234/example}}
@misc{unused, title={Unused}}
""", cites=["old"]),
        _source(2, "@inproceedings{new, title={Example}, doi={10.1234/example}, author={A. Author}}"),
    ]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert [row["citation_key"] for row in result.entries] == ["new"]
    assert result.entries[0]["journal"] == "Conference"
    assert result.entries[0]["year"] == 2020
    assert result.entries[0]["authors"] == ["A. Author"]
    assert result.key_map == {"1": {"old": "new"}, "2": {}}
    assert result.stats["entry_before"] == 4
    assert result.stats["groups_before_filter"] == 3
    assert result.stats["groups_filtered_out"] == 2
    assert result.stats["entry_after"] == 1


def test_no_citations_produces_empty_table():
    sources = [_source(1, "@misc{unused, title={Unused}}")]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert result.entries == []
    assert result.stats["groups_before_filter"] == result.stats["groups_filtered_out"] == 1


def test_bib_and_bibitem_share_unicode_text_cleanup():
    sources = [
        _source(1, r'''@inproceedings{bib,
title={{BERT}: Pre-training of {\'E}tudes}, author={M{\"u}ller, J.},
booktitle={Conf{\'e}rence}, year={2020}}''', cites=["bib"]),
        _source(2, items=[r'''\bibitem{item} \bibinfo{author}{M{\"u}ller, J.}
\bibinfo{title}{{BERT}: Pre-training of {\'E}tudes}\bibinfo{year}{2020}'''], cites=["item"]),
    ]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert len(result.entries) == 1
    assert result.entries[0]["title"] == "BERT: Pre-training of Études"
    assert result.entries[0]["authors"] == ["Müller, J."]
    assert result.entries[0]["journal"] == "Conférence"


@pytest.mark.parametrize(("title", "expected"), [
    (r"\href{https://example.org}{A {Linked} Title}", "A Linked Title"),
    (r"\href{https://example.org}", "https://example.org"),
    (r"\href", None),
])
def test_linked_bibtex_titles_and_missing_arguments(title, expected):
    sources = [_source(1, "@misc{linked, title={" + title + "}}", cites=["linked"])]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert result.entries[0]["title"] == expected


def test_unique_key_can_resolve_from_another_version_without_a_local_entry():
    sources = [_source(1, "@misc{old, title={Shared}, year={2020}}"), _source(2, cites=["old"])]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert [row["citation_key"] for row in result.entries] == ["old"]
    assert result.key_map == {"1": {}, "2": {"old": "old"}}
    assert result.stats["unresolved"] == 0
    assert result.stats["cross_version_keys"] == [
        {"version": 2, "key": "old", "citation_key": "old", "source_versions": [1]},
    ]


def test_cross_version_fallback_keeps_reused_ambiguous_keys_unresolved():
    sources = [
        _source(1, "@misc{k, title={First}, doi={10.1234/first}}", cites=["k"]),
        _source(2, "@misc{k, title={Second}, doi={10.1234/second}}"),
        _source(3, cites=["k"]),
    ]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert result.key_map["3"] == {}
    assert result.stats["unresolved_keys"] == [{"version": 3, "key": "k", "reason": "missing_entry"}]
    assert any(item["code"] == "ambiguous_cross_version_key" for item in result.stats["issues"])


def test_duplicate_fields_keep_last_value_and_log_conflict():
    sources = [_source(1, """
@article{dup, title={Title}, doi={invalid}, author={A. Doe and B. Smith}, doi={10.1234/valid}}
""", cites=["dup"])]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert result.entries[0]["doi"] == "10.1234/valid"
    assert result.entries[0]["authors"] == ["A. Doe", "B. Smith"]
    assert any(item["code"] == "duplicate_field_conflict" for item in result.stats["issues"])


def test_multiline_entry_header_is_recovered_without_rewriting_valid_fields():
    sources = [_source(1, """
@misc
{multiline, title={Title}, year={2020}}
@misc{literal, title={Example @misc
{nested}}, year={2021}}
""", cites=["multiline", "literal"])]
    result = merge_bibtex(ARXIV_ID, sources)
    assert validate_D(result, sources) == []
    assert {row["citation_key"] for row in result.entries} == {"multiline", "literal"}
    assert result.stats["entry_before"] == 2
    assert [item["code"] for item in result.stats["issues"]] == ["multiline_entry_header"]


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
    ], cites=["short", "full", "quoted", "plain"])])
    rows = {row["citation_key"]: row for row in result.entries}
    assert rows["short"]["title"] is None and rows["short"]["journal"] == "A Journal"
    assert rows["full"]["title"] == "A Nested Title"
    assert rows["quoted"]["title"] == "Quoted Title"
    assert rows["plain"]["title"] == "Comma-style Title"
    assert result.stats["issues"] == [{"version": 1, "key": "short", "code": "missing_bibitem_title"}]


def test_bibitem_leading_newblock_keeps_author_title_and_distinct_parts():
    # 2508.04688 opens every item with \newblock before the authors. The
    # empty text before it is not the author block, and two parts of one
    # series with the same author and year must stay separate entries.
    result = merge_bibtex(ARXIV_ID, [_source(1, items=[
        "\\bibitem{part1}\n \\newblock  G. Allaire,\n \\newblock Tiny holes I. Abstract framework,"
        "\n \\newblock \\emph{Arch. Ration. Mech. Anal.}, \\textbf{113}, (1991), 209 -- 259.",
        "\\bibitem{part2}\n \\newblock  G. Allaire,\n \\newblock Tiny holes II. Non-critical sizes,"
        "\n \\newblock \\emph{Arch. Ration. Mech. Anal.}, \\textbf{113}, (1991), 261 -- 298.",
    ], cites=["part1", "part2"])])
    rows = {row["citation_key"]: row for row in result.entries}
    assert set(rows) == {"part1", "part2"}
    assert rows["part1"]["title"] == "Tiny holes I. Abstract framework"
    assert rows["part2"]["title"] == "Tiny holes II. Non-critical sizes"
    assert rows["part1"]["authors"] == ["G. Allaire"]


def test_bibitem_leading_newblock_with_authors_and_title_in_one_block():
    # 2409.20363: "\newblock Authors. Title. \newblock Journal" has only two
    # blocks, so the first one holds both the authors and the title.
    result = merge_bibtex(ARXIV_ID, [_source(1, items=[
        "\\bibitem{st}\n\\newblock Stefano Serra-Capizzano and Eugene Tyrtyshnikov. Any circulant-like"
        " preconditioner is not superlinear.\n\\newblock {\\em SIAM J. Matrix Anal. Appl.}, 21: 431--439, 1999.",
    ], cites=["st"])])
    row = result.entries[0]
    assert row["title"] == "Any circulant-like preconditioner is not superlinear"
    assert row["authors"] == ["Stefano Serra-Capizzano", "Eugene Tyrtyshnikov"]
