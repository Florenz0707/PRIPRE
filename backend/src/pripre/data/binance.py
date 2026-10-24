"""Binance spot adapter; timestamps are normalized to UTC microseconds."""

import asyncio
import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Protocol
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field
from websockets.asyncio.client import connect

from pripre.data.source import Capabilities, TradeBatch
from pripre.domain import Coverage, Instrument, Trade

REST_BASE = "https://data-api.binance.vision/api/v3"
ARCHIVE_BASE = "https://data.binance.vision/data/spot"


class HTTPReader(Protocol):
    def get(self, url: str) -> bytes: ...


class AggregateRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    a: int = Field(ge=0)
    p: Decimal = Field(gt=0, allow_inf_nan=False)
    q: Decimal = Field(ge=0, allow_inf_nan=False)
    T: int = Field(ge=0)


def timestamp_us(value: int) -> int:
    """REST defaults to milliseconds; 2025+ spot archives use microseconds."""
    return value if value >= 100_000_000_000_000 else value * 1000


class BinanceSource:
    id = "binance"
    capabilities = Capabilities(historical_trades=True, live_trades=True)

    def __init__(self, instrument: Instrument, http: HTTPReader) -> None:
        self.instrument = instrument
        self.http = http

    def parse(self, payload: object) -> Trade:
        record = AggregateRecord.model_validate(payload)
        if record.p % self.instrument.tick_size:
            raise ValueError("trade price does not align with instrument tick size")
        return Trade(
            instrument=self.instrument.id,
            source=self.id,
            sequence=record.a,
            timestamp_us=timestamp_us(record.T),
            price=record.p,
            quantity=record.q,
        )

    def fetch_history(self, symbol: str, start_us: int, end_us: int) -> TradeBatch:
        if start_us >= end_us or start_us % 1000 or end_us % 1000:
            raise ValueError("historical request must be ordered and millisecond aligned")
        cursor: int | None = None
        trades: list[Trade] = []
        previous: Trade | None = None
        while True:
            params: dict[str, str | int] = {"symbol": symbol, "limit": 1000}
            if cursor is None:
                params.update(startTime=start_us, endTime=end_us - 1)
            else:
                params["fromId"] = cursor
            records: object = json.loads(
                self.http.get(f"{REST_BASE}/aggTrades?{urlencode(params)}")
            )
            if not isinstance(records, list):
                raise ValueError("expected a trade array")
            if cursor is not None and not records:
                raise ValueError("unexpected empty page after a full page")
            crossed_end = False
            for payload in records:
                trade = self.parse(payload)
                if previous is not None:
                    if trade.sequence != previous.sequence + 1:
                        raise ValueError("aggregate trade sequence gap, duplicate or reordering")
                    if trade.timestamp_us < previous.timestamp_us:
                        raise ValueError("trade timestamps are not ordered")
                previous = trade
                if trade.timestamp_us >= end_us:
                    crossed_end = True
                    break
                if trade.timestamp_us < start_us:
                    raise ValueError("provider returned trade before requested start")
                trades.append(trade)
            if crossed_end or len(records) < 1000:
                break
            if previous is None:
                raise ValueError("pagination made no progress")
            cursor = previous.sequence + 1
        return TradeBatch(tuple(trades), (Coverage(start_us=start_us, end_us=end_us),))

    async def history(self, symbol: str, start_us: int, end_us: int) -> TradeBatch:
        return await asyncio.to_thread(self.fetch_history, symbol, start_us, end_us)

    async def stream(self, symbol: str) -> AsyncIterator[Trade]:
        # A disconnect ends this iterator. The caller marks a gap before reconnecting.
        url = f"wss://data-stream.binance.vision/ws/{symbol.lower()}@aggTrade?timeUnit=MICROSECOND"
        async with connect(url, open_timeout=10, close_timeout=3, max_size=65536) as socket:
            async for message in socket:
                payload: object = json.loads(message)
                if not isinstance(payload, dict) or payload.get("s") != symbol:
                    raise ValueError("unexpected stream symbol or message")
                yield self.parse(payload)
