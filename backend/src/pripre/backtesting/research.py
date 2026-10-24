"""Expanding chronological replay; training labels end before each test fold."""

from collections import defaultdict
from datetime import UTC, datetime
from time import perf_counter

import numpy as np

from pripre.backtesting.dataset import Example, load_examples
from pripre.backtesting.metrics import day_bootstrap, metrics
from pripre.config import AppConfig
from pripre.data.history import dataset_summary
from pripre.data.store import write_json
from pripre.features.market_context import market_context
from pripre.models.paths import EmpiricalEstimator


def folds(days: list[str]) -> list[tuple[list[str], list[str]]]:
    if len(days) < 10:
        raise ValueError(
            "at least ten distinct sampled dates are required for chronological replay"
        )
    initial = max(5, len(days) // 2)
    width = max(1, (len(days) - initial + 2) // 3)
    return [
        (days[:index], days[index : index + width]) for index in range(initial, len(days), width)
    ]


def run_research(config: AppConfig) -> dict[str, object]:
    examples = load_examples(config)
    days = sorted({example.day for example in examples})
    predictions = []
    labels = []
    test_examples: list[Example] = []
    fold_reports = []
    durations = []
    daily: dict[str, list[float]] = defaultdict(list)
    for training_days, test_days in folds(days):
        training = [item for item in examples if item.day in training_days]
        testing = [item for item in examples if item.day in test_days]
        estimator = EmpiricalEstimator(
            [item.path for item in training], config.grid, config.runtime.paths, config.runtime.seed
        )
        fold_reports.append(
            {
                "train_start": training_days[0],
                "train_end": training_days[-1],
                "test_start": test_days[0],
                "test_end": test_days[-1],
                "training_paths": len(training),
                "test_origins": len(testing),
            }
        )
        for item in testing:
            start = perf_counter()
            forecast = estimator.predict(
                item.grid.reference_price, item.grid.timestamp_us, item.volatility
            )
            durations.append((perf_counter() - start) * 1000)
            predictions.append(forecast.probabilities)
            labels.append(item.labels)
            test_examples.append(item)
            daily[item.day].append(float(np.nanmean((forecast.probabilities - item.labels) ** 2)))
    p, y = np.stack(predictions), np.stack(labels)
    by_distance = []
    for distance in range(config.grid.half_width + 1):
        indices = [
            i for i in range(config.grid.rows) if abs(i - config.grid.half_width) == distance
        ]
        by_distance.append(
            {"distance_steps": distance, **metrics(p[:, indices, :], y[:, indices, :])}
        )
    by_window = [
        {
            "start_seconds": window.start_us // 1_000_000
            - test_examples[0].grid.timestamp_us // 1_000_000,
            **metrics(p[:, :, index], y[:, :, index]),
        }
        for index, window in enumerate(test_examples[0].grid.windows)
    ]
    result: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": "empirical-baseline",
        "config": config.model_dump(mode="json"),
        "data": dataset_summary(config),
        "market_context": market_context(config),
        "folds": fold_reports,
        "summary": metrics(p, y),
        "by_distance": by_distance,
        "by_window": by_window,
        "daily": [
            {"date": day, "brier": float(np.mean(scores)), "origins": len(scores)}
            for day, scores in sorted(daily.items())
        ],
        "day_block_brier_95": day_bootstrap([float(np.mean(scores)) for scores in daily.values()]),
        "latency_ms": {
            "p50": float(np.quantile(durations, 0.5)),
            "p95": float(np.quantile(durations, 0.95)),
            "max": max(durations),
        },
        "limitations": [
            "Exact touch evaluation covers sampled intervals only.",
            "Minute context is never used as a touch label.",
            "Daily samples overlap internally; confidence resamples entire dates.",
            "Replay assumes exchange-time availability; network delay is not modeled.",
        ],
    }
    write_json(config.history.data_dir / "research" / "report.json", result)
    return result
