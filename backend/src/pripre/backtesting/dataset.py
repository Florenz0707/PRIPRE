"""Replay origins and training paths from verified, sampled trade intervals."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
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


@dataclass
class DatasetAudit:
    partitions: int = 0
    candidates: int = 0
    accepted: int = 0
    excluded: Counter[str] = field(default_factory=Counter)

    def report(self) -> dict[str, object]:
        return {
            "partitions": self.partitions,
            "candidate_origins": self.candidates,
            "accepted_origins": self.accepted,
            "excluded_origins": sum(self.excluded.values()),
            "excluded_by_reason": dict(self.excluded),
            "unknown_policy": "Incomplete origins are counted and excluded, never negative.",
        }


def load_examples(config: AppConfig, audit: DatasetAudit | None = None) -> list[Example]:
    directory = config.history.data_dir / config.instrument.id / config.source.provider / "trades"
    examples: list[Example] = []
    for file in sorted(directory.glob("*.npz")):
        if not config.history.start <= date.fromisoformat(file.stem) <= config.history.end_date():
            continue
        examples.extend(examples_from_file(file, config, audit))
    return examples


def examples_from_file(
    file: Path, config: AppConfig, audit: DatasetAudit | None = None
) -> list[Example]:
    audit = audit if audit is not None else DatasetAudit()
    audit.partitions += 1
    batch = load_batch(file, config.instrument, config.source.provider)
    if not batch.coverage:
        raise ValueError(f"partition has no verifiable coverage: {file.name}")
    start = batch.coverage[0].start_us
    end = batch.coverage[-1].end_us
    times = np.array([trade.timestamp_us for trade in batch.trades], dtype=np.int64)
    prices = np.array([float(trade.price) for trade in batch.trades], dtype=np.float64)
    result: list[Example] = []
    horizon = config.grid.horizon_seconds * 1_000_000
    for origin in range(
        start + 60_000_000, end - horizon + 1, config.research.origin_stride_seconds * 1_000_000
    ):
        audit.candidates += 1
        if not covers(batch.coverage, origin - 60_000_000, origin + horizon):
            audit.excluded["incomplete_feature_or_label_coverage"] += 1
            continue
        index = int(np.searchsorted(times, origin, side="left")) - 1
        if index < 0:
            audit.excluded["no_reference_trade"] += 1
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
        audit.accepted += 1
    return result
