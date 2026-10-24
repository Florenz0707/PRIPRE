"""One shared inference loop with bounded latest-value subscriptions and feed fencing."""

import asyncio
import logging
import sqlite3
import time
from collections import deque
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Protocol

import numpy as np
from websockets.exceptions import WebSocketException

from pripre.clock import ClockSample, MonotonicUTC
from pripre.config import AppConfig
from pripre.data.http import DownloadError
from pripre.data.source import MarketSource
from pripre.domain import Trade
from pripre.features.volatility import trailing_volatility
from pripre.journal import PredictionJournal
from pripre.models.engine import build_engine
from pripre.models.paths import Forecast

logger = logging.getLogger(__name__)


class ProbabilityEngine(Protocol):
    def predict(self, reference: Decimal, timestamp_us: int, volatility: float) -> Forecast: ...


class MatrixRuntime:
    def __init__(
        self,
        config: AppConfig,
        source: MarketSource | None = None,
        engine: ProbabilityEngine | None = None,
        clock: Callable[[], int] | None = None,
        clock_sync: Callable[[], Awaitable[int]] | None = None,
        journal: PredictionJournal | None = None,
    ) -> None:
        self.config = config
        self.source = source
        self.engine = engine
        if clock is not None and clock_sync is not None:
            raise ValueError("choose either an injected clock or a source clock synchronizer")
        self._utc = MonotonicUTC()
        self.clock = clock or self._utc
        self._clock_sync = clock_sync
        self.clock_uncertainty_us: int | None = None
        self.journal = journal
        self.trades: deque[Trade] = deque()
        self.coverage_start_us: int | None = None
        self.connected = False
        self.duplicates = 0
        self.gaps = 0
        self.reconnects = 0
        self.computations = 0
        self._tasks: list[asyncio.Task[None]] = []
        self._clients: set[asyncio.Queue[dict[str, object]]] = set()
        self.snapshot: dict[str, object] = {"status": "starting", "probabilities": None}

    @property
    def clients(self) -> int:
        return len(self._clients)

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._ticker()))
        if self.config.runtime.live_enabled:
            if self.engine is None:
                self._tasks.append(asyncio.create_task(self._prepare()))
            if self.source is not None:
                self._tasks.append(asyncio.create_task(self._feed()))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _prepare(self) -> None:
        try:
            self.engine = await asyncio.to_thread(build_engine, self.config)
        except (OSError, ValueError):
            logger.exception("Local probability model could not be trained")

    def disconnect(self) -> None:
        self.connected = False
        self.coverage_start_us = None
        self.trades.clear()

    def ingest(self, trade: Trade) -> None:
        now = self.clock()
        if (
            trade.instrument != self.config.instrument.id
            or trade.source != self.config.source.provider
        ):
            raise ValueError("feed identity differs from configured instrument and source")
        if trade.timestamp_us > now + 2_000_000:
            raise ValueError("trade timestamp is ahead of local clock")
        if self.trades:
            previous = self.trades[-1]
            if trade.sequence <= previous.sequence:
                self.duplicates += 1
                return
            if (
                trade.sequence != previous.sequence + 1
                or trade.timestamp_us < previous.timestamp_us
                or trade.timestamp_us - previous.timestamp_us
                > self.config.runtime.stale_seconds * 1_000_000
            ):
                self.gaps += 1
                self.disconnect()
        if self.coverage_start_us is None:
            self.coverage_start_us = trade.timestamp_us
        self.connected = True
        self.trades.append(trade)
        while self.trades and self.trades[0].timestamp_us < now - 65_000_000:
            self.trades.popleft()
        if len(self.trades) > 200_000:
            self.gaps += 1
            self.disconnect()

    async def _feed(self) -> None:
        if self.source is None:
            return
        delay = 1
        while True:
            try:
                if self._clock_sync is not None:
                    samples: list[ClockSample] = []
                    for _ in range(3):
                        start_ns = time.monotonic_ns()
                        try:
                            source_us = await self._clock_sync()
                            samples.append(ClockSample(source_us, start_ns, time.monotonic_ns()))
                        except (OSError, ValueError, DownloadError):
                            continue
                    self.clock_uncertainty_us = self._utc.synchronize_samples(samples)
                async for trade in self.source.stream(self.config.source.symbol):
                    self.ingest(trade)
                    delay = 1
                raise ConnectionError("trade stream ended")
            except asyncio.CancelledError:
                raise
            except (OSError, ValueError, ConnectionError, WebSocketException, DownloadError) as exc:
                logger.warning("Trade feed disconnected: %s", type(exc).__name__)
                self.disconnect()
                self.reconnects += 1
                await asyncio.sleep(delay)
                delay = min(30, delay * 2)

    def subscribe(self) -> asyncio.Queue[dict[str, object]]:
        if self.clients >= self.config.runtime.max_clients:
            raise ValueError("maximum number of clients reached")
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=1)
        queue.put_nowait(self.snapshot)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._clients.discard(queue)

    def _publish(self, payload: dict[str, object]) -> dict[str, object]:
        self.snapshot = payload
        for queue in self._clients:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(payload)
        return payload

    async def tick(self) -> dict[str, object]:
        now = self.clock()
        last = self.trades[-1] if self.trades else None
        payload: dict[str, object] = {
            "timestamp_us": now,
            "instrument": self.config.instrument.id,
            "source": self.config.source.provider,
            "probabilities": None,
            "reference_price": str(last.price) if last else None,
            "trade_timestamp_us": last.timestamp_us if last else None,
            "clients": self.clients,
            "computations": self.computations,
            "gaps": self.gaps,
            "duplicates": self.duplicates,
            "reconnects": self.reconnects,
            "clock_uncertainty_us": self.clock_uncertainty_us,
        }
        if not self.config.runtime.live_enabled:
            payload["status"] = "disabled"
        elif not self.connected or last is None:
            payload["status"] = "disconnected"
        elif now - last.timestamp_us > self.config.runtime.stale_seconds * 1_000_000:
            payload["status"] = "stale"
        elif self.coverage_start_us is None or now - self.coverage_start_us < 60_000_000:
            payload["status"] = "warming_up"
        elif self.engine is None:
            payload["status"] = "model_unavailable"
        else:
            history = tuple(self.trades)
            start = time.perf_counter()
            try:
                volatility = trailing_volatility(history, now)
                forecast = await asyncio.to_thread(self.engine.predict, last.price, now, volatility)
                matrix = forecast.probabilities
                if (
                    matrix.shape != (self.config.grid.rows, self.config.grid.columns)
                    or np.any(~np.isfinite(matrix))
                    or np.any((matrix < 0) | (matrix > 1))
                ):
                    raise ValueError("estimator returned an invalid probability matrix")
                elapsed = (time.perf_counter() - start) * 1000
                self.computations += 1
                # Feed can disconnect or advance through a gap while inference runs in its thread.
                if (
                    not self.connected
                    or self.coverage_start_us is None
                    or self.coverage_start_us > now - 60_000_000
                ):
                    payload["status"] = "warming_up"
                elif elapsed > 1000:
                    payload["status"] = "calculation_overdue"
                else:
                    payload.update(
                        status=forecast.status,
                        grid=forecast.grid.model_dump(mode="json"),
                        model=forecast.model,
                        model_version=forecast.version,
                        trained_through_us=forecast.trained_through_us,
                        seed=self.config.runtime.seed,
                        paths=forecast.paths,
                        volatility=volatility,
                        calculation_ms=elapsed,
                        computations=self.computations,
                    )
                    if forecast.status == "ready":
                        payload["probabilities"] = forecast.probabilities.tolist()
                        if self.journal is not None:
                            await asyncio.to_thread(self.journal.append, now, payload.copy())
            except (ValueError, OSError, sqlite3.Error):
                logger.exception("Matrix calculation failed")
                payload["status"] = "model_error"
                payload["probabilities"] = None
        return self._publish(payload)

    async def _ticker(self) -> None:
        while True:
            start = time.monotonic()
            await self.tick()
            await asyncio.sleep(
                max(0.01, self.config.runtime.update_seconds - (time.monotonic() - start))
            )
