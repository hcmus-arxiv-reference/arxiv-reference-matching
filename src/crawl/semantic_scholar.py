"""Full reference pagination and explicit mapping to the agreed crawling schema.

Source: https://api.semanticscholar.org/graph/v1/swagger.json
"""
from __future__ import annotations
import json
import re
from urllib.parse import quote, urlencode

from src.common.schema import from_records
from .http_client import HttpClient, HttpStatusError
from .storage import require_id


class SemanticScholarClient:
    def __init__(self, client: HttpClient, endpoint: str = "https://api.semanticscholar.org/graph/v1") -> None:
        self.client, self.endpoint = client, endpoint.rstrip("/")

    def references(self, arxiv_id: str, *, page_size: int = 100) -> list[dict]:
        """Retain all raw citedPaper records, including those without an arXiv ID."""
        require_id(arxiv_id)
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        offset, rows = 0, []
        while True:
            query = urlencode({"fields": "paperId,externalIds,title,authors,publicationDate",
                               "limit": page_size, "offset": offset})
            response = self.client.get(f"{self.endpoint}/paper/ARXIV:{quote(arxiv_id, safe='')}/references?{query}")
            if response.status != 200:
                raise HttpStatusError(response.status, "Semantic Scholar")
            payload = json.loads(response.body)
            data = payload.get("data")
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("Invalid Semantic Scholar page")
            rows.extend(data)
            next_offset = payload.get("next")
            if next_offset is None:
                return rows
            if type(next_offset) is not int or next_offset <= offset:
                raise ValueError("Non-advancing Semantic Scholar pagination")
            offset = next_offset


def reference_rows(arxiv_id: str, raw_rows: list[dict]) -> list[dict]:
    """Deduplicate arXiv-keyed candidates; never treat publicationDate as submission."""
    require_id(arxiv_id)
    rows = {}
    for raw in raw_rows:
        paper = raw.get("citedPaper") or {}
        external = paper.get("externalIds") or {}
        identifier = external.get("ArXiv")
        if not identifier:
            continue
        ref_id = require_id(re.sub(r"v\d+$", "", identifier))
        row = {"arxiv_id": arxiv_id, "ref_arxiv_id": ref_id,
               "ref_title": paper.get("title"),
               "ref_authors": [a["name"] for a in (paper.get("authors") or []) if a.get("name")],
               "ref_submission_date": None, "ref_s2_id": paper.get("paperId")}
        if ref_id in rows:
            # Preserve first supplied nonempty values, fill missing values only.
            row = {k: rows[ref_id][k] or v for k, v in row.items()}
        rows[ref_id] = row
    result = [rows[k] for k in sorted(rows)]
    from_records(result, "references")
    return result
