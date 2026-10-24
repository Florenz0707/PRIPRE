"""Validated TOML configuration with explicit defaults and bounded workloads."""

import tomllib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pripre.domain import Instrument, PredictionGrid, PriceInterval, TimeWindow


class GridConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    price_step: Decimal = Field(default=Decimal("100"), gt=0, allow_inf_nan=False)
    half_width: int = Field(default=10, ge=1, le=30)
    first_window_seconds: int = Field(default=5, ge=1)
    window_seconds: int = Field(default=5, ge=1)
    horizon_seconds: int = Field(default=180, ge=2, le=600)

    @model_validator(mode="after")
    def aligned(self) -> Self:
        duration = self.horizon_seconds - self.first_window_seconds
        if duration <= 0 or duration % self.window_seconds:
            raise ValueError("horizon minus first window must be a positive multiple of window")
        if self.rows * self.columns > 5000:
            raise ValueError("grid must contain at most 5000 cells")
        return self

    @property
    def rows(self) -> int:
        return 2 * self.half_width + 1

    @property
    def columns(self) -> int:
        return (self.horizon_seconds - self.first_window_seconds) // self.window_seconds

    def build(self, reference: Decimal, timestamp_us: int) -> PredictionGrid:
        """Freeze the current price centre and all future window boundaries."""
        lower = reference - (Decimal(self.half_width) + Decimal("0.5")) * self.price_step
        if lower <= 0:
            raise ValueError("price grid extends below zero; reduce step or half width")
        return PredictionGrid(
            timestamp_us=timestamp_us,
            reference_price=reference,
            prices=tuple(
                PriceInterval(
                    lower=lower + index * self.price_step,
                    upper=lower + (index + 1) * self.price_step,
                )
                for index in range(self.rows)
            ),
            windows=tuple(
                TimeWindow(
                    start_us=timestamp_us + start * 1_000_000,
                    end_us=timestamp_us + (start + self.window_seconds) * 1_000_000,
                )
                for start in range(
                    self.first_window_seconds, self.horizon_seconds, self.window_seconds
                )
            ),
        )


class SourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    provider: str = "binance"
    symbol: str = Field(default="BTCUSDT", pattern=r"^[A-Z0-9]+$")


class HistoryConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    start: date = date(2026, 1, 1)
    end: date | None = None
    sample_seconds: int = Field(default=420, ge=240, le=3600)
    max_requests: int = Field(default=5000, ge=1, le=100000)
    max_download_mb: int = Field(default=256, ge=1, le=10000)
    data_dir: Path = Path("data")

    @model_validator(mode="after")
    def dates(self) -> Self:
        if self.end is not None and self.end < self.start:
            raise ValueError("history end precedes start")
        return self

    def end_date(self) -> date:
        """An omitted end resolves at execution time, in UTC market-data time."""
        return self.end or datetime.now(UTC).date()


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    update_seconds: int = Field(default=1, ge=1, le=1)
    max_clients: int = Field(default=50, ge=1, le=50)
    stale_seconds: int = Field(default=5, ge=2, le=60)
    paths: int = Field(default=512, ge=64, le=4096)
    seed: int = Field(default=2026, ge=0)
    live_enabled: bool = False


class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    instrument: Instrument = Instrument(
        id="BTC_USDT", base="BTC", quote="USDT", tick_size=Decimal("0.01")
    )
    source: SourceConfig = SourceConfig()
    grid: GridConfig = GridConfig()
    history: HistoryConfig = HistoryConfig()
    runtime: RuntimeConfig = RuntimeConfig()

    @model_validator(mode="after")
    def tick_alignment(self) -> Self:
        if self.grid.price_step % self.instrument.tick_size:
            raise ValueError("price step must be a multiple of the instrument tick size")
        return self


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        return AppConfig()
    with path.open("rb") as stream:
        return AppConfig.model_validate(tomllib.load(stream))
