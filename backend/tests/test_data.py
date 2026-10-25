"""Bounded acquisition, pagination and exact local replay without network calls."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from pripre.config import AppConfig
from pripre.data.binance import BinanceSource, timestamp_us
from pripre.data.history import daily_sample, minute_partitions, parse_minutes
from pripre.data.http import BudgetExceeded, DownloadBudget, PublicHTTP
from pripre.data.source import TradeBatch
from pripre.data.store import load_batch, save_batch
from pripre.domain import Coverage, Trade


class Pages:
    def __init__(self, pages: list[list[dict[str, object]]]) -> None:
        self.pages = iter(pages)
        self.urls: list[str] = []

    def get(self, url: str) -> bytes:
        self.urls.append(url)
        return json.dumps(next(self.pages)).encode()


def record(sequence: int, time: int) -> dict[str, object]:
    return {"a": sequence, "T": time, "p": "100.01", "q": "0.00000001"}


def test_full_page_is_followed_by_id_and_end_is_excluded() -> None:
    start = 1_767_225_600_000_000
    first = [record(i, start + i) for i in range(1000)]
    reader = Pages([first, [record(1000, start + 1000), record(1001, start + 2000)]])
    batch = BinanceSource(AppConfig().instrument, reader).fetch_history(
        "BTCUSDT", start, start + 2000
    )
    assert len(batch.trades) == 1001
    assert parse_qs(urlsplit(reader.urls[1]).query)["fromId"] == ["1000"]
    assert batch.coverage == (Coverage(start_us=start, end_us=start + 2000),)


def test_sequence_gap_is_not_declared_complete() -> None:
    start = 1_767_225_600_000_000
    source = BinanceSource(
        AppConfig().instrument, Pages([[record(1, start), record(3, start + 1)]])
    )
    with pytest.raises(ValueError, match="sequence gap"):
        source.fetch_history("BTCUSDT", start, start + 1000)


def test_empty_successful_window_is_complete_not_missing() -> None:
    start = 1_767_225_600_000_000
    source = BinanceSource(AppConfig().instrument, Pages([[]]))
    assert source.fetch_history("BTCUSDT", start, start + 1000).coverage


def test_budget_fails_before_any_network_call() -> None:
    http = PublicHTTP(DownloadBudget(max_requests=1, max_bytes=100, requests=1))
    with pytest.raises(BudgetExceeded):
        http.get("https://must-not-be-requested.invalid")


def test_store_round_trip_preserves_microseconds_decimal_and_coverage(tmp_path: Path) -> None:
    config = AppConfig()
    trade = Trade(
        instrument=config.instrument.id,
        source="binance",
        sequence=9,
        timestamp_us=1_767_225_600_000_123,
        price=Decimal("87648.21"),
        quantity=Decimal("0.00000001"),
    )
    batch = TradeBatch(
        (trade,), (Coverage(start_us=trade.timestamp_us, end_us=trade.timestamp_us + 1000),)
    )
    path = tmp_path / "sample.npz"
    save_batch(path, batch, config.instrument, "binance")
    assert load_batch(path, config.instrument, "binance") == batch
    with pytest.raises(ValueError, match="identity"):
        load_batch(path, config.instrument, "other")


def test_microsecond_archive_and_millisecond_rest_are_consistent() -> None:
    assert timestamp_us(1767225600000) == timestamp_us(1767225600000000)
    array = parse_minutes(
        [["1767225600000000", "100", "102", "99", "101", "1", "0", "1", "5"]], Decimal("0.01")
    )
    assert array.tolist() == [[1767225600000000, 10100, 10200, 9900, 5]]


def test_sample_schedule_is_deterministic_and_stays_inside_day() -> None:
    start, end = daily_sample(date(2026, 1, 1), 420)
    assert end - start == 420_000_000
    assert daily_sample(date(2026, 1, 1), 420) == (start, end)
    assert minute_partitions(date(2026, 1, 1), date(2026, 2, 2), date(2026, 2, 3)) == [
        ("monthly", date(2026, 1, 1), date(2026, 2, 1)),
        ("daily", date(2026, 2, 1), date(2026, 2, 2)),
        ("daily", date(2026, 2, 2), date(2026, 2, 3)),
    ]


def test_clock_http_timeout_bounds_the_underlying_blocking_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import NoReturn
    from urllib.request import Request

    from pripre.data.http import DownloadError

    timeouts: list[float] = []

    def timeout_read(_request: Request, *, timeout: float) -> NoReturn:
        timeouts.append(timeout)
        raise TimeoutError("simulated unavailable clock endpoint")

    monkeypatch.setattr("urllib.request.urlopen", timeout_read)
    reader = PublicHTTP(DownloadBudget(2, 1024), min_interval=0, timeout=2)
    for _ in range(2):
        with pytest.raises(DownloadError):
            reader.get("https://example.invalid/time")
    assert timeouts == [2, 2] and reader.budget.requests == 2
