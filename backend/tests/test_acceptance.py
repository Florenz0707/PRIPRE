"""Regression checks for full-period coverage, artifact integrity and causal calibration."""

import hashlib
import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
from pripre.backtesting.dataset import load_examples
from pripre.backtesting.research import folds
from pripre.config import AppConfig, GridConfig, HistoryConfig
from pripre.data.history import archive_minutes, daily_sample, load_minutes
from pripre.models.calibration import ProbabilityCalibrator
from pripre.models.conditional import CalibratedEstimator, ConditionalEstimator
from pripre.models.paths import TradePath
from pydantic import ValidationError


class ArchiveReader:
    def __init__(self, payload: bytes, checksum: str) -> None:
        self.payload = payload
        self.checksum = checksum

    def get(self, url: str) -> bytes:
        return self.checksum.encode() if url.endswith(".CHECKSUM") else self.payload


def test_archive_requires_valid_checksum_before_parsing() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("sample.csv", "1767225600000000,100,102,99,101,1,0,1,5\n")
    payload = stream.getvalue()
    valid = ArchiveReader(payload, hashlib.sha256(payload).hexdigest())
    assert archive_minutes(valid, "https://example.invalid/sample.zip", Decimal("0.01")).shape == (
        1,
        5,
    )
    with pytest.raises(ValueError, match="checksum"):
        archive_minutes(
            ArchiveReader(payload, "0" * 64), "https://example.invalid/sample.zip", Decimal("0.01")
        )


def test_overlapping_minute_partitions_deduplicate_identical_facts_and_reject_conflicts(
    tmp_path: Path,
) -> None:
    config = AppConfig(history=HistoryConfig(data_dir=tmp_path))
    directory = tmp_path / "BTC_USDT" / "binance" / "minutes"
    directory.mkdir(parents=True)
    row = np.array([[1767225600000000, 10100, 10200, 9900, 5]], dtype=np.int64)
    np.savez_compressed(directory / "2026-01.npz", minutes=row)
    np.savez_compressed(directory / "2026-01-01.npz", minutes=row)
    assert len(load_minutes(config)) == 1
    conflicting = row.copy()
    conflicting[0, 1] = 10101
    np.savez_compressed(directory / "2026-01-01.npz", minutes=conflicting)
    with pytest.raises(ValueError, match="disagree"):
        load_minutes(config)


def test_backtest_date_filter_does_not_load_out_of_range_files(tmp_path: Path) -> None:
    config = AppConfig(
        history=HistoryConfig(data_dir=tmp_path, start=date(2026, 2, 1), end=date(2026, 2, 2))
    )
    directory = tmp_path / "BTC_USDT" / "binance" / "trades"
    directory.mkdir(parents=True)
    (directory / "2026-01-01.npz").write_bytes(b"outside requested range: must not be loaded")
    assert load_examples(config) == []


def test_rolling_tests_cover_early_and_late_dates_after_ten_day_warmup() -> None:
    days = [str(date(2026, 1, 1) + timedelta(days=index)) for index in range(297)]
    splits = folds(days)
    assert splits[0][1][0] == "2026-01-11"
    assert [day for _, testing in splits for day in testing] == days[10:]
    assert all(max(train) < min(test) for train, test in splits)


def test_long_forecast_requires_a_long_enough_historical_sample() -> None:
    with pytest.raises(ValidationError, match="warmup"):
        AppConfig(grid=GridConfig(horizon_seconds=600))
    start, end = daily_sample(date(2026, 10, 24), 3600)
    assert end - start == 3_600_000_000
    assert end <= 1767225600000000 + 297 * 86_400_000_000


