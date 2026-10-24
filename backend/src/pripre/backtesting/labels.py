"""Exact labels from actual trades and independently verified coverage."""

from bisect import bisect_right
from collections.abc import Sequence

from pripre.domain import Coverage, PredictionGrid, Trade


def covers(coverage: Sequence[Coverage], start_us: int, end_us: int) -> bool:
    cursor = start_us
    for interval in sorted(coverage, key=lambda item: item.start_us):
        if interval.end_us <= cursor:
            continue
        if interval.start_us > cursor:
            return False
        cursor = max(cursor, interval.end_us)
        if cursor >= end_us:
            return True
    return False


def touch_labels(
    grid: PredictionGrid, trades: Sequence[Trade], coverage: Sequence[Coverage]
) -> list[list[bool | None]]:
    """Positive evidence survives gaps; an unobserved hit needs complete coverage."""
    labels: list[list[bool | None]] = [
        [
            False if covers(coverage, window.start_us, window.end_us) else None
            for window in grid.windows
        ]
        for _ in grid.prices
    ]
    lower = [interval.lower for interval in grid.prices]
    starts = [window.start_us for window in grid.windows]
    for trade in trades:
        row = bisect_right(lower, trade.price) - 1
        column = bisect_right(starts, trade.timestamp_us) - 1
        if (
            row >= 0
            and column >= 0
            and trade.price < grid.prices[row].upper
            and trade.timestamp_us < grid.windows[column].end_us
        ):
            labels[row][column] = True
    return labels
