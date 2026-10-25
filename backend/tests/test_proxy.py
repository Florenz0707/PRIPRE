"""Proxy routing is tested against local HTTP and WebSocket endpoints, never Binance."""

import asyncio
import base64
import json
import select
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

import pytest
from fastapi.testclient import TestClient
from pripre.api import create_app
from pripre.config import AppConfig
from pripre.data.binance import BinanceSource
from pripre.data.http import DownloadBudget, DownloadError, PublicHTTP
from pripre.data.proxy import SourceProxy
from websockets.asyncio.server import ServerConnection, serve


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), ProxyHandler)
        self.requests_seen: list[tuple[str, str, str | None]] = []
        self.response_code = 200
        self.tunnel_target: tuple[str, int] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        server = cast(ProxyServer, self.server)
        server.requests_seen.append(("GET", self.path, self.headers.get("Proxy-Authorization")))
        payload = b'{"serverTime":1790000000000}'
        self.send_response(server.response_code)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_CONNECT(self) -> None:
        server = cast(ProxyServer, self.server)
        server.requests_seen.append(("CONNECT", self.path, self.headers.get("Proxy-Authorization")))
        if server.tunnel_target is None:
            # Deliberately reflect a test password in the reason; callers must sanitize it.
            self.send_error(502, "proxy error p@ss")
            return
        with socket.create_connection(server.tunnel_target, timeout=2) as upstream:
            self.send_response(200, "Connection established")
            self.end_headers()
            self.wfile.flush()
            sockets = [self.connection, upstream]
            for _ in range(100):
                readable, _, _ = select.select(sockets, [], [], 2)
                if not readable:
                    return
                for current in readable:
                    data = current.recv(65536)
                    if not data:
                        return
                    (upstream if current is self.connection else self.connection).sendall(data)


@contextmanager
def proxy_server() -> Iterator[ProxyServer]:
    server = ProxyServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def authenticated_proxy(server: ProxyServer) -> SourceProxy:
    return SourceProxy(server.url.replace("http://", "http://alice:p%40ss@"))


def test_explicit_http_proxy_ignores_global_bypass_and_keeps_credentials_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    with proxy_server() as server:
        proxy = authenticated_proxy(server)
        client = PublicHTTP(DownloadBudget(2, 4096), proxy=proxy)
        assert json.loads(client.get("http://source-does-not-resolve.invalid/time"))["serverTime"]
        method, target, auth = server.requests_seen[0]
        assert method == "GET" and target == "http://source-does-not-resolve.invalid/time"
        assert auth == "Basic " + base64.b64encode(b"alice:p@ss").decode()
        assert "alice" not in repr(proxy) and "p@ss" not in str(proxy)
        assert proxy.endpoint == server.url


def test_https_uses_connect_and_does_not_leak_proxy_error_credentials() -> None:
    with proxy_server() as server:
        client = PublicHTTP(DownloadBudget(1, 4096), proxy=authenticated_proxy(server))
        with pytest.raises(DownloadError) as failure:
            client.get("https://source-does-not-resolve.invalid/time")
        assert server.requests_seen[0][:2] == ("CONNECT", "source-does-not-resolve.invalid:443")
        assert "p@ss" not in str(failure.value) and "p%40ss" not in str(failure.value)


def test_proxy_failure_never_falls_back_to_direct_and_direct_mode_ignores_global_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    with proxy_server() as origin, proxy_server() as proxy:
        proxy.response_code = 503
        client = PublicHTTP(DownloadBudget(1, 4096), proxy=SourceProxy(proxy.url))
        with pytest.raises(DownloadError, match="HTTP 503"):
            client.get(origin.url)
        assert not origin.requests_seen
        direct = PublicHTTP(DownloadBudget(1, 4096), proxy=SourceProxy())
        assert json.loads(direct.get(origin.url))["serverTime"]
        assert len(origin.requests_seen) == 1


def test_websocket_uses_the_same_authenticated_proxy_despite_global_no_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setattr("pripre.data.binance.STREAM_BASE", "ws://source-does-not-resolve.invalid")

    async def run() -> None:
        async def handler(socket: ServerConnection) -> None:
            await socket.send(
                json.dumps(
                    {"s": "BTCUSDT", "a": 1, "p": "10000.01", "q": "1", "T": 1790000000000000}
                )
            )
            await socket.wait_closed()

        async with serve(handler, "127.0.0.1", 0) as origin:
            with proxy_server() as server:
                server.tunnel_target = ("127.0.0.1", origin.sockets[0].getsockname()[1])
                proxy = authenticated_proxy(server)
                source = BinanceSource(
                    AppConfig().instrument,
                    PublicHTTP(DownloadBudget(1, 4096), proxy=proxy),
                    proxy=proxy,
                )
                stream = source.stream("BTCUSDT")
                try:
                    trade = await asyncio.wait_for(anext(stream), timeout=4)
                    assert trade.sequence == 1 and trade.instrument == "BTC_USDT"
                finally:
                    await stream.aclose()
                assert server.requests_seen[0][:2] == (
                    "CONNECT",
                    "source-does-not-resolve.invalid:80",
                )
                assert (
                    server.requests_seen[0][2]
                    == "Basic " + base64.b64encode(b"alice:p@ss").decode()
                )

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "socks5://localhost:1080",
        "https://localhost:443",
        "http://alice:secret@localhost:bad",
        "http://localhost:8080/path",
        "http://alice@localhost:8080",
    ],
)
def test_unsupported_or_invalid_proxy_is_rejected_without_echoing_secrets(url: str) -> None:
    with pytest.raises(ValueError) as failure:
        SourceProxy(url)
    assert "secret" not in str(failure.value)


