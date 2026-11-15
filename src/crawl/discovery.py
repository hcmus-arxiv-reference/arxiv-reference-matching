"""Atom metadata and complete revision dates from versioned arXiv queries.

Source: https://info.arxiv.org/help/api/user-manual.html
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.error import URLError
import xml.etree.ElementTree as ET

from src.common.corpus import Publication  # Compatibility re-export.
from .http_client import RETRY_STATUSES, HttpClient, HttpStatusError
from .storage import require_id

ATOM = "http://www.w3.org/2005/Atom"
# Pauses before retrying a whole Discovery batch that arXiv throttled (429/5xx or
# timeouts after HttpClient's own retries). Colab 15/11: the API answered 43 of 55
# queries with 429 while /src/ downloads ran normally; falling back to one query
# per ID multiplied the throttled requests by the batch size.
BATCH_THROTTLE_PAUSES = (60.0, 120.0, 240.0, 300.0, 300.0)
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
    The shared parser still fills all revision dates. Missing entries and
    malformed batches fall back to individual queries; a throttled batch
    (429/5xx, timeouts) is retried whole instead (``_prefetch_chunk``). A
    missing batch result is never
    sufficient evidence that a Publication does not exist. All arXiv requests,
    including revision lookups/source downloads, share one client and the
    process-wide rate limiter. batch_size=0 disables batching. Each batch sets
    ``max_results`` to its size: without it the API caps the reply at 10 entries
    and the remaining IDs silently fall back to one request each.
    """

    def __init__(self, client: HttpClient, batch_size: int = 50) -> None:
        super().__init__(client)
        if not 0 <= batch_size <= 100:
            raise ValueError("discover_batch must be between 0 and 100")
        self.batch_size = batch_size
        self.prefetched: dict[str, bytes] = {}
        self.throttled: set[str] = set()

    def prefetch(self, identifiers) -> None:
        ids = list(dict.fromkeys(require_id(i) for i in identifiers))
        self.throttled.difference_update(ids)    # a new pass asks again
        ids = [i for i in ids if i not in self.prefetched]
        if not self.batch_size:
            return
        for start in range(0, len(ids), self.batch_size):
            self._prefetch_chunk(ids[start:start + self.batch_size])

    def _prefetch_chunk(self, chunk: list[str]) -> None:
        """One batch query; a throttled batch is retried whole, never split per ID.

        After ``BATCH_THROTTLE_PAUSES`` run out, one ID is queried alone. If it
        answers, only the batch query fails and the other IDs fall back to one
        query each. Otherwise the IDs are marked throttled: their Discovery fails
        at once with HTTP 429 (no request), the Runner records the error and the
        next pass batches them again.
        """
        pauses = iter(BATCH_THROTTLE_PAUSES)
        while True:
            try:
                self.prefetched.update(self._fetch_batch(chunk))
                return
            except (HttpStatusError, URLError, TimeoutError, ConnectionError) as error:
                status = getattr(error, "status", None)
                if isinstance(error, HttpStatusError) and status not in RETRY_STATUSES:
                    self._fallback(error, chunk)
                    return
                pause = next(pauses, None)
                if pause is None:
                    if self._single_answers(chunk[0]):
                        self._fallback(error, chunk)
                        return
                    self.throttled.update(chunk)
                    print(json.dumps({"event": "batch_discovery_throttled", "status": status,
                                      "error_type": type(error).__name__, "size": len(chunk)}), flush=True)
                    return
                self.client._backoff(pause, status=status,
                                     error=None if status else type(error).__name__)
            except Exception as error:
                self._fallback(error, chunk)
                return

    def _fetch_batch(self, chunk: list[str]) -> dict[str, bytes]:
        # arXiv returns 10 entries unless max_results is set, even for id_list.
        query = urlencode({"id_list": ",".join(chunk), "max_results": len(chunk)})
        response = self.client.get(f"{self.endpoint}?{query}")
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
        return found

    def _single_answers(self, identifier: str) -> bool:
        """Query one ID of a throttled batch; keep its answer when it comes."""
        try:
            self.prefetched[identifier] = ArxivDiscovery._fetch(self, identifier)
            return True
        except (HttpStatusError, URLError, TimeoutError, ConnectionError):
            return False

    @staticmethod
    def _fallback(error: Exception, chunk: list[str]) -> None:
        """Malformed or rejected batch: its IDs are discovered one by one."""
        print(json.dumps({"event": "batch_discovery_fallback",
                          "error_type": type(error).__name__, "size": len(chunk)}), flush=True)

    def _fetch(self, identifier: str) -> bytes:
        if identifier in self.prefetched:
            return self.prefetched.pop(identifier)
        if identifier in self.throttled:
            self.throttled.discard(identifier)
            raise HttpStatusError(429, "arXiv metadata (batch throttled, not requested)")
        return super()._fetch(identifier)
