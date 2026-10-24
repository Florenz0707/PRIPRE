"""Descriptive full-period market context; not used to infer touch labels."""

from collections import defaultdict
from datetime import UTC, datetime

import numpy as np

from pripre.config import AppConfig
from pripre.data.history import load_minutes


def market_context(config: AppConfig) -> list[dict[str, object]]:
    grouped: dict[int, list[list[int]]] = defaultdict(list)
    for row in load_minutes(config):
        grouped[int(row[0]) // 86_400_000_000].append([int(value) for value in row])
    result: list[dict[str, object]] = []
    tick = float(config.instrument.tick_size)
    for day, rows in sorted(grouped.items()):
        array = np.array(sorted(rows), dtype=np.int64)
        close = array[:, 1] * tick
        result.append(
            {
                "date": datetime.fromtimestamp(day * 86400, UTC).date().isoformat(),
                "close": float(close[-1]),
                "high": float(np.max(array[:, 2]) * tick),
                "low": float(np.min(array[:, 3]) * tick),
                "return": float(close[-1] / close[0] - 1),
                "volatility": float(np.std(np.diff(np.log(close)))) if len(close) > 1 else 0,
                "efficiency": float(
                    abs(np.log(close[-1] / close[0]))
                    / max(float(np.sum(np.abs(np.diff(np.log(close))))), 1e-12)
                ),
                "minutes": len(rows),
                "trades": int(np.sum(array[:, 4])),
            }
        )
    return result