def test_calibrator_cannot_use_labels_from_after_the_prediction_origin() -> None:
    path = TradePath(0, 15_000_000, 0.01, np.array([5_000_000]), np.array([0.0]))
    estimator = ConditionalEstimator([path], GridConfig(half_width=1, horizon_seconds=15), 64)
    calibrator = ProbabilityCalibrator.fit(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
    calibrated = CalibratedEstimator(estimator, calibrator, trained_through_us=30_000_000)
    with pytest.raises(ValueError, match="calibration data"):
        calibrated.predict(Decimal(1000), 20_000_000, 0.01)


def test_forecast_exposes_specific_model_revision_and_calibration_cutoff() -> None:
    path = TradePath(0, 15_000_000, 0.01, np.array([5_000_000]), np.array([0.0]))
    estimator = ConditionalEstimator([path], GridConfig(half_width=1, horizon_seconds=15), 64)
    calibrator = ProbabilityCalibrator.fit(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
    calibrated = CalibratedEstimator(
        estimator, calibrator, version="data-fingerprint-test", trained_through_us=16_000_000
    )
    forecast = calibrated.predict(Decimal(1000), 20_000_000, 0.01)
    assert forecast.version == "data-fingerprint-test"
    assert forecast.trained_through_us == 16_000_000


def test_future_history_is_rejected_before_contacting_provider() -> None:
    import time

    from pripre.data.binance import BinanceSource

    source = BinanceSource(AppConfig().instrument, ArchiveReader(b"not JSON", "unused"))
    now = time.time_ns() // 1000
    with pytest.raises(ValueError, match="future"):
        source.fetch_history("BTCUSDT", now, now + 1_000_000)


def test_provider_specific_symbol_rules_do_not_leak_into_shared_configuration() -> None:
    from pripre.config import SourceConfig
    from pripre.data.binance import require_symbol

    config = AppConfig(source=SourceConfig(provider="defillama", symbol="coingecko:bitcoin"))
    assert config.source.symbol == "coingecko:bitcoin"
    with pytest.raises(ValueError, match="Binance"):
        require_symbol(config.source.symbol)


def test_research_identity_tracks_data_and_model_parameters_not_deployment_location(
    tmp_path: Path,
) -> None:
    from pripre.config import RuntimeConfig
    from pripre.data.integrity import research_fingerprint

    config = AppConfig(history=HistoryConfig(data_dir=tmp_path))
    initial = research_fingerprint(config)
    enabled = config.model_copy(update={"runtime": RuntimeConfig(live_enabled=True)})
    assert research_fingerprint(enabled) == initial
    changed = config.model_copy(update={"runtime": RuntimeConfig(seed=7)})
    assert research_fingerprint(changed) != initial
    directory = tmp_path / "BTC_USDT" / "binance" / "trades"
    directory.mkdir(parents=True)
    (directory / "2026-01-01.npz").write_bytes(b"new facts")
    assert research_fingerprint(config) != initial


def test_market_clock_advances_monotonically_across_host_wall_clock_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pripre.clock import MonotonicUTC

    ticks = [1_000_000_000]
    clock = MonotonicUTC(anchor_us=100_000_000, monotonic_ns=lambda: ticks[0])
    monkeypatch.setattr("time.time_ns", lambda: 999_999_999_999_999_999)
    ticks[0] += 1_000_000_000
    assert clock() == 101_000_000
    clock.synchronize(200_000_000)
    ticks[0] += 500_000_000
    assert clock() == 200_500_000


def test_source_clock_uses_the_fastest_sample_and_accounts_for_elapsed_time() -> None:
    from pripre.clock import ClockSample, MonotonicUTC

    clock = MonotonicUTC(0, monotonic_ns=lambda: 3_000_000_000)
    uncertainty = clock.synchronize_samples(
        [
            ClockSample(100_000_000, 0, 20_000_000_000),
            ClockSample(200_000_000, 1_000_000_000, 1_200_000_000),
            ClockSample(201_000_000, 2_000_000_000, 2_600_000_000),
        ]
    )
    assert uncertainty == 100_000
    assert clock() == 201_900_000
    with pytest.raises(ValueError, match="low-latency"):
        clock.synchronize_samples([ClockSample(0, 0, 20_000_000_000)])
