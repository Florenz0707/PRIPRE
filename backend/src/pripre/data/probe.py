"""Explicit, bounded source connectivity checks; never run as a startup side effect."""

import asyncio
from contextlib import aclosing

from pripre.config import AppConfig
from pripre.data.binance import BinanceSource
from pripre.data.http import DownloadBudget, HTTPStatusError, PublicHTTP
from pripre.data.proxy import SourceProxy


async def check_source(config: AppConfig) -> dict[str, object]:
    if config.source.provider != "binance":
        raise ValueError("source-check currently requires the Binance adapter")
    proxy = SourceProxy.from_environment()
    budget = DownloadBudget(1, 65536)
    source = BinanceSource(
        config.instrument, PublicHTTP(budget, timeout=3, proxy=proxy), proxy=proxy
    )
    result: dict[str, object] = {
        "source": config.source.provider,
        "instrument": config.instrument.id,
        "proxy_enabled": proxy.enabled,
        "proxy_endpoint": proxy.endpoint,
        "http_ok": False,
        "websocket_ok": False,
    }
    try:
        result["server_time_us"] = await asyncio.wait_for(source.server_time(), timeout=5)
        result["http_ok"] = True
    except HTTPStatusError as exc:
        result.update(
            http_error_type=type(exc).__name__,
            http_status=exc.status,
            retry_after_seconds=exc.retry_after_seconds,
        )
    except Exception as exc:
        # Proxy exceptions may contain credentials; report only the exception type.
        result["http_error_type"] = type(exc).__name__
    try:
        async with aclosing(source.stream(config.source.symbol)) as stream:
            trade = await asyncio.wait_for(anext(stream), timeout=15)
        result.update(websocket_ok=True, trade_timestamp_us=trade.timestamp_us)
    except Exception as exc:
        result["websocket_error_type"] = type(exc).__name__
    result.update(http_requests=budget.requests, http_bytes=budget.downloaded_bytes)
    if not result["http_ok"] or not result["websocket_ok"]:
        result["error"] = "source connectivity check failed; no direct fallback was attempted"
    return result
