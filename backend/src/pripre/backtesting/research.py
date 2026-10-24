"""Expanding chronological replay with separate training, calibration and test dates."""

from collections import defaultdict
from datetime import UTC, datetime
from time import perf_counter
from typing import cast
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

from pripre.backtesting.archive import OriginRecord, ReplayArchive
from pripre.backtesting.dataset import DatasetAudit, Example, load_examples
from pripre.backtesting.evaluation import summarize
from pripre.backtesting.metrics import day_bootstrap
from pripre.config import AppConfig
from pripre.data.history import dataset_summary
from pripre.data.integrity import research_fingerprint
from pripre.data.store import write_json
from pripre.features.market_context import market_context
from pripre.models.calibration import ProbabilityCalibrator
from pripre.models.conditional import CalibratedEstimator, ConditionalEstimator
from pripre.models.frequency import FrequencyEstimator
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


def run_research(config: AppConfig) -> dict[str, object]:
    audit = DatasetAudit()
    examples = load_examples(config, audit)
    days = sorted({example.day for example in examples})
    names = (
        "empirical-baseline",
        "conditional-raw",
        "conditional-calibrated",
        "frequency-baseline",
    )
    predictions: dict[str, list[NDArray[np.float64]]] = {name: [] for name in names}
    labels = []
    testing_examples: list[Example] = []
    records: list[OriginRecord] = []
    context = market_context(config)
    context_by_day = {str(row["date"]): row for row in context}
    cutoff = (
        float(np.quantile([abs(cast(float, row["return"])) for row in context], 0.95))
        if context
        else float("inf")
    )
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
        frequency = FrequencyEstimator(
            np.stack([item.labels for item in training]),
            [item.volatility for item in training],
            config.grid,
            max(item.path.end_us for item in training),
        )
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
            predictions[names[3]].append(
                frequency.predict(
                    item.grid.reference_price, item.grid.timestamp_us, item.volatility
                ).probabilities
            )
            ood += int(raw.status != "ready")
            labels.append(item.labels)
            testing_examples.append(item)
            day_context = context_by_day.get(item.day, {})
            daily_return = cast(float, day_context.get("return", 0.0))
            efficiency = cast(float, day_context.get("efficiency", 0.0))
            phase = (
                ("uptrend" if daily_return >= 0 else "downtrend")
                if efficiency * np.sqrt(cast(int, day_context.get("minutes", 0))) >= 1.0
                else "range"
            )
            records.append(
                OriginRecord(
                    item.day,
                    item.grid,
                    item.volatility,
                    "low"
                    if item.volatility < low
                    else "high"
                    if item.volatility > high
                    else "normal",
                    raw.status != "ready",
                    phase if day_context else "unclassified",
                    bool(day_context) and abs(daily_return) >= cutoff,
                )
            )
    y = np.stack(labels)
    stacked = {name: np.stack(values) for name, values in predictions.items()}
    models = {name: summarize(values, y, records, config) for name, values in stacked.items()}
    comparisons: list[dict[str, object]] = []
    for candidate, reference in (
        (names[1], names[0]),
        (names[2], names[0]),
        (names[2], names[1]),
        (names[2], names[3]),
    ):
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
    run_id = uuid4().hex
    ReplayArchive(records, y, stacked).save(
        config.history.data_dir / "research" / "runs" / run_id / "replay.npz"
    )
    result: dict[str, object] = {
        "run_id": run_id,
        "stage_analysis": {
            "phase_rule": (
                "Retrospective efficiency * sqrt(minute count) >= 1 means trend. "
                "means trend; direction by daily return. Never a prediction feature."
            ),
            "event_rule": (
                "Retrospective top 5% absolute daily returns, independent of model errors; "
                "never training features."
            ),
            "event_cutoff": cutoff if context else None,
            "event_dates": [
                str(row["date"]) for row in context if abs(cast(float, row["return"])) >= cutoff
            ],
            "sampled_event_dates": sorted({r.day for r in records if r.extreme_day}),
            "phase_dates": {
                phase: sorted({r.day for r in records if r.phase == phase})
                for phase in sorted({r.phase for r in records})
            },
        },
        "origin_audit": audit.report(),
        "origin_stride_seconds": config.research.origin_stride_seconds,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_fingerprint": research_fingerprint(config),
        "algorithm_version": "empirical-conditional-calibration-v2",
        "model": calibrated.name,
        "config": config.model_dump(mode="json"),
        "data": dataset_summary(config),
        "market_context": context,
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
