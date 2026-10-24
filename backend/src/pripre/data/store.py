"""Atomic, compressed local datasets; all numerical loads disallow pickle."""

import json
from decimal import Decimal
from pathlib import Path

import numpy as np

from pripre.data.source import TradeBatch
from pripre.domain import Coverage, Instrument, Trade


def save_batch(path: Path, batch: TradeBatch, instrument: Instrument, source: str) -> None:
    if any(
        item.instrument != instrument.id
        or item.source != source
        or item.price % instrument.tick_size
        for item in batch.trades
    ):
        raise ValueError("trade identity or price precision differs from dataset")
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "schema": 1,
        "instrument": instrument.model_dump(mode="json"),
        "source": source,
        "coverage": [item.model_dump() for item in batch.coverage],
    }
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(
            stream,
            metadata=np.array(json.dumps(meta)),
            timestamp_us=np.array([item.timestamp_us for item in batch.trades], dtype=np.int64),
            sequence=np.array([item.sequence for item in batch.trades], dtype=np.int64),
            price_ticks=np.array(
                [int(item.price / instrument.tick_size) for item in batch.trades], dtype=np.int64
            ),
            quantity=np.array([str(item.quantity) for item in batch.trades], dtype=np.str_),
        )
    temporary.replace(path)


def load_batch(path: Path, instrument: Instrument, source: str) -> TradeBatch:
    with np.load(path, allow_pickle=False) as archive:
        meta = json.loads(str(archive["metadata"]))
        if (
            meta.get("schema") != 1
            or meta.get("instrument") != instrument.model_dump(mode="json")
            or meta.get("source") != source
        ):
            raise ValueError("cached dataset identity does not match configuration")
        times, sequences, prices, quantities = (
            archive[key] for key in ("timestamp_us", "sequence", "price_ticks", "quantity")
        )
        trades = tuple(
            Trade(
                instrument=instrument.id,
                source=source,
                sequence=int(sequence),
                timestamp_us=int(timestamp),
                price=int(price) * instrument.tick_size,
                quantity=Decimal(str(quantity)),
            )
            for timestamp, sequence, price, quantity in zip(
                times, sequences, prices, quantities, strict=True
            )
        )
        coverage = tuple(Coverage.model_validate(item) for item in meta["coverage"])
    return TradeBatch(trades, coverage)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)
