"""Provider seam: quote-only adapters cannot masquerade as trade feeds."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from pripre.domain import Coverage, Instrument, Trade


@dataclass(frozen=True)
class Capabilities:
    historical_trades: bool
    live_trades: bool


@dataclass(frozen=True)
class TradeBatch:
    trades: tuple[Trade, ...]
    coverage: tuple[Coverage, ...]


class MarketSource(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def capabilities(self) -> Capabilities: ...

    async def history(self, symbol: str, start_us: int, end_us: int) -> TradeBatch: ...

    def stream(self, symbol: str) -> AsyncIterator[Trade]: ...


class SourceRegistry:
    """Composition root registration; callers are independent of adapter types."""

    def __init__(self) -> None:
        self._sources: dict[str, MarketSource] = {}
        self._bindings: dict[tuple[str, str], str] = {}

    def register(self, source: MarketSource, instrument: Instrument, symbol: str) -> None:
        existing = self._sources.get(source.id)
        if existing is not None and existing is not source:
            raise ValueError(f"duplicate source id: {source.id}")
        self._sources[source.id] = source
        self._bindings[instrument.id, source.id] = symbol

    def resolve(self, instrument: str, provider: str, *, live: bool) -> tuple[MarketSource, str]:
        try:
            source = self._sources[provider]
            symbol = self._bindings[instrument, provider]
        except KeyError as exc:
            raise ValueError(f"unsupported instrument/source: {instrument}/{provider}") from exc
        supported = (
            source.capabilities.live_trades if live else source.capabilities.historical_trades
        )
        if not supported:
            raise ValueError("source does not provide the required trade-level evidence")
        return source, symbol
