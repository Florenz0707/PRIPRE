"""Calibration metrics with explicit denominators and day-block uncertainty."""

import numpy as np
from numpy.typing import NDArray


def metrics(probabilities: NDArray[np.float64], labels: NDArray[np.float64]) -> dict[str, object]:
    known = np.isfinite(labels)
    p, y = probabilities[known], labels[known]
    if len(p) == 0:
        return {"count": 0, "unknown": int(labels.size), "brier": None, "reliability": []}
    reliability: list[dict[str, object]] = []
    for index in range(10):
        selected = (p >= index / 10) & ((p < (index + 1) / 10) if index < 9 else (p <= 1))
        count = int(np.count_nonzero(selected))
        reliability.append(
            {
                "lower": index / 10,
                "upper": (index + 1) / 10,
                "count": count,
                "predicted": float(np.mean(p[selected])) if count else None,
                "observed": float(np.mean(y[selected])) if count else None,
            }
        )
    brier = float(np.mean((p - y) ** 2))
    zero_brier = float(np.mean(y**2))
    return {
        "count": len(p),
        "unknown": int(labels.size - len(p)),
        "brier": brier,
        "frequency": float(np.mean(y)),
        "mean_probability": float(np.mean(p)),
        "zero_forecast_brier": zero_brier,
        "skill_vs_zero": 1 - brier / zero_brier if zero_brier else None,
        "reliability": reliability,
    }


def day_bootstrap(day_scores: list[float], seed: int = 2026) -> list[float] | None:
    if len(day_scores) < 2:
        return None
    rng = np.random.default_rng(seed)
    values = np.array(day_scores)
    means = np.mean(rng.choice(values, size=(1000, len(values)), replace=True), axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return [float(low), float(high)]
