"""Frozen replay, date filtering, uncertainty and independent frequency evidence."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pripre.api import create_app
from pripre.backtesting.archive import OriginRecord, ReplayArchive
from pripre.backtesting.evaluation import summarize
from pripre.config import AppConfig, GridConfig, HistoryConfig
from pripre.data.store import write_json
from pripre.models.frequency import FrequencyEstimator


def evidence(tmp_path: Path) -> AppConfig:
    config = AppConfig(
        grid=GridConfig(half_width=1, horizon_seconds=10), history=HistoryConfig(data_dir=tmp_path)
    )
    records = [
        OriginRecord(
            "2026-01-11", config.grid.build(Decimal(10000), 100_000_000), 0.1, "low", False, "range"
        ),
        OriginRecord(
            "2026-01-12",
            config.grid.build(Decimal(10100), 200_000_000),
            0.3,
            "high",
            True,
            "uptrend",
            True,
        ),
    ]
    y = np.array([[[0.0], [1.0], [0.0]], [[1.0], [0.0], [1.0]]])
    p = np.array([[[0.0], [1.0], [0.0]], [[0.0], [1.0], [0.0]]])
    run_id = "a" * 32
    ReplayArchive(records, y, {"conditional-calibrated": p}).save(
        tmp_path / "research" / "runs" / run_id / "replay.npz"
    )
    write_json(
        tmp_path / "research" / "report.json",
        {
            "run_id": run_id,
            "config": config.model_dump(mode="json"),
            "dataset_fingerprint": "test",
            "algorithm_version": "test",
            "models": {},
            "market_context": [],
            "comparisons": ["full run only"],
            "summary": {"brier": 0.5},
        },
    )
    return config


def test_replay_api_filters_metrics_and_preserves_frozen_grids(tmp_path: Path) -> None:
    config = evidence(tmp_path)
    with TestClient(create_app(config)) as client:
        selected = client.get("/api/research?start=2026-01-11&end=2026-01-11").json()
        assert selected["models"]["conditional-calibrated"]["summary"]["brier"] == 0
        assert "comparisons" not in selected and "summary" not in selected
        assert client.get("/api/research?start=2026-02-01").json()["selection"]["origins"] == 0
        assert client.get("/api/research?start=2026-02-01&end=2026-01-01").status_code == 422
        assert client.get("/api/replay?limit=101").status_code == 422
        assert client.get("/api/replay?start=2026-01-12").json()["total"] == 1
        detail = client.get("/api/replay/100000000").json()
        assert detail["grid"]["reference_price"] == "10000"
        assert detail["labels"] == [[0], [1], [0]]
        assert detail["probabilities"] == [[0], [1], [0]]
        assert client.get("/api/replay/0").status_code == 404
        assert client.get("/api/replay/100000000?model=unknown").status_code == 422


def test_group_intervals_and_live_policy_keep_ood_errors(tmp_path: Path) -> None:
    config = evidence(tmp_path)
    archive = ReplayArchive.load(tmp_path / "research" / "runs" / ("a" * 32) / "replay.npz")
    report = summarize(
        archive.predictions["conditional-calibrated"], archive.labels, archive.records, config
    )
    assert report["summary"]["brier"] == pytest.approx(0.5)  # type: ignore[index]
    assert report["summary"]["day_block_brier_95"] == [0.0, 1.0]  # type: ignore[index]
    assert report["live_policy"]["suppressed_origins"] == 1  # type: ignore[index]
    assert report["live_policy"]["published"]["brier"] == 0  # type: ignore[index]
    for group in report["by_distance"]:  # type: ignore[attr-defined]
        assert group["count"] > 0 and group["day_block_brier_95"] is not None


def test_frequency_baseline_uses_state_evidence_and_sparse_fallback() -> None:
    labels = np.array([[[0.0]], [[0.0]], [[1.0]], [[1.0]]])
    estimator = FrequencyEstimator(labels, [0.1, 0.2, 0.3, 0.4], GridConfig(), 10, minimum=1)
    assert estimator.predict(Decimal(10000), 20, 0.01).probabilities[0, 0] == 0
    assert estimator.predict(Decimal(10000), 20, 0.9).probabilities[0, 0] == 1
    estimator.minimum = 16
    assert estimator.predict(Decimal(10000), 20, 0.9).probabilities[0, 0] == 0.5
    with pytest.raises(ValueError, match="beyond"):
        estimator.predict(Decimal(10000), 0, 0.1)


def test_full_research_and_development_experiments_leave_replay_evidence(tmp_path: Path) -> None:
    from datetime import timedelta

    from pripre.backtesting.experiments import run_experiments
    from pripre.backtesting.research import run_research
    from pripre.data.source import TradeBatch
    from pripre.data.store import save_batch
    from pripre.domain import Coverage, Trade

    config = AppConfig(
        grid=GridConfig(half_width=1, horizon_seconds=10),
        history=HistoryConfig(data_dir=tmp_path, end=date(2026, 1, 20)),
    )
    for index in range(20):
        day = date(2026, 1, 1) + timedelta(days=index)
        start = (1767225600 + index * 86400) * 1_000_000
        trades = tuple(
            Trade(
                instrument="BTC_USDT",
                source="binance",
                sequence=i,
                timestamp_us=start + i * 1_000_000,
                price=Decimal(10000 + (i % 7) * 10),
                quantity=Decimal(1),
            )
            for i in range(420)
        )
        save_batch(
            tmp_path / "BTC_USDT" / "binance" / "trades" / f"{day}.npz",
            TradeBatch(trades, (Coverage(start_us=start, end_us=start + 420_000_000),)),
            config.instrument,
            "binance",
        )
    report = run_research(config)
    run_id = str(report["run_id"])
    archive = ReplayArchive.load(tmp_path / "research" / "runs" / run_id / "replay.npz")
    assert len(archive.predictions) == 4
    assert all(r.day >= "2026-01-11" for r in archive.records)
    experiment = run_experiments(config)
    assert experiment["untouched_test_dates"] == ["2026-01-17", "2026-01-20"]
    assert len(experiment["variants"]) == 20  # type: ignore[arg-type]
    with TestClient(create_app(config)) as client:
        response = client.get("/api/research?start=2026-01-11&end=2026-01-11")
        assert response.status_code == 200
        assert response.json()["selection"]["origins"] > 0
