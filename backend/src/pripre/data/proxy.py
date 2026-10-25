"""Explicit data-source routing; proxy credentials never enter research configuration."""

import base64
import os
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class SourceProxy:
    url: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.url is None:
            return
        try:
            parsed = urlsplit(self.url)
            valid = (
                self.url.isascii()
                and not any(char.isspace() for char in self.url)
                and parsed.scheme == "http"
                and bool(parsed.hostname)
                and (parsed.port is None or 1 <= parsed.port <= 65535)
                and parsed.path in ("", "/")
                and not parsed.query
                and not parsed.fragment
                and ((parsed.username is None) == (parsed.password is None))
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "PRIPRE_SOURCE_PROXY requires an HTTP proxy URL with host and valid port"
            )

    @classmethod
    def from_environment(cls) -> "SourceProxy":
        return cls(os.environ.get("PRIPRE_SOURCE_PROXY", "").strip() or None)

    @property
    def enabled(self) -> bool:
        return self.url is not None

    @property
    def endpoint(self) -> str | None:
        if self.url is None:
            return None
        parsed = urlsplit(self.url)
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        return f"http://{host}:{parsed.port or 80}"

    def opener(self) -> urllib.request.OpenerDirector:
        # Always suppress global proxy auto-discovery, including NO_PROXY overrides.
        handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
        if self.url is not None:
            handlers.append(_ExplicitProxyHandler(self.url))
        return urllib.request.build_opener(*handlers)

    def __repr__(self) -> str:
        return f"SourceProxy(enabled={self.enabled})"


class _ExplicitProxyHandler(urllib.request.BaseHandler):
    handler_order = 100

    def __init__(self, url: str) -> None:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        self._authority = f"{host}:{parsed.port or 80}"
        self._authorization: str | None = None
        if parsed.username is not None and parsed.password is not None:
            raw = f"{unquote(parsed.username)}:{unquote(parsed.password)}".encode()
            self._authorization = "Basic " + base64.b64encode(raw).decode("ascii")

    def http_open(self, request: urllib.request.Request) -> None:
        # HTTP requests use absolute targets; HTTPSHandler performs CONNECT and verifies origin TLS.
        request.set_proxy(self._authority, "http")
        if self._authorization is not None:
            request.add_unredirected_header("Proxy-Authorization", self._authorization)

    https_open = http_open
