"""Descriptive full-period market context; not used to infer touch labels."""

from collections import defaultdict
from datetime import UTC, datetime

import numpy as np

from pripre.config import AppConfig


def market_context(config: AppConfig) -> list[dict[str, object]]:
    directory = config.history.data_dir / config.instrument.id / config.source.provider / "minutes"
    grouped: dict[int, list[list[int]]] = defaultdict(list)
    for file in sorted(directory.glob("*.npz")):
        with np.load(file, allow_pickle=False) as archive:
            for row in archive["minutes"]:
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
                "minutes": len(rows),
                "trades": int(np.sum(array[:, 4])),
            }
        )
    return result
