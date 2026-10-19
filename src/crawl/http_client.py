"""Small serialized HTTP client with polite pacing and bounded retries."""

from __future__ import annotations

from dataclasses import dataclass
import email.utils
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class HttpClient:
    """One-connection-at-a-time HTTP client suitable for arXiv endpoints."""

    def __init__(
        self,
        user_agent: str,
        *,
        min_interval: float = 3.0,
        timeout: float = 60.0,
        max_retries: int = 4,
        transport: Callable[[Request, float], HttpResponse] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.user_agent = user_agent
        self.min_interval = max(0.0, min_interval)
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self._transport = transport or self._urlopen
        self._sleeper = sleeper
        self._clock = clock
        self._last_request = float("-inf")
        self._lock = threading.Lock()

    @staticmethod
    def _urlopen(request: Request, timeout: float) -> HttpResponse:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, dict(response.headers.items()), response.read())

    @staticmethod
    def _retry_after(headers: dict[str, str], fallback: float) -> float:
        value = headers.get("Retry-After")
        if not value:
            return fallback
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                target = email.utils.parsedate_to_datetime(value).timestamp()
                return max(0.0, target - time.time())
            except (TypeError, ValueError, OverflowError):
                return fallback

    def get(self, url: str) -> HttpResponse:
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "*/*"})
        with self._lock:
            for attempt in range(self.max_retries + 1):
                wait = self.min_interval - (self._clock() - self._last_request)
                if wait > 0:
                    self._sleeper(wait)
                self._last_request = self._clock()
                try:
                    response = self._transport(request, self.timeout)
                except HTTPError as error:
                    response = HttpResponse(error.code, dict(error.headers.items()), error.read())
                except (URLError, TimeoutError):
                    if attempt >= self.max_retries:
                        raise
                    self._sleeper(min(60.0, 2.0**attempt))
                    continue
                if response.status not in {429, 500, 502, 503, 504}:
                    return response
                if attempt >= self.max_retries:
                    return response
                self._sleeper(self._retry_after(response.headers, min(60.0, 2.0**attempt)))
            raise AssertionError("unreachable")
