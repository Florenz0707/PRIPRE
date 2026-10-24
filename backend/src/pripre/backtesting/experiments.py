"""Predeclared development diagnostics; no selection on the final held-out dates."""

from time import perf_counter

import numpy as np
from numpy.typing import NDArray

from pripre.backtesting.dataset import load_examples
from pripre.config import AppConfig, ResearchConfig
from pripre.data.integrity import research_fingerprint
from pripre.data.store import write_json
from pripre.models.conditional import ConditionalEstimator


def run_experiments(config: AppConfig) -> dict[str, object]:
    examples = load_examples(config)
    days = sorted({r.day for r in examples})
    if len(days) < 20:
        raise ValueError("experiments require at least twenty sample dates")
    train_end, validation_end = int(len(days) * 0.6), int(len(days) * 0.8)
    training = [r for r in examples if r.day < days[train_end]]
    validation = [r for r in examples if days[train_end] <= r.day < days[validation_end]]
    # Deterministic temporal spacing, independent of labels and model errors.
    validation = validation[:: max(1, len(validation) // 20)][:20]
    paths = [r.path for r in training]
    settings: list[dict[str, object]] = []
    for count in (64, 256, 512, 1024):
        for seed in (2026, 2027, 2028):
            settings.append(
                {
                    "count": count,
                    "seed": seed,
                    "fraction": 1 / 3,
                    "minimum": 16,
                    "mapping": "relative",
                    "horizon": 180,
                    "stride": config.research.origin_stride_seconds,
                }
            )
    for fraction, minimum, mapping, horizon, stride in (
        (0.2, 16, "relative", 180, 60),
        (0.5, 16, "relative", 180, 60),
        (1 / 3, 8, "relative", 180, 60),
        (1 / 3, 32, "relative", 180, 60),
        (1 / 3, 16, "absolute", 180, 60),
        (1 / 3, 16, "relative", 60, 60),
        (1 / 3, 16, "relative", 120, 60),
        (1 / 3, 16, "relative", 180, 30),
    ):
        settings.append(
            {
                "count": 512,
                "seed": 2026,
                "fraction": fraction,
                "minimum": minimum,
                "mapping": mapping,
                "horizon": horizon,
                "stride": stride,
            }
        )
    alternate = config.model_copy(update={"research": ResearchConfig(origin_stride_seconds=30)})
    dense_paths = [r.path for r in load_examples(alternate) if r.day < days[train_end]]
    reference = ConditionalEstimator(paths, config.grid, 4096, 999)
    reference_values = [
        reference.predict(r.grid.reference_price, r.grid.timestamp_us, r.volatility).probabilities
        for r in validation
    ]
    rows = []
    monte_carlo: dict[int, list[NDArray[np.float64]]] = {}
    for setting in settings:
        count, seed = int(str(setting["count"])), int(str(setting["seed"]))
        horizon = min(config.grid.horizon_seconds, int(str(setting["horizon"])))
        grid = config.grid.model_copy(update={"horizon_seconds": horizon})
        estimator = ConditionalEstimator(
            dense_paths if setting["stride"] == 30 else paths,
            grid,
            count,
            seed,
            candidate_fraction=float(str(setting["fraction"])),
            minimum_candidates=int(str(setting["minimum"])),
            mapping=str(setting["mapping"]),
        )
        started = perf_counter()
        p = np.stack(
            [
                estimator.predict(
                    r.grid.reference_price, r.grid.timestamp_us, r.volatility
                ).probabilities
                for r in validation
            ]
        )
        elapsed = (perf_counter() - started) * 1000 / len(validation)
        y = np.stack([r.labels[:, : grid.columns] for r in validation])
        ref = np.stack([r[:, : grid.columns] for r in reference_values])
        rows.append(
            {
                **setting,
                "horizon": horizon,
                "origins": len(validation),
                "brier": float(np.nanmean((p - y) ** 2)),
                "mean_ms": elapsed,
                "rmse_vs_4096_paths": float(np.sqrt(np.mean((p - ref) ** 2))),
            }
        )
        if setting in settings[:12]:
            monte_carlo.setdefault(count, []).append(p)
    result: dict[str, object] = {
        "dataset_fingerprint": research_fingerprint(config),
        "protocol": (
            "Development diagnostics only; no automatic model change. "
            "Short horizons have different targets; do not rank against full horizons."
        ),
        "train_dates": [days[0], days[train_end - 1]],
        "validation_dates": [days[train_end], days[validation_end - 1]],
        "untouched_test_dates": [days[validation_end], days[-1]],
        "validation_origins": len(validation),
        "variants": rows,
        "monte_carlo": [
            {
                "paths": count,
                "seeds": 3,
                "mean_cell_std": float(np.mean(np.std(np.stack(values), axis=0))),
                "max_cell_std": float(np.max(np.std(np.stack(values), axis=0))),
            }
            for count, values in monte_carlo.items()
        ],
        "limitations": [
            "The 4096-path reference is also stochastic, not ground truth.",
            "Held-out dates were viewed in initial research; they are not virgin data.",
            "Only temporally spaced development origins are used; no final-test claim.",
            "Candidate minimum merges sparse states; larger samples are not independent.",
        ],
    }
    write_json(config.history.data_dir / "research" / "experiments.json", result)
    return result
