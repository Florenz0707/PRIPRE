"""Immutable market facts and prediction geometry, independent of providers."""

from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

PositivePrice = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Timestamp = Annotated[int, Field(ge=0, strict=True)]


class Instrument(BaseModel):
    """A tradable instrument; new assets require configuration, not branching."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(min_length=1, pattern=r"^[A-Z0-9_-]+$")
    base: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    tick_size: PositivePrice


class Trade(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    instrument: str
    source: str
    sequence: int = Field(ge=0)
    timestamp_us: Timestamp
    price: PositivePrice
    quantity: Decimal = Field(ge=0, allow_inf_nan=False)


class Coverage(BaseModel):
    """Verified complete [start, end) trade data; no trades is valid coverage."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    start_us: Timestamp
    end_us: Timestamp

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_us <= self.start_us:
            raise ValueError("coverage end must follow start")
        return self


class PriceInterval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    lower: Decimal
    upper: Decimal


class TimeWindow(Coverage):
    """A future observation window; both axes use half-open intervals."""


class PredictionGrid(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    timestamp_us: Timestamp
    reference_price: PositivePrice
    prices: tuple[PriceInterval, ...]
    windows: tuple[TimeWindow, ...]
