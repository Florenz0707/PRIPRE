"""Training-only volatility bins with an explicit sparse-state frequency fallback."""

from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

from pripre.config import GridConfig
from pripre.models.paths import Forecast


class FrequencyEstimator:
    name = "frequency-baseline"
    version = "state-frequency-v1"

    def __init__(
        self,
        labels: NDArray[np.float64],
        volatility: list[float],
        grid: GridConfig,
        trained_through_us: int,
        minimum: int = 16,
    ) -> None:
        self.labels = labels
        self.volatility = np.array(volatility)
        self.thresholds = np.quantile(self.volatility, [0.25, 0.75])
        self.grid = grid
        self.trained_through_us = trained_through_us
        self.minimum = minimum

    def predict(self, reference: Decimal, timestamp_us: int, volatility: float) -> Forecast:
        if timestamp_us < self.trained_through_us:
            raise ValueError("frequency baseline training reaches beyond prediction")
        group = np.searchsorted(self.thresholds, volatility, side="right")
        mask = np.searchsorted(self.thresholds, self.volatility, side="right") == group
        labels = self.labels[mask] if mask.sum() >= self.minimum else self.labels
        known = np.isfinite(labels)
        # Unknown cells fall back to pooled evidence; cells with no evidence cannot be estimated.
        total = known.sum(axis=0)
        pooled_total = np.isfinite(self.labels).sum(axis=0)
        pooled = np.divide(
            np.nansum(self.labels, axis=0),
            pooled_total,
            out=np.full(total.shape, np.nan),
            where=pooled_total > 0,
        )
        probabilities = np.divide(
            np.nansum(labels, axis=0), total, out=pooled.copy(), where=total > 0
        )
        if np.any(~np.isfinite(probabilities)):
            raise ValueError("frequency baseline has no label evidence")
        return Forecast(
            self.grid.build(reference, timestamp_us),
            probabilities,
            self.name,
            len(labels),
            version=self.version,
            trained_through_us=self.trained_through_us,
        )
