"""Optional Semantic Scholar reference retrieval with pagination."""

from __future__ import annotations

import json
from .http_client import HttpClient


class SemanticScholarClient:
    def __init__(self, client: HttpClient, endpoint: str = "https://api.semanticscholar.org/graph/v1") -> None:
        self.client = client
        self.endpoint = endpoint.rstrip("/")

    def references(self, arxiv_id: str, *, limit: int = 1000) -> list[dict]:
        offset, rows = 0, []
        while offset < limit:
            page_size = min(100, limit - offset)
            url = f"{self.endpoint}/paper/ARXIV:{arxiv_id}/references?fields=paperId,externalIds,title,authors,publicationDate&limit={page_size}&offset={offset}"
            response = self.client.get(url)
            if response.status != 200:
                raise RuntimeError(f"Semantic Scholar HTTP {response.status} for {arxiv_id}")
            payload = json.loads(response.body)
            data = payload.get("data", [])
            rows.extend(data)
            if len(data) < page_size:
                break
            offset += len(data)
        return rows
