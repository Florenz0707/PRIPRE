"""A slewed OS clock must not age fresh market trades or old predictions."""

import importlib
import time

import pytest


@pytest.mark.skipif(not hasattr(time, "CLOCK_MONOTONIC_RAW"), reason="Linux raw clock")
def test_default_market_clock_ignores_three_percent_system_clock_slew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pripre.clock as clocks

    raw = [0]
    adjusted = [0]
    try:
        with monkeypatch.context() as patch:
            # Reload also simulates a process started while the OS clock is slewing.
            patch.setattr(time, "monotonic_ns", lambda: adjusted[0])
            patch.setattr(time, "clock_gettime_ns", lambda _clock_id: raw[0])
            importlib.reload(clocks)
            clock = clocks.MonotonicUTC(anchor_us=100_000_000)
            raw[0] = 180_000_000_000
            adjusted[0] = 185_400_000_000
            assert clock() == 280_000_000, "fresh trades must not acquire 5.4s of false age"
    finally:
        importlib.reload(clocks)


def test_expired_calibration_pauses_and_recovery_requires_new_warmup() -> None:
    import asyncio
    from decimal import Decimal

    import numpy as np
    from pripre.config import AppConfig, RuntimeConfig
    from pripre.domain import Trade
    from pripre.models.paths import Forecast
    from pripre.runtime import MatrixRuntime

    async def run() -> None:
        raw = [0]
        failed = [False]
        offset = [0]
        config = AppConfig(runtime=RuntimeConfig(live_enabled=True))

        async def source_time() -> int:
            if failed[0]:
                raise OSError("clock endpoint unavailable")
            return 1_000_000_000 + raw[0] // 1000 + offset[0]

        class Engine:
            def predict(self, reference: Decimal, timestamp_us: int, volatility: float) -> Forecast:
                return Forecast(
                    config.grid.build(reference, timestamp_us), np.zeros((21, 35)), "test", 64
                )

        runtime = MatrixRuntime(
            config, engine=Engine(), clock_sync=source_time, elapsed_ns=lambda: raw[0]
        )
        await runtime.resynchronize_clock()

        def ingest(second: int) -> None:
            raw[0] = second * 1_000_000_000
            runtime.ingest(
                Trade(
                    instrument="BTC_USDT",
                    source="binance",
                    sequence=second,
                    timestamp_us=1_000_000_000 + second * 1_000_000,
                    price=Decimal(10000),
                    quantity=Decimal(1),
                )
            )

        for second in range(61):
            ingest(second)
        ready = await runtime.tick()
        assert ready["status"] == "ready"
        first_sequence = ready["frame_sequence"]
        next_sequence = (await runtime.tick())["frame_sequence"]
        assert isinstance(first_sequence, int) and isinstance(next_sequence, int)
        assert next_sequence > first_sequence
        offset[0] = 100_000
        await runtime.resynchronize_clock()
        assert (await runtime.tick())["status"] == "ready"  # Small correction preserves coverage.
        failed[0] = True
        raw[0] = 70_000_000_000
        with pytest.raises(ValueError, match="low-latency"):
            await runtime.resynchronize_clock()
        for second in range(61, 71):
            ingest(second)
        assert (await runtime.tick())["status"] == "ready"  # Last good calibration is still valid.
        raw[0] = 151_000_000_000
        expired = await runtime.tick()
        assert expired["status"] == "clock_unavailable" and expired["probabilities"] is None
        assert not runtime.trades
        assert (
            runtime.for_delivery(ready)["probabilities"] is None
        )  # Queued old frames are fenced too.
        failed[0] = False
        offset[0] = 0
        await runtime.resynchronize_clock()
        ingest(152)
        recovered = await runtime.tick()
        assert recovered["status"] == "warming_up" and recovered["probabilities"] is None
        assert recovered["clock_sync_failures"] == 1
        assert recovered["clock_syncs"] == 3

    asyncio.run(run())


def test_resync_uses_raw_time_for_both_round_trip_and_extrapolation() -> None:
    import asyncio

    from pripre.config import AppConfig
    from pripre.runtime import MatrixRuntime

    async def run() -> None:
        raw = [0]

        async def source_time() -> int:
            server = 100_000_000 + raw[0] // 1000 + 100_000
            raw[0] += 200_000_000
            return server

        runtime = MatrixRuntime(AppConfig(), clock_sync=source_time, elapsed_ns=lambda: raw[0])
        await runtime.resynchronize_clock()
        assert runtime.clock() == 100_600_000
        assert runtime.clock_uncertainty_us == 100_000
        snap = await runtime.tick()
        assert snap["clock_sync_age_ms"] == 400
        raw[0] += 1_000_000_000
        assert runtime.for_delivery(snap)["frame_age_ms"] == 1000

    asyncio.run(run())


