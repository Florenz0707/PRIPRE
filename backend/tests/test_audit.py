"""Excluded origins and invalid live states remain visible in the audit trail."""

import asyncio
from decimal import Decimal
from pathlib import Path

from pripre.backtesting.dataset import DatasetAudit, examples_from_file
from pripre.config import AppConfig, ResearchConfig
from pripre.data.source import TradeBatch
from pripre.data.store import save_batch
from pripre.domain import Coverage, Trade
from pripre.journal import PredictionJournal
from pripre.runtime import MatrixRuntime


def test_missing_windows_are_counted_before_filtering(tmp_path: Path) -> None:
    config = AppConfig()
    trade = Trade(
        instrument="BTC_USDT",
        source="binance",
        sequence=1,
        timestamp_us=0,
        price=Decimal(10000),
        quantity=Decimal(1),
    )
    batch = TradeBatch(
        (trade,),
        (
            Coverage(start_us=0, end_us=100_000_000),
            Coverage(start_us=150_000_000, end_us=420_000_000),
        ),
    )
    file = tmp_path / "2026-01-01.npz"
    save_batch(file, batch, config.instrument, "binance")
    audit = DatasetAudit()
    examples = examples_from_file(file, config, audit)
    assert len(examples) == 1
    assert audit.candidates == 4 and audit.accepted == 1
    assert audit.excluded == {"incomplete_feature_or_label_coverage": 3}
    assert examples[0].grid.timestamp_us == 240_000_000


def test_empty_complete_partition_is_not_silently_lost(tmp_path: Path) -> None:
    config = AppConfig(research=ResearchConfig(origin_stride_seconds=1))
    file = tmp_path / "2026-01-01.npz"
    save_batch(
        file,
        TradeBatch((), (Coverage(start_us=0, end_us=420_000_000),)),
        config.instrument,
        "binance",
    )
    audit = DatasetAudit()
    assert examples_from_file(file, config, audit) == []
    assert audit.candidates == 181
    assert audit.excluded == {"no_reference_trade": 181}


def test_live_invalid_states_are_persisted_and_retention_is_bounded(tmp_path: Path) -> None:
    async def run() -> None:
        now = [1_000_000]
        journal = PredictionJournal(tmp_path / "audit.sqlite", retain=2)
        runtime = MatrixRuntime(AppConfig(), journal=journal, clock=lambda: now[0])
        for second in range(1, 4):
            now[0] = second * 1_000_000
            await runtime.tick()
        assert journal.read(1_000_000) is None
        record = journal.read(3_000_000)
        assert record is not None and record["status"] == "disabled"
        assert record["probabilities"] is None and "parameters" in record

    asyncio.run(run())
