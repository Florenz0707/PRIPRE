"""Immutable per-run replay evidence, committed before the report pointer changes."""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from pripre.domain import PredictionGrid


@dataclass(frozen=True)
class OriginRecord:
    day: str
    grid: PredictionGrid
    volatility: float
    regime: str
    out_of_distribution: bool
    phase: str = "unclassified"
    extreme_day: bool = False

    def dump(self) -> dict[str, object]:
        return {
            "day": self.day,
            "grid": self.grid.model_dump(mode="json"),
            "volatility": self.volatility,
            "regime": self.regime,
            "out_of_distribution": self.out_of_distribution,
            "phase": self.phase,
            "extreme_day": self.extreme_day,
        }


@dataclass(frozen=True)
class ReplayArchive:
    records: list[OriginRecord]
    labels: NDArray[np.float64]
    predictions: dict[str, NDArray[np.float64]]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            np.savez_compressed(
                stream,
                allow_pickle=False,
                labels=self.labels,
                metadata=np.array(json.dumps([item.dump() for item in self.records])),
                **self.predictions,
            )
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> "ReplayArchive":
        with np.load(path, allow_pickle=False) as data:
            rows = json.loads(str(data["metadata"]))
            records = [
                OriginRecord(
                    day=row["day"],
                    grid=PredictionGrid.model_validate(row["grid"]),
                    volatility=row["volatility"],
                    regime=row["regime"],
                    out_of_distribution=row["out_of_distribution"],
                    phase=row["phase"],
                    extreme_day=row["extreme_day"],
                )
                for row in rows
            ]
            labels = np.asarray(data["labels"], dtype=np.float64)
            predictions = {
                name: np.asarray(data[name], dtype=np.float64)
                for name in data.files
                if name not in ("labels", "metadata")
            }
        if not records or any(p.shape != labels.shape for p in predictions.values()):
            raise ValueError("invalid replay archive")
        if labels.shape[0] != len(records):
            raise ValueError("replay origin count does not match labels")
        return cls(records, labels, predictions)

    def indices(self, start: str | None, end: str | None) -> list[int]:
        return [
            i
            for i, row in enumerate(self.records)
            if (start is None or row.day >= start) and (end is None or row.day <= end)
        ]