def test_large_backward_resync_discards_inflight_and_queued_predictions() -> None:
    import asyncio
    import threading
    from decimal import Decimal

    import numpy as np
    from pripre.config import AppConfig, RuntimeConfig
    from pripre.domain import Trade
    from pripre.models.paths import Forecast
    from pripre.runtime import MatrixRuntime

    async def run() -> None:
        started, release = threading.Event(), threading.Event()
        raw, offset = [0], [0]
        config = AppConfig(runtime=RuntimeConfig(live_enabled=True))

        async def source_time() -> int:
            return 1_000_000_000 + raw[0] // 1000 + offset[0]

        class Engine:
            def predict(self, reference: Decimal, timestamp_us: int, volatility: float) -> Forecast:
                started.set()
                assert release.wait(2)
                return Forecast(
                    config.grid.build(reference, timestamp_us), np.zeros((21, 35)), "test", 64
                )

        runtime = MatrixRuntime(
            config, engine=Engine(), clock_sync=source_time, elapsed_ns=lambda: raw[0]
        )
        await runtime.resynchronize_clock()
        for second in range(61):
            raw[0] = second * 1_000_000_000
            runtime.ingest(
                Trade(
                    instrument="BTC_USDT",
                    source="binance",
                    sequence=second,
                    timestamp_us=1_000_000_000 + second * 1_000_000,
                    price=Decimal(10000),
                    quantity=Decimal(1),
                )
            )
        old_epoch = runtime.clock_epoch
        pending = asyncio.create_task(runtime.tick())
        assert await asyncio.to_thread(started.wait, 1)
        offset[0] = -8_000_000
        await runtime.resynchronize_clock()
        release.set()
        result = await pending
        assert runtime.clock_epoch > old_epoch and not runtime.trades
        assert result["status"] == "warming_up" and result["probabilities"] is None
        assert (
            runtime.for_delivery(
                {"status": "ready", "clock_epoch": old_epoch, "probabilities": [[0.5]]}
            )["probabilities"]
            is None
        )

    asyncio.run(run())


def test_periodic_clock_sync_runs_without_reconnecting_feed_and_stops_cleanly() -> None:
    import asyncio
    from collections.abc import AsyncIterator
    from decimal import Decimal

    from pripre.clock import steady_ns
    from pripre.config import AppConfig, RuntimeConfig
    from pripre.data.source import Capabilities, TradeBatch
    from pripre.domain import Trade
    from pripre.models.paths import Forecast
    from pripre.runtime import MatrixRuntime

    async def run() -> None:
        synchronized_twice = asyncio.Event()
        closed = asyncio.Event()
        calls = [0]
        started = steady_ns()

        async def source_time() -> int:
            calls[0] += 1
            if calls[0] >= 6:
                synchronized_twice.set()
            return 1_000_000_000 + (steady_ns() - started) // 1000

        class Source:
            id = "binance"
            capabilities = Capabilities(historical_trades=True, live_trades=True)

            async def history(self, symbol: str, start_us: int, end_us: int) -> TradeBatch:
                raise AssertionError("No historical requests in live test")

            async def stream(self, symbol: str) -> AsyncIterator[Trade]:
                try:
                    yield Trade(
                        instrument="BTC_USDT",
                        source="binance",
                        sequence=0,
                        timestamp_us=1_000_000_000 + (steady_ns() - started) // 1000,
                        price=Decimal(10000),
                        quantity=Decimal(1),
                    )
                    await asyncio.Event().wait()
                finally:
                    closed.set()

        class Engine:
            def predict(self, reference: Decimal, timestamp_us: int, volatility: float) -> Forecast:
                raise AssertionError("Warm-up cannot produce predictions")

        runtime = MatrixRuntime(
            AppConfig(
                runtime=RuntimeConfig(
                    live_enabled=True, clock_sync_seconds=5, clock_max_age_seconds=10
                )
            ),
            source=Source(),
            engine=Engine(),
            clock_sync=source_time,
        )
        await runtime.start()
        try:
            await asyncio.wait_for(synchronized_twice.wait(), timeout=8)
            # The last callback wakes the event before its sample is applied.
            for _ in range(10):
                if runtime.clock_syncs >= 2:
                    break
                await asyncio.sleep(0)
            assert runtime.clock_syncs >= 2 and runtime.reconnects == 0
        finally:
            await runtime.stop()
        assert closed.is_set() and not runtime._tasks

    asyncio.run(run())
