"""Atom metadata and complete revision dates from versioned arXiv queries.

Source: https://info.arxiv.org/help/api/user-manual.html
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode, urlsplit
import xml.etree.ElementTree as ET

from src.common.corpus import Publication  # Compatibility re-export.
from .http_client import HttpClient, HttpStatusError
from .storage import require_id

ATOM = "http://www.w3.org/2005/Atom"
ARXIV = "http://arxiv.org/schemas/atom"


def _text(parent: ET.Element, name: str, namespace: str = ATOM) -> str | None:
    value = parent.findtext(f"{{{namespace}}}{name}")
    return " ".join(value.split()) if value else None


def _entry(body: bytes) -> ET.Element:
    entries = ET.fromstring(body).findall(f"{{{ATOM}}}entry")
    if len(entries) != 1:
        raise ValueError("Expected exactly one arXiv publication")
    return entries[0]


def parse_feed(body: bytes) -> Publication:
    """Parse one entry; latest suffix gives count, not the number of date tags."""
    entry = _entry(body)
    identifier = _text(entry, "id") or ""
    path = urlsplit(identifier).path
    if not path.startswith("/abs/"):
        raise ValueError("arXiv response is an error or has no publication ID")
    raw_id = path[len("/abs/"):]
    match = re.fullmatch(r"(.+?)v([1-9]\d*)", raw_id)
    base_id = require_id(match[1] if match else raw_id)
    legacy_versions = entry.findall(f"{{{ARXIV}}}version")
    dates = [_text(v, "date", ARXIV) for v in legacy_versions]
    if any(d is None for d in dates):
        raise ValueError("Incomplete version dates")
    count = int(match[2]) if match else max(1, len(dates))
    return Publication(base_id, _text(entry, "title"),
        [a.text.strip() for a in entry.findall(f"{{{ATOM}}}author/{{{ATOM}}}name") if a.text],
        _text(entry, "published") or (dates[0] if dates else None),
        dates[1:] if len(dates) == count else [],
        _text(entry, "journal_ref", ARXIV), count)


class ArxivDiscovery:
    """One base lookup and version-specific lookups for all revision dates."""
    def __init__(self, client: HttpClient, endpoint: str = "https://export.arxiv.org/api/query") -> None:
        self.client, self.endpoint = client, endpoint

    def _fetch(self, identifier: str) -> bytes:
        response = self.client.get(f"{self.endpoint}?{urlencode({'id_list': identifier})}")
        if response.status != 200:
            raise HttpStatusError(response.status, "arXiv metadata")
        return response.body

    def discover(self, arxiv_id: str) -> Publication:
        require_id(arxiv_id)
        body = self._fetch(arxiv_id)
        publication = parse_feed(body)
        if publication.arxiv_id != arxiv_id:
            raise ValueError("arXiv returned a different publication")
        revisions = []
        for version in range(2, publication.versions + 1):
            version_body = body if version == publication.versions else self._fetch(f"{arxiv_id}v{version}")
            parsed = parse_feed(version_body)
            if parsed.arxiv_id != arxiv_id or parsed.versions != version:
                raise ValueError("arXiv did not return the requested version")
            updated = _text(_entry(version_body), "updated")
            if not updated:
                raise ValueError("Version response missing updated date")
            revisions.append(updated)
        return Publication(publication.arxiv_id, publication.title, publication.authors,
                           publication.submission_date, revisions, publication.venue, publication.versions)


class BatchedDiscovery(ArxivDiscovery):
    """Discovery theo lô: prefetch base-ID Atom entries, up to 100 IDs per query.

    Contributed by Liễu (langtucod0n), originally in merge parent 0d19257.
    The shared parser still fills all revision dates. Missing or failed batch
    entries fall back to individual queries; a missing batch result is never
    sufficient evidence that a Publication does not exist. All arXiv requests,
    including revision lookups/source downloads, share one client and the
    process-wide rate limiter. batch_size=0 disables batching.
    """

    def __init__(self, client: HttpClient, batch_size: int = 50) -> None:
        super().__init__(client)
        if not 0 <= batch_size <= 100:
            raise ValueError("discover_batch must be between 0 and 100")
        self.batch_size = batch_size
        self.prefetched: dict[str, bytes] = {}

    def prefetch(self, identifiers) -> None:
        ids = list(dict.fromkeys(require_id(i) for i in identifiers))
        ids = [i for i in ids if i not in self.prefetched]
        if not self.batch_size:
            return
        for start in range(0, len(ids), self.batch_size):
            chunk = ids[start:start + self.batch_size]
            try:
                response = self.client.get(f"{self.endpoint}?{urlencode({'id_list': ','.join(chunk)})}")
                if response.status != 200:
                    raise HttpStatusError(response.status, "arXiv batch metadata")
                root = ET.fromstring(response.body)
                found = {}
                for entry in root.findall(f"{{{ATOM}}}entry"):
                    feed = ET.Element(f"{{{ATOM}}}feed")
                    feed.append(entry)
                    body = ET.tostring(feed, encoding="utf-8")
                    pub = parse_feed(body)
                    if pub.arxiv_id not in chunk or pub.arxiv_id in found:
                        raise ValueError("Unexpected or duplicate batch publication")
                    found[pub.arxiv_id] = body
                self.prefetched.update(found)
            except Exception as error:
                print(json.dumps({"event": "batch_discovery_fallback",
                                  "error_type": type(error).__name__, "size": len(chunk)}), flush=True)

    def _fetch(self, identifier: str) -> bytes:
        if identifier in self.prefetched:
            return self.prefetched.pop(identifier)
        return super()._fetch(identifier)
