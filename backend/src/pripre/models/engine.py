"""Train once from local samples; share the same estimator in live and replay."""

import numpy as np

from pripre.backtesting.dataset import load_examples
from pripre.config import AppConfig
from pripre.models.calibration import ProbabilityCalibrator
from pripre.models.conditional import CalibratedEstimator, ConditionalEstimator


def build_engine(config: AppConfig) -> CalibratedEstimator:
    examples = load_examples(config)
    days = sorted({item.day for item in examples})
    if len(days) < 10:
        raise ValueError("at least ten sampled dates are required to fit a live model")
    split = max(1, int(len(days) * 0.8))
    training = [item for item in examples if item.day < days[split]]
    calibration = [item for item in examples if item.day >= days[split]]
    estimator = ConditionalEstimator(
        [item.path for item in training], config.grid, config.runtime.paths, config.runtime.seed
    )
    predictions = np.stack(
        [
            estimator.predict(
                item.grid.reference_price, item.grid.timestamp_us, item.volatility
            ).probabilities
            for item in calibration
        ]
    )
    labels = np.stack([item.labels for item in calibration])
    return CalibratedEstimator(estimator, ProbabilityCalibrator.fit(predictions, labels))
