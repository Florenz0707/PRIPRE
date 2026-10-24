"""Expanding chronological replay with separate training, calibration and test dates."""

from collections import defaultdict
from datetime import UTC, datetime
from time import perf_counter

import numpy as np
from numpy.typing import NDArray

from pripre.backtesting.dataset import DatasetAudit, Example, load_examples
from pripre.backtesting.metrics import day_bootstrap, metrics
from pripre.config import AppConfig
from pripre.data.history import dataset_summary
from pripre.data.integrity import research_fingerprint
from pripre.data.store import write_json
from pripre.features.market_context import market_context
from pripre.models.calibration import ProbabilityCalibrator
from pripre.models.conditional import CalibratedEstimator, ConditionalEstimator
from pripre.models.paths import EmpiricalEstimator


def folds(days: list[str]) -> list[tuple[list[str], list[str]]]:
    if len(days) < 10:
        raise ValueError(
            "at least ten distinct sampled dates are required for chronological replay"
        )
    initial = min(10, len(days) // 2)
    width = 30
    return [
        (days[:index], days[index : index + width]) for index in range(initial, len(days), width)
    ]


def summarize(
    p: NDArray[np.float64],
    y: NDArray[np.float64],
    examples: list[Example],
    regimes: list[str],
    config: AppConfig,
) -> dict[str, object]:
    daily: dict[str, list[float]] = defaultdict(list)
    for i, item in enumerate(examples):
        daily[item.day].append(float(np.nanmean((p[i] - y[i]) ** 2)))
    by_distance = []
    for distance in range(config.grid.half_width + 1):
        indices = [
            i for i in range(config.grid.rows) if abs(i - config.grid.half_width) == distance
        ]
        by_distance.append(
            {"distance_steps": distance, **metrics(p[:, indices, :], y[:, indices, :])}
        )
    return {
        "summary": metrics(p, y),
        "by_distance": by_distance,
        "by_window": [
            {
                "start_seconds": config.grid.first_window_seconds + i * config.grid.window_seconds,
                **metrics(p[:, :, i], y[:, :, i]),
            }
            for i in range(config.grid.columns)
        ],
        "by_regime": [
            {
                "regime": regime,
                **metrics(p[np.array(regimes) == regime], y[np.array(regimes) == regime]),
            }
            for regime in sorted(set(regimes))
        ],
        "daily": [
            {"date": day, "brier": float(np.mean(scores)), "origins": len(scores)}
            for day, scores in sorted(daily.items())
        ],
        "day_block_brier_95": day_bootstrap([float(np.mean(scores)) for scores in daily.values()]),
    }


def run_research(config: AppConfig) -> dict[str, object]:
    audit = DatasetAudit()
    examples = load_examples(config, audit)
    days = sorted({example.day for example in examples})
    names = ("empirical-baseline", "conditional-raw", "conditional-calibrated")
    predictions: dict[str, list[NDArray[np.float64]]] = {name: [] for name in names}
    labels = []
    testing_examples: list[Example] = []
    regimes: list[str] = []
    fold_reports = []
    durations = []
    ood = 0
    for available_days, test_days in folds(days):
        split = max(1, int(len(available_days) * 0.8))
        train_days, cal_days = available_days[:split], available_days[split:]
        training = [item for item in examples if item.day in train_days]
        calibration = [item for item in examples if item.day in cal_days]
        testing = [item for item in examples if item.day in test_days]
        paths = [item.path for item in training]
        baseline = EmpiricalEstimator(paths, config.grid, config.runtime.paths, config.runtime.seed)
        conditional = ConditionalEstimator(
            paths, config.grid, config.runtime.paths, config.runtime.seed
        )
        raw_cal = np.stack(
            [
                conditional.predict(
                    item.grid.reference_price, item.grid.timestamp_us, item.volatility
                ).probabilities
                for item in calibration
            ]
        )
        calibrator = ProbabilityCalibrator.fit(
            raw_cal, np.stack([item.labels for item in calibration])
        )
        calibrated = CalibratedEstimator(conditional, calibrator)
        low, high = np.quantile([item.volatility for item in training], [0.25, 0.75])
        fold_reports.append(
            {
                "train_start": train_days[0],
                "train_end": train_days[-1],
                "calibration_start": cal_days[0],
                "calibration_end": cal_days[-1],
                "test_start": test_days[0],
                "test_end": test_days[-1],
                "training_paths": len(training),
                "test_origins": len(testing),
            }
        )
        for item in testing:
            start = perf_counter()
            raw = conditional.predict(
                item.grid.reference_price, item.grid.timestamp_us, item.volatility
            )
            calibrated_values = calibrator.apply(raw.probabilities)
            durations.append((perf_counter() - start) * 1000)
            predictions[names[0]].append(
                baseline.predict(
                    item.grid.reference_price, item.grid.timestamp_us, item.volatility
                ).probabilities
            )
            predictions[names[1]].append(raw.probabilities)
            predictions[names[2]].append(calibrated_values)
            ood += int(raw.status != "ready")
            labels.append(item.labels)
            testing_examples.append(item)
            regimes.append(
                "low" if item.volatility < low else "high" if item.volatility > high else "normal"
            )
    y = np.stack(labels)
    stacked = {name: np.stack(values) for name, values in predictions.items()}
    models = {
        name: summarize(values, y, testing_examples, regimes, config)
        for name, values in stacked.items()
    }
    comparisons: list[dict[str, object]] = []
    for candidate, reference in ((names[1], names[0]), (names[2], names[0]), (names[2], names[1])):
        differences = np.nanmean(
            (stacked[candidate] - y) ** 2 - (stacked[reference] - y) ** 2, axis=(1, 2)
        )
        by_day: dict[str, list[float]] = defaultdict(list)
        for item, difference in zip(testing_examples, differences, strict=True):
            by_day[item.day].append(float(difference))
        blocks = [float(np.mean(values)) for values in by_day.values()]
        comparisons.append(
            {
                "candidate": candidate,
                "reference": reference,
                "brier_difference": float(np.mean(differences)),
                "paired_day_block_95": day_bootstrap(blocks, config.runtime.seed),
            }
        )
    result: dict[str, object] = {
        "origin_audit": audit.report(),
        "origin_stride_seconds": config.research.origin_stride_seconds,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_fingerprint": research_fingerprint(config),
        "algorithm_version": "empirical-conditional-calibration-v1",
        "model": calibrated.name,
        "config": config.model_dump(mode="json"),
        "data": dataset_summary(config),
        "market_context": market_context(config),
        "folds": fold_reports,
        "warmup_dates": days[: min(10, len(days) // 2)],
        "models": models,
        "comparisons": comparisons,
        "summary": models[calibrated.name]["summary"],
        "out_of_distribution_origins": ood,
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
            "Out-of-distribution errors remain in research metrics; live output is suppressed.",
            "The calibrated candidate is not assumed to outperform the baseline.",
        ],
    }
    write_json(config.history.data_dir / "research" / "report.json", result)
    return result
