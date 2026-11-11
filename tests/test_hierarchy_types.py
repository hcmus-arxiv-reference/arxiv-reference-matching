"""Verify that M2 dataclass records fit the existing table schemas unchanged."""

from dataclasses import asdict, fields

import pytest

from src.common.schema import SCHEMAS, from_records, validate
from src.parse.Hierarchy.types import BibtexEntry, Element, Hierarchy


@pytest.mark.parametrize("table_name,record", [
    ("elements", Element("2508-02872#document-root", "2508.02872", "document", "")),
    ("hierarchy", Hierarchy("2508.02872", 1, "2508-02872#section-intro", "2508-02872#document-root")),
    ("bibtex", BibtexEntry("2508.02872", "vaswani2017", "article")),
])
def test_dataclass_fields_and_records_match_table_schema(table_name, record):
    assert [field.name for field in fields(record)] == SCHEMAS[table_name].names
    row = asdict(record)
    table = from_records([row], table_name)
    assert validate(table, table_name) == []
    assert table.to_pylist() == [row]


@pytest.mark.parametrize("authors,year", [
    (["Author A", "Author B"], 2017),
    ([], None),
    (None, None),
])
def test_bibtex_preserves_author_lists_and_unknown_values(authors, year):
    entry = BibtexEntry(
        arxiv_id="2508.02872", citation_key="example", entry_type="article",
        title="Example title", authors=authors, year=year,
        doi="10.1234/example", journal="Example journal", url="https://example.org/paper",
    )
    table = from_records([asdict(entry)], "bibtex")
    assert table.to_pylist() == [asdict(entry)]
    assert validate(table, "bibtex") == []
