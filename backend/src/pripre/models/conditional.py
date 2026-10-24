"""A volatility-conditioned path adapter and its independently fitted calibrator."""

from dataclasses import replace
from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

from pripre.models.calibration import ProbabilityCalibrator
from pripre.models.paths import EmpiricalEstimator, Forecast


class ConditionalEstimator(EmpiricalEstimator):
    name = "conditional-raw"

    def select(self, volatility: float) -> NDArray[np.int64]:
        historical = np.array([path.volatility for path in self.paths], dtype=np.float64)
        distances = np.abs(np.log(np.maximum(historical, 1e-9) / max(volatility, 1e-9)))
        count = min(len(historical), max(16, len(historical) // 3))
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

    def __init__(self, estimator: ConditionalEstimator, calibrator: ProbabilityCalibrator) -> None:
        self.estimator = estimator
        self.calibrator = calibrator

    def predict(self, reference: Decimal, timestamp_us: int, volatility: float) -> Forecast:
        forecast = self.estimator.predict(reference, timestamp_us, volatility)
        return replace(
            forecast, model=self.name, probabilities=self.calibrator.apply(forecast.probabilities)
        )
