"""S2 citation lists: one batch request for many Publications, or full pagination for one.

Source: https://api.semanticscholar.org/graph/v1/swagger.json
(``GET /paper/{id}/references`` and ``POST /paper/batch``).
"""
from __future__ import annotations
import json
from urllib.parse import quote, urlencode

from src.common.references import reference_rows  # Compatibility re-export.
from .http_client import HttpClient, HttpStatusError
from .storage import require_id


REFERENCE_FIELDS = ("paperId", "externalIds", "title", "authors", "publicationDate")
# S2 documents a 500-ID, 10 MB limit per batch; 100 Publications measured 2.8 MB (2026-11-13).
BATCH_SIZE = 100
# A batch list this long may have been cut by S2; such a Publication is paginated instead.
BATCH_ROW_LIMIT = 1000


class SemanticScholarClient:
    """References of a Publication, one at a time (``references``) or theo lô (``references_batch``)."""

    def __init__(self, client: HttpClient, endpoint: str = "https://api.semanticscholar.org/graph/v1",
                 batch_size: int = BATCH_SIZE) -> None:
        if not 0 <= batch_size <= 500:
            raise ValueError("batch_size must be between 0 and 500")
        self.client, self.endpoint, self.batch_size = client, endpoint.rstrip("/"), batch_size

    def references_batch(self, arxiv_ids: list[str]) -> dict[str, list[dict] | None]:
        """S2 citation lists of up to ``batch_size`` Publications in one request.

        Rows have the shape ``references`` returns (``{"citedPaper": {...}}``), so
        the cache does not depend on which call filled it. A Publication that S2
        does not know maps to None. A list of ``BATCH_ROW_LIMIT`` rows or more may
        be truncated; the caller must fetch that Publication with ``references``.
        """
        ids = [require_id(i) for i in arxiv_ids]
        if not ids or len(ids) > self.batch_size or len(set(ids)) != len(ids):
            raise ValueError("Batch must hold 1..batch_size distinct IDs")
        query = urlencode({"fields": ",".join(f"references.{name}" for name in REFERENCE_FIELDS)})
        response = self.client.post(f"{self.endpoint}/paper/batch?{query}",
                                    json.dumps({"ids": [f"ARXIV:{i}" for i in ids]}).encode())
        if response.status != 200:
            raise HttpStatusError(response.status, "Semantic Scholar")
        payload = json.loads(response.body)
        if not isinstance(payload, list) or len(payload) != len(ids):
            raise ValueError("Invalid Semantic Scholar batch")
        result: dict[str, list[dict] | None] = {}
        for identifier, paper in zip(ids, payload):
            if paper is None:
                result[identifier] = None
                continue
            rows = paper.get("references") if isinstance(paper, dict) else None
            if not isinstance(rows, list) or any(row is not None and not isinstance(row, dict) for row in rows):
                raise ValueError("Invalid Semantic Scholar batch entry")
            result[identifier] = [{"citedPaper": row} for row in rows]
        return result

    def references(self, arxiv_id: str, *, page_size: int = 100) -> list[dict]:
        """Retain all raw citedPaper records, including those without an arXiv ID."""
        require_id(arxiv_id)
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        offset, rows = 0, []
        while True:
            query = urlencode({"fields": ",".join(REFERENCE_FIELDS),
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
