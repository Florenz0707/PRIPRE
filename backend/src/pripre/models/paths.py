"""Empirical trade paths preserve observed jumps and intrawindow revisits."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

from pripre.config import GridConfig
from pripre.domain import PredictionGrid


@dataclass(frozen=True)
class TradePath:
    origin_us: int
    end_us: int
    volatility: float
    offsets_us: NDArray[np.int64]
    relative_prices: NDArray[np.float64]


@dataclass(frozen=True)
class Forecast:
    grid: PredictionGrid
    probabilities: NDArray[np.float64]
    model: str
    paths: int
    status: str = "ready"
    version: str = "empirical-path-v1"
    trained_through_us: int | None = None


class EmpiricalEstimator:
    """Unconditional historical path baseline with deterministic Monte Carlo."""

    name = "empirical-baseline"
    version = "empirical-path-v1"

    def __init__(
        self, paths: Sequence[TradePath], grid: GridConfig, count: int = 512, seed: int = 2026
    ) -> None:
        if not paths:
            raise ValueError("no historical paths available")
        self.paths = tuple(paths)
        self.config = grid
        self.count = count
        self.seed = seed

    def select(self, volatility: float) -> NDArray[np.int64]:
        return np.arange(len(self.paths), dtype=np.int64)

    def predict(self, reference: Decimal, timestamp_us: int, volatility: float) -> Forecast:
        grid = self.config.build(reference, timestamp_us)
        candidates = self.select(volatility)
        if any(self.paths[int(index)].end_us > timestamp_us for index in candidates):
            raise ValueError("historical path reaches beyond prediction origin")
        rng = np.random.default_rng(self.seed)
        selected = rng.choice(candidates, size=self.count, replace=True)
        indices, weights = np.unique(selected, return_counts=True)
        rows, cols = self.config.rows, self.config.columns
        counts = np.zeros(rows * cols, dtype=np.float64)
        lower = float(grid.prices[0].lower)
        step = float(self.config.price_step)
        for index, weight in zip(indices, weights, strict=True):
            path = self.paths[int(index)]
            prices = float(reference) * (1 + path.relative_prices)
            price_rows = np.floor((prices - lower) / step).astype(np.int64)
            columns = (path.offsets_us - self.config.first_window_seconds * 1_000_000) // (
                self.config.window_seconds * 1_000_000
            )
            valid = (price_rows >= 0) & (price_rows < rows) & (columns >= 0) & (columns < cols)
            touched = np.unique(price_rows[valid] * cols + columns[valid])
            counts[touched] += int(weight)
        return Forecast(
            grid,
            counts.reshape(rows, cols) / self.count,
            self.name,
            self.count,
            version=self.version,
            trained_through_us=max(path.end_us for path in self.paths),
        )
