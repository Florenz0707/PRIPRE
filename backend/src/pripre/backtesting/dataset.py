"""Replay origins and training paths from verified, sampled trade intervals."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from pripre.backtesting.labels import covers, touch_labels
from pripre.config import AppConfig
from pripre.data.store import load_batch
from pripre.domain import PredictionGrid
from pripre.features.volatility import trailing_volatility
from pripre.models.paths import TradePath


@dataclass(frozen=True)
class Example:
    day: str
    grid: PredictionGrid
    volatility: float
    path: TradePath
    labels: NDArray[np.float64]


def load_examples(config: AppConfig) -> list[Example]:
    directory = config.history.data_dir / config.instrument.id / config.source.provider / "trades"
    examples: list[Example] = []
    for file in sorted(directory.glob("*.npz")):
        examples.extend(examples_from_file(file, config))
    return examples


def examples_from_file(file: Path, config: AppConfig) -> list[Example]:
    batch = load_batch(file, config.instrument, config.source.provider)
    if not batch.trades or not batch.coverage:
        return []
    start = batch.coverage[0].start_us
    end = batch.coverage[-1].end_us
    times = np.array([trade.timestamp_us for trade in batch.trades], dtype=np.int64)
    prices = np.array([float(trade.price) for trade in batch.trades], dtype=np.float64)
    result: list[Example] = []
    horizon = config.grid.horizon_seconds * 1_000_000
    for origin in range(start + 60_000_000, end - horizon + 1, 60_000_000):
        if not covers(batch.coverage, origin - 60_000_000, origin + horizon):
            continue
        index = int(np.searchsorted(times, origin, side="left")) - 1
        if index < 0:
            continue
        reference = batch.trades[index].price
        volatility = trailing_volatility(batch.trades, origin)
        grid = config.grid.build(reference, origin)
        future = (times >= origin) & (times < origin + horizon)
        path = TradePath(
            origin,
            origin + horizon,
            volatility,
            times[future] - origin,
            prices[future] / float(reference) - 1,
        )
        labels = np.array(touch_labels(grid, batch.trades, batch.coverage), dtype=np.float64)
        result.append(Example(file.stem, grid, volatility, path, labels))
    return result
