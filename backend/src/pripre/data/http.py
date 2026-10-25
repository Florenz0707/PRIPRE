"""Bounded public HTTP reads with explicit accounting and deterministic pacing."""

import math
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from pripre.clock import steady_ns
from pripre.data.proxy import SourceProxy


class DownloadError(RuntimeError):
    pass


class HTTPStatusError(DownloadError):
    def __init__(self, status: int, url: str, retry_after_seconds: int | None = None) -> None:
        self.status = status
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"HTTP {status}: {url}")


class BudgetExceeded(DownloadError):
    pass


@dataclass
class DownloadBudget:
    max_requests: int
    max_bytes: int
    requests: int = 0
    downloaded_bytes: int = 0


class PublicHTTP:
    def __init__(
        self,
        budget: DownloadBudget,
        min_interval: float = 0.15,
        timeout: float = 20,
        proxy: SourceProxy | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("HTTP timeout must be positive")
        self._timeout = timeout
        self.proxy = proxy if proxy is not None else SourceProxy.from_environment()
        self._opener = self.proxy.opener()
        self.budget = budget
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._interval = min_interval
        self._retry_at_ns = 0
        self._blocked_status = 429

    def get(self, url: str) -> bytes:
        """Bounded response; no hidden retry or unaccounted background requests."""
        with self._lock:
            remaining_wait = self._retry_at_ns - steady_ns()
            if remaining_wait > 0:
                raise HTTPStatusError(
                    self._blocked_status, url, math.ceil(remaining_wait / 1_000_000_000)
                )
            if self.budget.requests >= self.budget.max_requests:
                raise BudgetExceeded("request budget exhausted")
            if self.budget.downloaded_bytes >= self.budget.max_bytes:
                raise BudgetExceeded("download byte budget exhausted")
            time.sleep(max(0, self._interval - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            self.budget.requests += 1
            request = urllib.request.Request(
                url, headers={"User-Agent": "PRIPRE/0.1", "X-MBX-TIME-UNIT": "MICROSECOND"}
            )
            try:
                with self._opener.open(request, timeout=self._timeout) as response:
                    remaining = self.budget.max_bytes - self.budget.downloaded_bytes
                    declared = response.headers.get("Content-Length")
                    if declared is not None and int(declared) > remaining:
                        raise BudgetExceeded("response would exceed remaining byte budget")
                    chunks: list[bytes] = []
                    while remaining > 0:
                        chunk = response.read(min(65536, remaining))
                        if not chunk:
                            return b"".join(chunks)
                        self.budget.downloaded_bytes += len(chunk)
                        remaining -= len(chunk)
                        chunks.append(chunk)
                    raise BudgetExceeded("response reached byte budget before verified EOF")
            except urllib.error.HTTPError as exc:
                status = exc.code
                retry: int | None = None
                if status in (418, 429):
                    try:
                        seconds = float(exc.headers.get("Retry-After", "60"))
                        retry = (
                            math.ceil(min(604800, max(1, seconds)))
                            if math.isfinite(seconds)
                            else 60
                        )
                    except (TypeError, ValueError):
                        retry = 60
                    self._blocked_status = status
                    self._retry_at_ns = steady_ns() + retry * 1_000_000_000
                exc.close()
                raise HTTPStatusError(status, url, retry) from None
            except (OSError, urllib.error.URLError) as exc:
                raise DownloadError(
                    f"public data request failed ({type(exc).__name__}): {url}"
                ) from None
