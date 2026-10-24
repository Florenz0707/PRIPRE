"""Feed gaps fence predictions; subscribers share one computation and bounded queues."""

import asyncio
from decimal import Decimal

import numpy as np
import pytest
from pripre.config import AppConfig, RuntimeConfig
from pripre.domain import Trade
from pripre.models.paths import Forecast
from pripre.runtime import MatrixRuntime


class Engine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.calls = 0

    def predict(self, reference: Decimal, timestamp_us: int, volatility: float) -> Forecast:
        self.calls += 1
        grid = self.config.grid.build(reference, timestamp_us)
        return Forecast(grid, np.full((21, 35), 0.25), "test-engine", 64)


def test_one_computation_serves_fifty_latest_only_subscribers() -> None:
    async def run() -> None:
        now = [61_000_000]
        config = AppConfig(runtime=RuntimeConfig(live_enabled=True))
        engine = Engine(config)
        runtime = MatrixRuntime(config, engine=engine, clock=lambda: now[0])
        for second in range(62):
            runtime.ingest(
                Trade(
                    instrument="BTC_USDT",
                    source="binance",
                    sequence=second,
                    timestamp_us=second * 1_000_000,
                    price=Decimal(10000),
                    quantity=Decimal(1),
                )
            )
        queues = [runtime.subscribe() for _ in range(50)]
        with pytest.raises(ValueError, match="maximum"):
            runtime.subscribe()
        snapshot = await runtime.tick()
        assert snapshot["status"] == "ready" and engine.calls == 1
        now[0] += 1_000_000
        await runtime.tick()
        assert engine.calls == 2 and all(queue.qsize() == 1 for queue in queues)
        assert all(queue.get_nowait()["computations"] == 2 for queue in queues)
        now[0] += 10_000_000
        assert (await runtime.tick())["status"] == "stale"
        assert engine.calls == 2
        runtime.disconnect()
        assert (await runtime.tick())["probabilities"] is None

    asyncio.run(run())


def test_sequence_gap_requires_a_new_warmup_and_duplicates_are_ignored() -> None:
    config = AppConfig(runtime=RuntimeConfig(live_enabled=True))
    runtime = MatrixRuntime(config, clock=lambda: 100_000_000)

    def trade(sequence: int, seconds: int) -> Trade:
        return Trade(
            instrument="BTC_USDT",
            source="binance",
            sequence=sequence,
            timestamp_us=seconds * 1_000_000,
            price=Decimal(10000),
            quantity=Decimal(1),
        )

    runtime.ingest(trade(1, 90))
    runtime.ingest(trade(1, 90))
    runtime.ingest(trade(3, 91))
    assert runtime.duplicates == 1 and runtime.gaps == 1
    assert runtime.coverage_start_us == 91_000_000 and len(runtime.trades) == 1


def test_feed_gap_during_inference_discards_the_finished_matrix() -> None:
    import threading

    async def run() -> None:
        started = threading.Event()
        release = threading.Event()
        config = AppConfig(runtime=RuntimeConfig(live_enabled=True))

        class DelayedEngine(Engine):
            def predict(self, reference: Decimal, timestamp_us: int, volatility: float) -> Forecast:
                started.set()
                assert release.wait(timeout=2)
                return super().predict(reference, timestamp_us, volatility)

        runtime = MatrixRuntime(config, engine=DelayedEngine(config), clock=lambda: 61_000_000)
        for second in range(62):
            runtime.ingest(
                Trade(
                    instrument="BTC_USDT",
                    source="binance",
                    sequence=second,
                    timestamp_us=second * 1_000_000,
                    price=Decimal(10000),
                    quantity=Decimal(1),
                )
            )
        pending = asyncio.create_task(runtime.tick())
        assert await asyncio.to_thread(started.wait, 1)
        runtime.disconnect()
        release.set()
        result = await pending
        assert result["probabilities"] is None
        assert result["status"] == "warming_up"

    asyncio.run(run())
