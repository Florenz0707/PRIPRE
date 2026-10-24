"""A bounded local prediction audit trail; frozen boundaries survive UI recentering."""

import json
import sqlite3
import zlib
from pathlib import Path


class PredictionJournal:
    def __init__(self, path: Path, retain: int = 3600) -> None:
        self.path = path
        self.retain = retain
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS predictions "
                "(timestamp_us INTEGER PRIMARY KEY, payload BLOB NOT NULL)"
            )

    def append(self, timestamp_us: int, payload: dict[str, object]) -> None:
        packed = zlib.compress(json.dumps(payload, separators=(",", ":")).encode())
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO predictions VALUES (?,?)", (timestamp_us, packed)
            )
            connection.execute(
                "DELETE FROM predictions WHERE timestamp_us NOT IN "
                "(SELECT timestamp_us FROM predictions ORDER BY timestamp_us DESC LIMIT ?)",
                (self.retain,),
            )
