"""The estimator and evaluation share public event semantics and causal splits."""

from decimal import Decimal

import numpy as np
import pytest
from pripre.backtesting.metrics import day_bootstrap, metrics
from pripre.backtesting.research import folds
from pripre.config import GridConfig
from pripre.models.paths import EmpiricalEstimator, TradePath


def test_empirical_paths_count_any_trade_without_filling_jumps() -> None:
    path = TradePath(
        0,
        15_000_000,
        0.01,
        np.array([5_000_000, 9_000_000, 10_000_000]),
        np.array([-0.1, 0.1, 0.0]),
    )
    estimator = EmpiricalEstimator([path], GridConfig(half_width=1, horizon_seconds=15), 64)
    forecast = estimator.predict(Decimal(1000), 20_000_000, 0.01)
    np.testing.assert_array_equal(forecast.probabilities, [[1, 0], [0, 1], [1, 0]])
    with pytest.raises(ValueError, match="beyond"):
        estimator.predict(Decimal(1000), 10_000_000, 0.01)


def test_chronological_folds_never_train_on_test_dates() -> None:
    days = [f"2026-01-{i:02d}" for i in range(1, 21)]
    splits = folds(days)
    assert len(splits) == 3
    assert [day for _, test in splits for day in test] == days[10:]
    for train, test in splits:
        assert max(train) < min(test)


def test_metrics_report_unknowns_and_perfect_probabilities() -> None:
    p = np.array([0.0, 1.0, 0.5])
    y = np.array([0.0, 1.0, np.nan])
    result = metrics(p, y)
    assert result["count"] == 2 and result["unknown"] == 1
    assert result["brier"] == 0 and result["skill_vs_zero"] == 1
    assert day_bootstrap([0.1, 0.1]) == pytest.approx([0.1, 0.1])


def test_calibrator_is_monotone_even_when_sample_bins_are_reversed() -> None:
    from pripre.models.calibration import ProbabilityCalibrator

    p = np.array([0.1, 0.1, 0.9, 0.9])
    y = np.array([1.0, 1.0, 0.0, 0.0])
    calibrator = ProbabilityCalibrator.fit(p, y, prior_weight=0)
    actual = calibrator.apply(np.linspace(0, 1, 11))
    assert np.all(np.diff(actual) >= 0)
    np.testing.assert_allclose(actual, 0.5)


def test_conditioning_changes_selection_and_extreme_state_is_flagged() -> None:
    from pripre.models.conditional import ConditionalEstimator

    paths = [
        TradePath(0, 15_000_000, float(i + 1) * 0.001, np.array([5_000_000]), np.array([0.0]))
        for i in range(60)
    ]
    estimator = ConditionalEstimator(paths, GridConfig(half_width=1, horizon_seconds=15), 64)
    assert max(estimator.select(0.001)) < 30
    assert min(estimator.select(0.06)) > 20
    assert estimator.predict(Decimal(1000), 20_000_000, 1).status == "out_of_distribution"
