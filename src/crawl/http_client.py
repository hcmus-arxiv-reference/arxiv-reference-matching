"""Bounded HTTP requests, serialized arXiv traffic, and bounded retry/backoff."""
from __future__ import annotations

from dataclasses import dataclass
import email.utils
from http.client import IncompleteRead
import math
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class HttpStatusError(RuntimeError):
    """Keep the status for manifests without logging headers or response bodies."""
    def __init__(self, status: int, service: str):
        self.status = status
        super().__init__(f"{service}: HTTP {status}")


class _Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(req.full_url).hostname == "export.arxiv.org":
            raise RuntimeError("Refusing automatic arXiv redirect; verify endpoint before retrying")
        elif urlsplit(req.full_url).netloc != urlsplit(newurl).netloc:
            raise RuntimeError("Refusing cross-host redirect with client headers")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpClient:
    """arXiv uses a shared process lock and at least three seconds between calls.

    Injected transports/clocks are isolated for deterministic offline tests.
    Run one crawler process at a time across all data directories/machines.
    """
    _arxiv_lock = threading.Lock()
    _arxiv_last = float("-inf")

    def __init__(self, user_agent: str, *, min_interval: float = 3.0,
                 timeout: float = 60.0, max_retries: int = 4,
                 transport: Callable[[Request, float], HttpResponse] | None = None,
                 sleeper: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 headers: dict[str, str] | None = None,
                 max_bytes: int = 128 * 1024 * 1024) -> None:
        if not math.isfinite(min_interval) or min_interval < 0:
            raise ValueError("min_interval must be finite and nonnegative")
        self.user_agent, self.min_interval = user_agent, min_interval
        self.timeout, self.max_retries = timeout, max(0, max_retries)
        self.max_bytes = max_bytes
        self.headers = dict(headers or {})
        self._real = transport is None
        self._transport = transport or self._urlopen
        self._sleeper, self._clock = sleeper, clock
        self._last_request = float("-inf")
        self._lock = threading.Lock()

    def _urlopen(self, request: Request, timeout: float) -> HttpResponse:
        with build_opener(_Redirects()).open(request, timeout=timeout) as response:
            expected = response.headers.get("Content-Length")
            expected = int(expected) if expected is not None else None
            if expected is not None and expected > self.max_bytes:
                raise ValueError("HTTP response exceeds configured size limit")
            chunks, total = [], 0
            while chunk := response.read(min(64 * 1024, self.max_bytes + 1 - total)):
                total += len(chunk)
                if total > self.max_bytes:
                    raise ValueError("HTTP response exceeds configured size limit")
                chunks.append(chunk)
            if expected is not None and total != expected:
                raise IncompleteRead(b"", max(0, expected - total))
            return HttpResponse(response.status, dict(response.headers.items()), b"".join(chunks))

    @staticmethod
    def _retry_after(headers: dict[str, str], fallback: float) -> float:
        value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
        if not value:
            return fallback
        try:
            delay = float(value)
            return max(0.0, delay) if math.isfinite(delay) else fallback
        except ValueError:
            try:
                return max(0.0, email.utils.parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                return fallback

    def get(self, url: str) -> HttpResponse:
        host = urlsplit(url).hostname or ""
        arxiv = host == "export.arxiv.org"
        if host == "arxiv.org" or (host.endswith(".arxiv.org") and not arxiv):
            raise ValueError("Crawler requests must use export.arxiv.org")
        interval = max(3.0, self.min_interval) if arxiv else self.min_interval
        shared = arxiv and self._real
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "*/*", **self.headers})
        with (self._arxiv_lock if shared else self._lock):
            for attempt in range(self.max_retries + 1):
                last = HttpClient._arxiv_last if shared else self._last_request
                wait = interval - (self._clock() - last)
                if wait > 0:
                    self._sleeper(wait)
                self._last_request = self._clock()
                if shared:
                    HttpClient._arxiv_last = self._last_request
                try:
                    response = self._transport(request, self.timeout)
                except HTTPError as error:
                    # Error bodies are not corpus data and can contain secrets.
                    response = HttpResponse(error.code, dict(error.headers.items()), b"")
                    error.close()
                except (URLError, TimeoutError, ConnectionError, IncompleteRead):
                    if attempt >= self.max_retries:
                        raise
                    self._sleeper(min(60.0, 2.0**attempt))
                    continue
                if response.status not in {429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    return response
                delay = self._retry_after(response.headers, min(60.0, 2.0**attempt))
                if delay > 60:
                    # Persist the failure instead of ignoring a long server cooldown.
                    raise HttpStatusError(response.status, "retry later (Retry-After > 60s)")
                self._sleeper(delay)
        raise AssertionError("unreachable")
