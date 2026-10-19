"""Discover arXiv metadata and version history from the export API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
import re

from .http_client import HttpClient

ATOM = "http://www.w3.org/2005/Atom"
ARXIV = "http://arxiv.org/schemas/atom"


@dataclass(frozen=True)
class Publication:
    arxiv_id: str
    title: str | None
    authors: list[str]
    submission_date: str | None
    revised_dates: list[str]
    venue: str | None
    versions: int


def _text(parent: ET.Element, name: str) -> str | None:
    value = parent.findtext(f"{{{ATOM}}}{name}")
    return " ".join(value.split()) if value else None


def _arxiv_text(parent: ET.Element, name: str) -> str | None:
    value = parent.findtext(f"{{{ARXIV}}}{name}")
    return " ".join(value.split()) if value else None


def parse_feed(body: bytes) -> Publication:
    root = ET.fromstring(body)
    entry = root.find(f"{{{ATOM}}}entry")
    if entry is None:
        raise ValueError("arXiv API không trả về publication")
    versions = entry.findall(f"{{{ARXIV}}}version")
    dates = [_arxiv_text(version, "date") for version in versions]
    dates = [d for d in dates if d]
    if not dates:
        published = _text(entry, "published")
        dates = [published] if published else []
    raw_id = _text(entry, "id").rsplit("/", 1)[-1] if _text(entry, "id") else ""
    base_id = re.sub(r"v\d+$", "", raw_id)
    return Publication(
        arxiv_id=base_id,
        title=_text(entry, "title"),
        authors=[a.text.strip() for a in entry.findall(f"{{{ATOM}}}author/{{{ATOM}}}name") if a.text],
        submission_date=dates[0] if dates else None,
        revised_dates=dates[1:],
        venue=_text(entry, "journal_ref"),
        versions=max(1, len(versions)),
    )


class ArxivDiscovery:
    def __init__(self, client: HttpClient, endpoint: str = "https://export.arxiv.org/api/query") -> None:
        self.client = client
        self.endpoint = endpoint

    def discover(self, arxiv_id: str) -> Publication:
        response = self.client.get(f"{self.endpoint}?id_list={arxiv_id}")
        if response.status != 200:
            raise RuntimeError(f"arXiv metadata HTTP {response.status} for {arxiv_id}")
        return parse_feed(response.body)
