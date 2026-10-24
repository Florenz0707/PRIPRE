"""Read-only replay queries reuse frozen predictions; filtering never retrains models."""

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np

from pripre.backtesting.archive import ReplayArchive
from pripre.backtesting.evaluation import summarize
from pripre.config import AppConfig


@lru_cache(maxsize=2)
def cached_archive(path: str, modified_ns: int) -> ReplayArchive:
    return ReplayArchive.load(Path(path))


def read_evidence(data_dir: Path) -> tuple[dict[str, object], ReplayArchive, AppConfig]:
    report = json.loads((data_dir / "research" / "report.json").read_text())
    run_id = report.get("run_id", "")
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("report has no replay evidence; rerun backtest")
    path = data_dir / "research" / "runs" / run_id / "replay.npz"
    return (
        report,
        cached_archive(str(path), path.stat().st_mtime_ns),
        AppConfig.model_validate(report["config"]),
    )


def date_bounds(start: date | None, end: date | None) -> tuple[str | None, str | None]:
    if start is not None and end is not None and start > end:
        raise ValueError("start date follows end date")
    return start.isoformat() if start else None, end.isoformat() if end else None


def filtered_report(data_dir: Path, start: date | None, end: date | None) -> dict[str, object]:
    lower, upper = date_bounds(start, end)
    report, archive, config = read_evidence(data_dir)
    indices = archive.indices(lower, upper)
    records = [archive.records[i] for i in indices]
    result = dict(report)
    result["models"] = {
        name: summarize(p[indices], archive.labels[indices], records, config)
        for name, p in archive.predictions.items()
    }
    result["market_context"] = [
        row
        for row in json.loads(json.dumps(report["market_context"]))
        if (lower is None or row["date"] >= lower) and (upper is None or row["date"] <= upper)
    ]
    result["out_of_distribution_origins"] = sum(r.out_of_distribution for r in records)
    result["selection"] = {
        "start": lower,
        "end": upper,
        "origins": len(indices),
        "dates": len({r.day for r in records}),
        "note": "Frozen out-of-sample predictions; no retraining.",
    }
    # Full-run comparisons and stage summaries are not valid for this date selection.
    result.pop("comparisons", None)
    result.pop("summary", None)
    result.pop("stage_analysis", None)
    return result


def replay_page(
    data_dir: Path, start: date | None, end: date | None, offset: int, limit: int
) -> dict[str, object]:
    lower, upper = date_bounds(start, end)
    report, archive, _ = read_evidence(data_dir)
    indices = archive.indices(lower, upper)
    return {
        "run_id": report["run_id"],
        "total": len(indices),
        "offset": offset,
        "origins": [
            {
                "timestamp_us": archive.records[i].grid.timestamp_us,
                "reference_price": str(archive.records[i].grid.reference_price),
                "day": archive.records[i].day,
            }
            for i in indices[offset : offset + limit]
        ],
        "models": list(archive.predictions),
    }


def replay_detail(data_dir: Path, timestamp_us: int, model: str) -> dict[str, object]:
    report, archive, _ = read_evidence(data_dir)
    if model not in archive.predictions:
        raise ValueError("unknown replay model")
    index = next(
        (i for i, r in enumerate(archive.records) if r.grid.timestamp_us == timestamp_us), None
    )
    if index is None:
        raise KeyError(timestamp_us)
    record = archive.records[index]
    labels = archive.labels[index]
    return {
        "run_id": report["run_id"],
        "dataset_fingerprint": report["dataset_fingerprint"],
        "algorithm_version": report["algorithm_version"],
        "parameters": report["config"],
        **record.dump(),
        "model": model,
        "probabilities": archive.predictions[model][index].tolist(),
        "labels": [[None if not np.isfinite(v) else int(v) for v in row] for row in labels],
        "status": "out_of_distribution" if record.out_of_distribution else "ready",
    }
