"""One definition for every count of the S2 citation list (CONTEXT.md, data contract 4.3)."""
import pytest

from src.common.references import CitationList

PID = "2508.02872"
RAW = [
    {"citedPaper": {"paperId": "a", "title": "A", "externalIds": {"ArXiv": "1706.03762v1"}}},
    {"citedPaper": {"paperId": None, "title": None, "externalIds": {"ArXiv": "1706.03762v5"}}},
    {"citedPaper": {"paperId": "b", "title": "B", "externalIds": {"ArXiv": "hep-th/9901001"}}},
    {"citedPaper": {"paperId": "c", "title": "C", "externalIds": {}}},
    {"citedPaper": None},
]


def test_counts_before_and_after_deduplication():
    citations = CitationList.from_raw(PID, RAW)
    assert citations.total == 5
    assert citations.with_arxiv_id == 3  # raw rows, before deduplication
    assert [r["ref_arxiv_id"] for r in citations.references] == ["1706.03762", "hep-th/9901001"]
    assert citations.legacy_ids == 1
    # Deduplication keeps the first nonempty values.
    assert citations.references[0]["ref_s2_id"] == "a" and citations.references[0]["ref_title"] == "A"
    assert citations.raw == tuple(RAW)  # the cache keeps every raw row (ADR 0002)


def test_empty_list_is_valid():
    citations = CitationList.from_raw(PID, [])
    assert (citations.total, citations.with_arxiv_id, citations.references) == (0, 0, ())


@pytest.mark.parametrize("raw", [None, {"data": []}, ["not an object"],
                                 [{"citedPaper": {"externalIds": {"ArXiv": "not an id"}}}]])
def test_invalid_rows_raise_value_error(raw):
    with pytest.raises(ValueError):
        CitationList.from_raw(PID, raw)


def test_reference_rows_reexports_point_to_one_function():
    from src.common import corpus, references
    from src.crawl import semantic_scholar
    assert corpus.reference_rows is references.reference_rows
    assert semantic_scholar.reference_rows is references.reference_rows
