"""A volatility-conditioned path adapter and its independently fitted calibrator."""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

from pripre.config import GridConfig
from pripre.models.calibration import ProbabilityCalibrator
from pripre.models.paths import EmpiricalEstimator, Forecast, TradePath


class ConditionalEstimator(EmpiricalEstimator):
    name = "conditional-raw"
    version = "conditional-path-v1"

    def __init__(
        self,
        paths: Sequence[TradePath],
        grid: GridConfig,
        count: int = 512,
        seed: int = 2026,
        *,
        candidate_fraction: float = 1 / 3,
        minimum_candidates: int = 16,
        mapping: str = "relative",
    ) -> None:
        super().__init__(paths, grid, count, seed)
        if not 0 < candidate_fraction <= 1 or minimum_candidates < 1:
            raise ValueError("invalid candidate selection parameters")
        if mapping not in ("relative", "absolute"):
            raise ValueError("unknown price mapping")
        self.candidate_fraction = candidate_fraction
        self.minimum_candidates = minimum_candidates
        self.mapping = mapping

    def map_prices(self, path: TradePath, reference: Decimal) -> NDArray[np.float64]:
        if self.mapping == "absolute":
            return float(reference) + path.relative_prices * path.origin_price
        return super().map_prices(path, reference)

    def select(self, volatility: float) -> NDArray[np.int64]:
        historical = np.array([path.volatility for path in self.paths], dtype=np.float64)
        distances = np.abs(np.log(np.maximum(historical, 1e-9) / max(volatility, 1e-9)))
        count = min(
            len(historical),
            max(self.minimum_candidates, int(len(historical) * self.candidate_fraction)),
        )
        return np.asarray(np.argsort(distances, kind="stable")[:count], dtype=np.int64)

    def predict(self, reference: Decimal, timestamp_us: int, volatility: float) -> Forecast:
        maximum = max(path.volatility for path in self.paths)
        if volatility > max(maximum * 3, 1e-8):
            # No extrapolated confidence: callers receive a status and can suppress the matrix.
            base = super().predict(reference, timestamp_us, volatility)
            return replace(base, status="out_of_distribution")
        return super().predict(reference, timestamp_us, volatility)


class CalibratedEstimator:
    name = "conditional-calibrated"

    def __init__(
        self,
        estimator: ConditionalEstimator,
        calibrator: ProbabilityCalibrator,
        version: str = "calibrated-path-v1",
        trained_through_us: int | None = None,
    ) -> None:
        self.estimator = estimator
        self.calibrator = calibrator
        self.version = version
        self.trained_through_us = trained_through_us

    def predict(self, reference: Decimal, timestamp_us: int, volatility: float) -> Forecast:
        if self.trained_through_us is not None and self.trained_through_us > timestamp_us:
            raise ValueError("calibration data reaches beyond prediction origin")
        forecast = self.estimator.predict(reference, timestamp_us, volatility)
        return replace(
            forecast,
            model=self.name,
            probabilities=self.calibrator.apply(forecast.probabilities),
            version=self.version,
            trained_through_us=self.trained_through_us,
        )
