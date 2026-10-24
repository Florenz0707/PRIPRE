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
