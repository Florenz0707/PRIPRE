"""Past-only one-second returns; carry-forward is a feature, never a touch label."""

import numpy as np
from numpy.typing import NDArray

from pripre.domain import Trade


def trailing_volatility(trades: tuple[Trade, ...], timestamp_us: int, seconds: int = 60) -> float:
    history = [
        item
        for item in trades
        if timestamp_us - seconds * 1_000_000 <= item.timestamp_us < timestamp_us
    ]
    if len(history) < 2:
        return 0.0
    times = np.array([item.timestamp_us for item in history], dtype=np.int64)
    prices = np.array([float(item.price) for item in history], dtype=np.float64)
    boundaries = timestamp_us - np.arange(seconds, 0, -1, dtype=np.int64) * 1_000_000
    indices = np.searchsorted(times, boundaries, side="right") - 1
    valid = indices >= 0
    sampled: NDArray[np.float64] = prices[indices[valid]]
    return float(np.std(np.diff(np.log(sampled)))) if len(sampled) > 1 else 0.0
