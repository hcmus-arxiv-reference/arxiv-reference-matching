"""Các bản ghi M2 theo parsing.md và schema trong src/common/schema.py."""

from dataclasses import dataclass


@dataclass
class Element:
    """Một dòng elements, dùng chung giữa các Version sau khử trùng lặp."""

    element_id: str
    arxiv_id: str
    kind: str
    content: str


@dataclass
class Hierarchy:
    """Một cạnh nút-cha trong một Version; root không có dòng cạnh lên cha."""

    arxiv_id: str
    version: int
    element_id: str
    parent_id: str


@dataclass
class BibtexEntry:

    arxiv_id: str
    citation_key: str
    entry_type: str
    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    doi: str | None = None
    journal: str | None = None
    url: str | None = None
