"""Bounded HTTP requests, serialized arXiv traffic, and bounded retry/backoff.

Resumable downloads, the per-file time budget and the 429/5xx wait table are
ported from Lieu's standalone crawler (commits 6d435fd, 1b45e47; tag
lieu-standalone-final) per decision Q12 in docs/handoff/2026-11-01-merge-lieu.md.
"""
from __future__ import annotations

from dataclasses import dataclass
import email.utils
from http.client import IncompleteRead
import math
import random
import re
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


RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
HTTP_WAITS = (15.0, 30.0, 60.0, 120.0, 240.0)  # seconds after the 1st..5th consecutive 429/5xx, ±20%
RETRY_AFTER_MAX = 900.0      # a longer server cooldown is persisted as a failure instead
MIN_SPEED = 10_000           # bytes/s; a resumable download slower than this is hopeless
MIN_BUDGET = 600.0           # seconds allowed for any resumable file, however small
UNKNOWN_SIZE_BUDGET = 3600.0  # seconds allowed when the server does not report a size
MAX_ATTEMPTS = 60            # hard cap per resumable file, even when every attempt progresses


def download_budget(total: int | None) -> float:
    """Total seconds for one resumable file: large files get time by size at MIN_SPEED."""
    return UNKNOWN_SIZE_BUDGET if total is None else max(MIN_BUDGET, total / MIN_SPEED)


def _header(headers: dict[str, str], name: str) -> str | None:
    return next((v for k, v in headers.items() if k.lower() == name), None)


