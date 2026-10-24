"""Event geometry, coverage and source substitution are public contracts."""

from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
from pripre.backtesting.labels import touch_labels
from pripre.config import AppConfig, GridConfig, load_config
from pripre.data.source import Capabilities, SourceRegistry, TradeBatch
from pripre.domain import Coverage, Instrument, Trade
from pydantic import ValidationError


def trade(price: str, seconds: int) -> Trade:
    return Trade(
        instrument="BTC_USDT",
        source="test",
        sequence=seconds,
        timestamp_us=seconds * 1_000_000,
        price=Decimal(price),
        quantity=Decimal(1),
    )


def test_defaults_and_toml_agree() -> None:
    config = load_config(Path("config/default.toml"))
    assert config == AppConfig()
    grid = config.grid.build(Decimal("10000"), 0)
    assert len(grid.prices) == 21 and len(grid.windows) == 35
    assert grid.prices[10].lower == Decimal("9950")
    assert grid.windows[0].start_us == 5_000_000
    assert grid.windows[-1].end_us == 180_000_000


@pytest.mark.parametrize(
    "settings",
    [
        {"price_step": "NaN"},
        {"price_step": 0},
        {"half_width": -1},
        {"horizon_seconds": 181},
        {"first_window_seconds": 180},
        {"unknown": 1},
    ],
)
def test_invalid_grid_is_rejected(settings: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GridConfig.model_validate(settings)


def test_interval_edges_and_jumps_do_not_create_interpolated_hits() -> None:
    grid = GridConfig(half_width=1, horizon_seconds=15).build(Decimal("1000"), 0)
    labels = touch_labels(
        grid,
        [trade("850", 5), trade("1050", 9), trade("950", 10), trade("950", 15)],
        [Coverage(start_us=5_000_000, end_us=15_000_000)],
    )
    assert labels == [[True, False], [False, True], [True, False]]
    assert sum(value is True for value in (row[0] for row in labels)) == 2


def test_missing_data_is_unknown_but_observed_hit_is_proven() -> None:
    grid = GridConfig(half_width=1, horizon_seconds=10).build(Decimal("1000"), 0)
    assert touch_labels(grid, [trade("1000", 6)], []) == [[None], [True], [None]]
    assert touch_labels(
        grid,
        [],
        [
            Coverage(start_us=5_000_000, end_us=7_000_000),
            Coverage(start_us=7_000_000, end_us=10_000_000),
        ],
    ) == [[False], [False], [False]]


class AlternativeSource:
    id = "alternative"
    capabilities = Capabilities(historical_trades=True, live_trades=False)

    async def history(self, symbol: str, start_us: int, end_us: int) -> TradeBatch:
        return TradeBatch((), (Coverage(start_us=start_us, end_us=end_us),))

    async def stream(self, symbol: str) -> AsyncIterator[Trade]:
        raise NotImplementedError
        yield  # pragma: no cover


def test_asset_and_provider_can_be_added_without_changing_consumers() -> None:
    registry = SourceRegistry()
    gold = Instrument(id="GOLD_USD", base="XAU", quote="USD", tick_size=Decimal("0.01"))
    source = AlternativeSource()
    registry.register(source, gold, "XAUUSD")
    assert registry.resolve("GOLD_USD", "alternative", live=False) == (source, "XAUUSD")
    with pytest.raises(ValueError, match="trade-level"):
        registry.resolve("GOLD_USD", "alternative", live=True)
    with pytest.raises(ValueError, match="unsupported"):
        registry.resolve("OIL_USD", "alternative", live=False)
