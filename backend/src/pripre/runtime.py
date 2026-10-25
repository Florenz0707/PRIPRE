"""One shared inference loop with bounded latest-value subscriptions and feed fencing."""

import asyncio
import logging
import sqlite3
from collections import deque
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

import numpy as np
from websockets.exceptions import WebSocketException

from pripre.clock import RAW_CLOCK, ClockSample, MonotonicUTC, steady_ns, wait_until
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
        elapsed_ns: Callable[[], int] | None = None,
    ) -> None:
        self.config = config
        self.source = source
        self.engine = engine
        if clock is not None and clock_sync is not None:
            raise ValueError("choose either an injected clock or a source clock synchronizer")
        self._elapsed_ns = elapsed_ns or steady_ns
        self._utc = MonotonicUTC(monotonic_ns=self._elapsed_ns)
        self.elapsed_clock = (
            "injected" if elapsed_ns else "monotonic_raw" if RAW_CLOCK is not None else "monotonic"
        )
        self.stream_id = uuid4().hex
        self._frame_sequence = 0
        self.clock_epoch = 0
        self.clock_syncs = 0
        self.clock_sync_failures = 0
        self.clock_adjustment_us: int | None = None
        self._last_clock_sync_ns: int | None = None
        self._clock_usable = False
        self._clock_lock = asyncio.Lock()
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
        self.snapshot: dict[str, object] = {
            "status": "starting",
            "probabilities": None,
            "timestamp_us": self.clock(),
            "stream_id": self.stream_id,
            "frame_sequence": 0,
            "frame_elapsed_us": self._elapsed_ns() // 1000,
        }

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
            if self._clock_sync is not None:
                self._tasks.append(asyncio.create_task(self._clock_loop()))

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
        if not self._clock_trusted():
            return
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

    def _clock_trusted(self) -> bool:
        if self._clock_sync is None:
            return True
        age = (
            self._elapsed_ns() - self._last_clock_sync_ns
            if self._last_clock_sync_ns is not None
            else None
        )
        if age is None or age > self.config.runtime.clock_max_age_seconds * 1_000_000_000:
            if self._clock_usable:
                self.clock_epoch += 1
                self._clock_usable = False
                self.disconnect()
            return False
        return self._clock_usable

    async def resynchronize_clock(self) -> None:
        if self._clock_sync is None:
            return
        async with self._clock_lock:
            samples: list[ClockSample] = []
            for _ in range(3):
                start_ns = self._elapsed_ns()
                try:
                    source_us = await asyncio.wait_for(self._clock_sync(), timeout=3)
                    samples.append(ClockSample(source_us, start_ns, self._elapsed_ns()))
                except (OSError, ValueError, DownloadError, TimeoutError):
                    continue
            before = self._utc()
            trusted = self._clock_trusted()
            try:
                uncertainty = self._utc.synchronize_samples(samples)
            except ValueError:
                self.clock_sync_failures += 1
                raise
            self.clock_adjustment_us = self._utc() - before
            # Large corrections invalidate the entire feature window, including in-flight inference.
            if not trusted or abs(self.clock_adjustment_us) > 500_000:
                self.clock_epoch += 1
                self.disconnect()
            self.clock_uncertainty_us = uncertainty
            self._last_clock_sync_ns = self._utc.sampled_at_ns
            self._clock_usable = True
            self.clock_syncs += 1

    async def _clock_loop(self) -> None:
        while True:
            await wait_until(
                self._elapsed_ns() + self.config.runtime.clock_sync_seconds * 1_000_000_000,
                self._elapsed_ns,
            )
            try:
                await self.resynchronize_clock()
            except (OSError, ValueError, DownloadError):
                logger.warning(
                    "Source clock synchronization failed; retaining only unexpired calibration"
                )

    def for_delivery(self, payload: dict[str, object]) -> dict[str, object]:
        """Attach server-side queue age without reusing source UTC as a transport timer."""
        result = dict(payload)
        elapsed = payload.get("frame_elapsed_us")
        result["frame_age_ms"] = (
            max(0.0, (self._elapsed_ns() / 1000 - elapsed) / 1000)
            if isinstance(elapsed, int)
            else 0.0
        )
        if payload.get("status") == "ready":
            if not self._clock_trusted():
                result.update(status="clock_unavailable", probabilities=None)
            elif payload.get("clock_epoch") != self.clock_epoch:
                result.update(status="warming_up", probabilities=None)
        return result

    async def _feed(self) -> None:
        if self.source is None:
            return
        delay = 1
        while True:
            try:
                await self.resynchronize_clock()
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
        self._frame_sequence += 1
        payload.update(stream_id=self.stream_id, frame_sequence=self._frame_sequence)
        if payload.get("status") == "ready":
            if not self._clock_trusted():
                payload.update(status="clock_unavailable", probabilities=None)
            elif payload.get("clock_epoch") != self.clock_epoch:
                payload.update(status="warming_up", probabilities=None)
        self.snapshot = payload
        for queue in self._clients:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(payload)
        return payload

    async def tick(self) -> dict[str, object]:
        trusted = self._clock_trusted()
        epoch = self.clock_epoch
        now = self.clock()
        last = self.trades[-1] if self.trades else None
        payload: dict[str, object] = {
            "timestamp_us": now,
            "frame_elapsed_us": self._elapsed_ns() // 1000,
            "elapsed_clock": self.elapsed_clock,
            "clock_epoch": epoch,
            "clock_syncs": self.clock_syncs,
            "clock_sync_failures": self.clock_sync_failures,
            "clock_adjustment_us": self.clock_adjustment_us,
            "clock_sync_age_ms": (self._elapsed_ns() - self._last_clock_sync_ns) / 1_000_000
            if self._last_clock_sync_ns is not None
            else None,
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
            "parameters": {
                "grid": self.config.grid.model_dump(mode="json"),
                "runtime": self.config.runtime.model_dump(mode="json"),
            },
            "seed": self.config.runtime.seed,
        }
        if not self.config.runtime.live_enabled:
            payload["status"] = "disabled"
        elif not trusted:
            payload["status"] = "clock_unavailable"
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
            start = self._elapsed_ns()
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
                elapsed = (self._elapsed_ns() - start) / 1_000_000
                self.computations += 1
                # Feed can disconnect or advance through a gap while inference runs in its thread.
                if not self._clock_trusted():
                    payload["status"] = "clock_unavailable"
                elif (
                    epoch != self.clock_epoch
                    or not self.connected
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

            except (ValueError, OSError, sqlite3.Error):
                logger.exception("Matrix calculation failed")
                payload["status"] = "model_error"
                payload["probabilities"] = None
        if self.journal is not None:
            try:
                await asyncio.to_thread(self.journal.append, now, payload.copy())
            except (OSError, sqlite3.Error):
                logger.exception("Prediction journal failed")
                payload.update(status="journal_error", probabilities=None)
        return self._publish(payload)

    async def _ticker(self) -> None:
        while True:
            start = self._elapsed_ns()
            await self.tick()
            deadline = max(
                start + self.config.runtime.update_seconds * 1_000_000_000,
                self._elapsed_ns() + 10_000_000,
            )
            await wait_until(deadline, self._elapsed_ns)
