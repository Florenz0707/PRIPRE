"""Bounded public HTTP reads with explicit accounting and deterministic pacing."""

import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class DownloadError(RuntimeError):
    pass


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
        self, budget: DownloadBudget, min_interval: float = 0.15, timeout: float = 20
    ) -> None:
        if timeout <= 0:
            raise ValueError("HTTP timeout must be positive")
        self._timeout = timeout
        self.budget = budget
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._interval = min_interval

    def get(self, url: str) -> bytes:
        """Bounded response; no hidden retry or unaccounted background requests."""
        with self._lock:
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
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
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
                raise DownloadError(f"HTTP {exc.code}: {url}") from exc
            except (OSError, urllib.error.URLError) as exc:
                raise DownloadError(f"public data request failed: {url}: {exc}") from exc