def test_api_reports_only_proxy_enabled_flag_and_does_not_proxy_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIPRE_SOURCE_PROXY", "http://alice:p%40ss@127.0.0.1:1")
    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200
        result = client.get("/api/config")
        assert result.json()["network"] == {"source_proxy_enabled": True}
        assert "p%40ss" not in result.text and "p@ss" not in result.text


def test_direct_websocket_does_not_inherit_an_unrelated_global_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")

    async def run() -> None:
        async def handler(socket: ServerConnection) -> None:
            await socket.send(
                json.dumps(
                    {"s": "BTCUSDT", "a": 2, "p": "10000.01", "q": "1", "T": 1790000000000000}
                )
            )
            await socket.wait_closed()

        async with serve(handler, "127.0.0.1", 0) as origin:
            monkeypatch.setattr(
                "pripre.data.binance.STREAM_BASE",
                f"ws://127.0.0.1:{origin.sockets[0].getsockname()[1]}",
            )
            direct = SourceProxy()
            source = BinanceSource(
                AppConfig().instrument,
                PublicHTTP(DownloadBudget(1, 4096), proxy=direct),
                proxy=direct,
            )
            stream = source.stream("BTCUSDT")
            try:
                assert (await asyncio.wait_for(anext(stream), timeout=4)).sequence == 2
            finally:
                await stream.aclose()

    asyncio.run(run())


def test_explicit_source_check_covers_http_and_websocket_with_one_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pripre.data.probe import check_source

    monkeypatch.setattr(
        "pripre.data.binance.REST_BASE", "http://source-does-not-resolve.invalid/api/v3"
    )
    monkeypatch.setattr("pripre.data.binance.STREAM_BASE", "ws://source-does-not-resolve.invalid")

    async def run() -> None:
        async def handler(socket: ServerConnection) -> None:
            await socket.send(
                json.dumps(
                    {"s": "BTCUSDT", "a": 2, "p": "10000.01", "q": "1", "T": 1790000000000000}
                )
            )
            await socket.wait_closed()

        async with serve(handler, "127.0.0.1", 0) as origin:
            with proxy_server() as server:
                server.tunnel_target = ("127.0.0.1", origin.sockets[0].getsockname()[1])
                monkeypatch.setenv("PRIPRE_SOURCE_PROXY", authenticated_proxy(server).url or "")
                result = await check_source(AppConfig())
                assert result["http_ok"] and result["websocket_ok"]
                assert result["http_requests"] == 1 and "error" not in result
                assert "p%40ss" not in json.dumps(result) and "p@ss" not in json.dumps(result)
                assert [r[0] for r in server.requests_seen] == ["GET", "CONNECT"]

    asyncio.run(run())


def test_rate_limit_respects_retry_after_without_hidden_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.error
    from email.message import Message
    from typing import NoReturn
    from urllib.request import Request

    from pripre.data.http import HTTPStatusError

    now = [0]
    calls = [0]
    monkeypatch.setattr("pripre.data.http.steady_ns", lambda: now[0])

    def blocked(_opener: object, request: Request, *, timeout: float) -> NoReturn:
        calls[0] += 1
        headers = Message()
        headers["Retry-After"] = "120"
        raise urllib.error.HTTPError(request.full_url, 418, "banned", headers, None)

    monkeypatch.setattr("urllib.request.OpenerDirector.open", blocked)
    client = PublicHTTP(DownloadBudget(3, 1024), min_interval=0, proxy=SourceProxy())
    for _ in range(3):
        with pytest.raises(HTTPStatusError) as failure:
            client.get("https://source.invalid/time")
        assert failure.value.status == 418 and failure.value.retry_after_seconds == 120
    assert calls[0] == 1 and client.budget.requests == 1
    now[0] = 121_000_000_000
    with pytest.raises(HTTPStatusError):
        client.get("https://source.invalid/time")
    assert calls[0] == 2 and client.budget.requests == 2
