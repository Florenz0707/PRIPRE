"""Monotone probability calibration fitted only on a separate chronological set."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class ProbabilityCalibrator:
    predicted: NDArray[np.float64]
    observed: NDArray[np.float64]

    @classmethod
    def fit(
        cls,
        probabilities: NDArray[np.float64],
        labels: NDArray[np.float64],
        bins: int = 20,
        prior_weight: float = 20,
    ) -> "ProbabilityCalibrator":
        valid = np.isfinite(labels)
        p, y = probabilities[valid].ravel(), labels[valid].ravel()
        if not len(p) or np.any((p < 0) | (p > 1)):
            raise ValueError("calibration requires known labels and valid probabilities")
        x: list[float] = []
        totals: list[float] = []
        weights: list[float] = []
        assignments = np.minimum((p * bins).astype(np.int64), bins - 1)
        for index in range(bins):
            selected = assignments == index
            n = int(np.count_nonzero(selected))
            if not n:
                continue
            mean = float(np.mean(p[selected]))
            x.append(mean)
            totals.append(float(np.sum(y[selected])) + prior_weight * mean)
            weights.append(n + prior_weight)
        # Pool adjacent violators; keep a value for each original probability bin.
        blocks: list[tuple[int, int, float, float]] = []
        for i, (total, weight) in enumerate(zip(totals, weights, strict=True)):
            blocks.append((i, i + 1, total, weight))
            while len(blocks) > 1 and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]:
                right = blocks.pop()
                left = blocks.pop()
                blocks.append((left[0], right[1], left[2] + right[2], left[3] + right[3]))
        calibrated = np.empty(len(x), dtype=np.float64)
        for start, end, total, weight in blocks:
            calibrated[start:end] = total / weight
        return cls(np.array(x, dtype=np.float64), calibrated)

    def apply(self, probabilities: NDArray[np.float64]) -> NDArray[np.float64]:
        return np.asarray(np.interp(probabilities, self.predicted, self.observed), dtype=np.float64)