class PartialBody(IncompleteRead):
    """A body cut short, keeping status and headers so the caller can resume it."""
    def __init__(self, status: int, headers: dict[str, str], partial: bytes,
                 expected: int | None = None) -> None:
        super().__init__(partial, expected)
        self.status, self.headers = status, headers


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
                 max_bytes: int = 128 * 1024 * 1024,
                 jitter: Callable[[float, float], float] = random.uniform) -> None:
        if not math.isfinite(min_interval) or min_interval < 0:
            raise ValueError("min_interval must be finite and nonnegative")
        self.user_agent, self.min_interval = user_agent, min_interval
        self.timeout, self.max_retries = timeout, max(0, max_retries)
        self.max_bytes = max_bytes
        self.headers = dict(headers or {})
        self._real = transport is None
        self._transport = transport or self._urlopen
        self._sleeper, self._clock, self._jitter = sleeper, clock, jitter
        self._deadline: float | None = None  # set only while a resumable download reads
        self._last_request = float("-inf")
        self._lock = threading.Lock()

    def _urlopen(self, request: Request, timeout: float) -> HttpResponse:
        with build_opener(_Redirects()).open(request, timeout=timeout) as response:
            expected = response.headers.get("Content-Length")
            expected = int(expected) if expected is not None else None
            if expected is not None and expected > self.max_bytes:
                raise ValueError("HTTP response exceeds configured size limit")
            headers = dict(response.headers.items())
            chunks, total = [], 0
            try:
                while chunk := response.read(min(64 * 1024, self.max_bytes + 1 - total)):
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise ValueError("HTTP response exceeds configured size limit")
                    chunks.append(chunk)
                    if self._deadline is not None and self._clock() > self._deadline:
                        raise TimeoutError("download time budget exceeded while reading")
            except (TimeoutError, ConnectionError, IncompleteRead) as error:
                # Keep what arrived so a resumable download can ask for the rest.
                raise PartialBody(response.status, headers, b"".join(chunks)) from error
            if expected is not None and total != expected:
                raise PartialBody(response.status, headers, b"".join(chunks), max(0, expected - total))
            return HttpResponse(response.status, headers, b"".join(chunks))

    @staticmethod
    def _retry_after(headers: dict[str, str], fallback: float | None) -> float | None:
        value = _header(headers, "retry-after")
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

    def _status_delay(self, response: HttpResponse, failures: int) -> float:
        """Wait before retrying a 429/5xx: exact Retry-After up to 900 s, else the table."""
        delay = self._retry_after(response.headers, None)
        if delay is None:
            return HTTP_WAITS[min(failures, len(HTTP_WAITS)) - 1] * self._jitter(0.8, 1.2)
        if delay > RETRY_AFTER_MAX:
            # Persist the failure instead of holding the arXiv lock for a long cooldown.
            raise HttpStatusError(response.status, f"retry later (Retry-After > {RETRY_AFTER_MAX:.0f}s)")
        return delay

    def _send(self, request: Request, interval: float, shared: bool) -> HttpResponse:
        """One paced request; HTTP error statuses come back as responses."""
        last = HttpClient._arxiv_last if shared else self._last_request
        wait = interval - (self._clock() - last)
        if wait > 0:
            self._sleeper(wait)
        self._last_request = self._clock()
        if shared:
            HttpClient._arxiv_last = self._last_request
        try:
            return self._transport(request, self.timeout)
        except HTTPError as error:
            # Error bodies are not corpus data and can contain secrets.
            response = HttpResponse(error.code, dict(error.headers.items()), b"")
            error.close()
            return response

    def get(self, url: str, *, resume: bool = False,
            on_event: Callable[[dict], None] | None = None) -> HttpResponse:
        """GET with bounded retries.

        With resume=True a truncated body is kept and continued with an HTTP
        Range request (see _get_resumable); on_event then receives small
        progress dicts without URLs, headers or payloads.
        """
        host = urlsplit(url).hostname or ""
        arxiv = host == "export.arxiv.org"
        if host == "arxiv.org" or (host.endswith(".arxiv.org") and not arxiv):
            raise ValueError("Crawler requests must use export.arxiv.org")
        interval = max(3.0, self.min_interval) if arxiv else self.min_interval
        shared = arxiv and self._real
        headers = {"User-Agent": self.user_agent, "Accept": "*/*", **self.headers}
        with (self._arxiv_lock if shared else self._lock):
            if resume:
                return self._get_resumable(url, headers, interval, shared, on_event or (lambda _: None))
            request = Request(url, headers=headers)
            for attempt in range(self.max_retries + 1):
                try:
                    response = self._send(request, interval, shared)
                except (URLError, TimeoutError, ConnectionError, IncompleteRead):
                    if attempt >= self.max_retries:
                        raise
                    self._sleeper(min(60.0, 2.0**attempt))
                    continue
                if response.status not in RETRY_STATUSES or attempt >= self.max_retries:
                    return response
                self._sleeper(self._status_delay(response, attempt + 1))
        raise AssertionError("unreachable")

    def _get_resumable(self, url: str, base_headers: dict[str, str], interval: float,
                       shared: bool, emit: Callable[[dict], None]) -> HttpResponse:
        """Download one file, continuing truncated bodies with Range requests.

        - Received bytes are kept; the next attempt asks for ``bytes=<have>-``.
          If-Range is sent only with a strong ETag: a weak ``W/`` ETag makes the
          server ignore Range (RFC 9110 13.1.5), so it is never sent.
        - A 200 answer restarts from byte 0; a 206 must start exactly at the
          kept length and agree on the total size, otherwise the kept bytes
          are dropped.
        - An attempt that gets further than every earlier one does not count
          as a failure, so a large file cut many times can still finish.
        - The whole file is bounded by download_budget(size) and MAX_ATTEMPTS.
        """
        buf = bytearray()
        total: int | None = None
        can_range, validator, headers = False, None, {}
        failures = best = 0
        started = self._clock()
        for attempt in range(MAX_ATTEMPTS):
            elapsed = self._clock() - started
            if elapsed > download_budget(total):
                emit({"event": "gave_up", "reason": "time_budget", "received": len(buf),
                      "total": total, "seconds": round(elapsed, 1)})
                raise TimeoutError(f"download time budget exceeded after {elapsed:.0f}s")
            resuming = can_range and bool(buf)
            request_headers = dict(base_headers)
            if resuming:
                request_headers["Range"] = f"bytes={len(buf)}-"
                if validator:
                    request_headers["If-Range"] = validator
            self._deadline = started + download_budget(total)
            partial = False
            try:
                response = self._send(Request(url, headers=request_headers), interval, shared)
                status, headers, body = response.status, response.headers, response.body
            except PartialBody as error:
                status, headers, body, partial = error.status, error.headers, error.partial, True
            except (URLError, TimeoutError, ConnectionError, IncompleteRead) as error:
                failures += 1
                if failures > self.max_retries:
                    raise
                delay = min(60.0, 2.0 ** (failures - 1))
                emit({"event": "retry", "error": type(error).__name__, "delay": delay, "received": len(buf)})
                self._sleeper(delay)
                continue
            finally:
                self._deadline = None

            if status == 206 and resuming:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", (_header(headers, "content-range") or "").strip())
                if (not match or int(match[1]) != len(buf)
                        or (total is not None and int(match[3]) != total)):
                    buf.clear()
                    total, can_range, validator = None, False, None
                    best, failures = 0, failures + 1
                    emit({"event": "restart", "reason": "content_range_mismatch"})
                    if failures > self.max_retries:
                        raise IncompleteRead(b"", None)
                    continue
                total = int(match[3])
                emit({"event": "resume", "offset": len(buf), "total": total})
                buf += body
            elif status == 200:
                if resuming:
                    emit({"event": "restart", "reason": "server_ignored_range"})
                if not partial:
                    return HttpResponse(status, headers, body)
                buf = bytearray(body)
                length = _header(headers, "content-length") or ""
                total = int(length) if length.isdigit() else None
                can_range = (_header(headers, "accept-ranges") or "").lower() == "bytes"
                etag = _header(headers, "etag")
                validator = etag if etag and not etag.startswith("W/") else None
            elif partial:
                raise IncompleteRead(bytes(body), None)
            elif status in RETRY_STATUSES:
                failures += 1
                if failures > self.max_retries:
                    return HttpResponse(status, headers, b"")
                delay = self._status_delay(HttpResponse(status, headers, b""), failures)
                emit({"event": "retry", "status": status, "delay": round(delay, 1), "received": len(buf)})
                self._sleeper(delay)
                continue
            else:
                return HttpResponse(status, headers, body)

            if len(buf) > self.max_bytes:
                raise ValueError("HTTP response exceeds configured size limit")
            if total is not None and len(buf) == total:
                return HttpResponse(200, headers, bytes(buf))
            if len(buf) > best:
                best, failures = len(buf), 0
            else:
                failures += 1
            emit({"event": "partial", "received": len(buf), "total": total, "attempt": attempt + 1})
            if failures > self.max_retries:
                raise IncompleteRead(bytes(buf), None if total is None else total - len(buf))
            self._sleeper(min(60.0, 2.0 ** max(failures - 1, 0)))
        raise IncompleteRead(bytes(buf), None if total is None else total - len(buf))
