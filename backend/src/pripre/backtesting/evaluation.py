"""Date-block uncertainty and descriptive stage analysis, never model features."""

from collections import defaultdict

import numpy as np
from numpy.typing import NDArray

from pripre.backtesting.archive import OriginRecord
from pripre.backtesting.metrics import day_ratio_bootstrap, metrics
from pripre.config import AppConfig


def grouped_metrics(
    p: NDArray[np.float64], y: NDArray[np.float64], dates: list[str]
) -> dict[str, object]:
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for i, day in enumerate(dates):
        known = np.isfinite(y[i])
        if np.any(known):
            sums[day] += float(np.sum((p[i][known] - y[i][known]) ** 2))
            counts[day] += int(known.sum())
    result = metrics(p, y)
    result.update(
        origins=len(dates),
        dates=len(sums),
        unknown_ratio=float(np.mean(~np.isfinite(y))) if y.size else None,
        day_block_brier_95=day_ratio_bootstrap(list(sums.values()), list(counts.values())),
    )
    return result


def summarize(
    p: NDArray[np.float64], y: NDArray[np.float64], records: list[OriginRecord], config: AppConfig
) -> dict[str, object]:
    dates = [item.day for item in records]
    summary = grouped_metrics(p, y, dates)
    daily = []
    for day in sorted(set(dates)):
        selected = np.array([value == day for value in dates])
        daily.append(
            {"date": day, **grouped_metrics(p[selected], y[selected], [day] * int(selected.sum()))}
        )
    by_distance = []
    for distance in range(config.grid.half_width + 1):
        indices = [
            i for i in range(config.grid.rows) if abs(i - config.grid.half_width) == distance
        ]
        by_distance.append(
            {
                "distance_steps": distance,
                **grouped_metrics(p[:, indices, :], y[:, indices, :], dates),
            }
        )
    groups: dict[str, list[dict[str, object]]] = {}
    for name, values in {
        "by_regime": [r.regime for r in records],
        "by_phase": [r.phase for r in records],
        "by_anomaly": [
            "out_of_distribution" if r.out_of_distribution else "in_distribution" for r in records
        ],
        "by_event": ["extreme_day" if r.extreme_day else "ordinary_day" for r in records],
    }.items():
        groups[name] = []
        for value in sorted(set(values)):
            mask = np.array([item == value for item in values])
            groups[name].append(
                {
                    "regime": value,
                    **grouped_metrics(
                        p[mask], y[mask], [d for d, keep in zip(dates, mask, strict=True) if keep]
                    ),
                }
            )
    live_mask = np.array([not r.out_of_distribution for r in records], dtype=bool)
    return {
        "summary": summary,
        "by_distance": by_distance,
        "by_window": [
            {
                "start_seconds": config.grid.first_window_seconds + i * config.grid.window_seconds,
                **grouped_metrics(p[:, :, i], y[:, :, i], dates),
            }
            for i in range(config.grid.columns)
        ],
        **groups,
        "daily": daily,
        "day_block_brier_95": summary["day_block_brier_95"],
        "live_policy": {
            "suppressed_origins": int((~live_mask).sum()),
            "suppression_ratio": float(np.mean(~live_mask)) if len(records) else None,
            "published": grouped_metrics(
                p[live_mask], y[live_mask], [r.day for r in records if not r.out_of_distribution]
            ),
            "policy": "Suppress OOD output; research above retains all origins.",
        },
    }
