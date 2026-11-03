"""Batched Atom discovery reused from integration commit 63df237."""
import json
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

from .discovery import ATOM, ArxivDiscovery, parse_feed
from .http_client import HttpStatusError
from .storage import require_id


class BatchedDiscovery(ArxivDiscovery):
    """Prefetch base-ID Atom entries; the shared parser fills all revision dates.

    Missing or failed batch entries fall back to individual queries. A missing
    batch result is never sufficient evidence that a Publication does not exist.
    All arXiv requests, including revision lookups/source downloads, share one
    client and the process-wide rate limiter.
    """

    def __init__(self, client, batch_size=50):
        super().__init__(client)
        if not 0 <= batch_size <= 100:
            raise ValueError("discover_batch must be between 0 and 100")
        self.batch_size = batch_size
        self.prefetched = {}

    def prefetch(self, identifiers):
        ids = list(dict.fromkeys(require_id(i) for i in identifiers))
        ids = [i for i in ids if i not in self.prefetched]
        if not self.batch_size:
            return
        for start in range(0, len(ids), self.batch_size):
            chunk = ids[start:start + self.batch_size]
            try:
                response = self.client.get(f"{self.endpoint}?{urlencode({'id_list': ','.join(chunk), 'max_results': len(chunk)})}")
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

    def _fetch(self, identifier):
        if identifier in self.prefetched:
            return self.prefetched.pop(identifier)
        return super()._fetch(identifier)


