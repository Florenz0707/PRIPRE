"""Full-date-range minute context plus rotating daily, exact trade samples."""

import csv
import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import numpy as np
from numpy.typing import NDArray

from pripre.config import AppConfig
from pripre.data.binance import (
    ARCHIVE_BASE,
    REST_BASE,
    BinanceSource,
    HTTPReader,
    require_symbol,
    timestamp_us,
)
from pripre.data.http import DownloadBudget, DownloadError, PublicHTTP
from pripre.data.proxy import SourceProxy
from pripre.data.store import load_batch, save_batch, write_json


def midnight_us(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), UTC).timestamp()) * 1_000_000


def daily_sample(day: date, seconds: int) -> tuple[int, int]:
    # Rotate through all 24 UTC hours and minute offsets; no selection by returns.
    offset = ((day.toordinal() * 7) % 24) * 3600 + (day.toordinal() * 13 % 40) * 60
    offset = min(offset, 86400 - seconds)
    start = midnight_us(day) + offset * 1_000_000
    return start, start + seconds * 1_000_000


def parse_minutes(rows: list[list[str]], tick: Decimal) -> NDArray[np.int64]:
    result: list[list[int]] = []
    for row in rows:
        if len(row) < 9:
            raise ValueError("incomplete kline record")
        result.append(
            [
                timestamp_us(int(row[0])),
                int(Decimal(row[4]) / tick),
                int(Decimal(row[2]) / tick),
                int(Decimal(row[3]) / tick),
                int(row[8]),
            ]
        )
    array = np.array(result, dtype=np.int64).reshape(-1, 5)
    if len(array) and (
        np.any(np.diff(array[:, 0]) != 60_000_000)
        or np.any(array[:, 1:4] <= 0)
        or np.any(array[:, 2] < array[:, 1])
        or np.any(array[:, 1] < array[:, 3])
        or np.any(array[:, 4] < 0)
    ):
        raise ValueError("minute data contains gaps, duplicates or invalid prices")
    return array


def archive_minutes(http: HTTPReader, url: str, tick: Decimal) -> NDArray[np.int64]:
    checksum = http.get(url + ".CHECKSUM").decode().split()[0]
    payload = http.get(url)
    if hashlib.sha256(payload).hexdigest() != checksum:
        raise ValueError("archive checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].file_size > 100_000_000:
            raise ValueError("unexpected archive contents or expanded size")
        with archive.open(members[0]) as stream:
            return parse_minutes(list(csv.reader(io.TextIOWrapper(stream))), tick)


def minute_partitions(start: date, end: date, today: date) -> list[tuple[str, date, date]]:
    result: list[tuple[str, date, date]] = []
    day = start
    while day <= end:
        next_month = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
        if day.day == 1 and next_month <= today and next_month - timedelta(days=1) <= end:
            result.append(("monthly", day, next_month))
            day = next_month
        else:
            result.append(("daily", day, day + timedelta(days=1)))
            day += timedelta(days=1)
    return result


def collect_history(config: AppConfig) -> dict[str, object]:
    if config.source.provider != "binance":
        raise ValueError("historical archive collection requires a registered archive adapter")
    symbol = require_symbol(config.source.symbol)
    directory = config.history.data_dir / config.instrument.id / config.source.provider
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    budget = DownloadBudget(
        config.history.max_requests,
        config.history.max_download_mb * 1024 * 1024,
        int(previous.get("requests", 0)),
        int(previous.get("downloaded_bytes", 0)),
    )
    proxy = SourceProxy.from_environment()
    http = PublicHTTP(budget, proxy=proxy)
    source = BinanceSource(config.instrument, http, proxy=proxy)
    completed: list[str] = []
    gaps: list[dict[str, str]] = []
    result: dict[str, object] = {
        "schema": 1,
        "instrument": config.instrument.model_dump(mode="json"),
        "source": config.source.model_dump(),
        "requested_start": str(config.history.start),
        "sample_seconds": config.history.sample_seconds,
        "sampling": "420-second rotating daily trade samples; minute context is not touch evidence",
    }
    try:
        server = json.loads(http.get(f"{REST_BASE}/time"))
        now_us = timestamp_us(int(server["serverTime"]))
        today = datetime.fromtimestamp(now_us / 1_000_000, UTC).date()
        end = min(config.history.end_date(), today)
        result.update(requested_end=str(config.history.end_date()), source_now_us=now_us)
        for cadence, start, _stop in minute_partitions(config.history.start, end, today):
            name = start.strftime("%Y-%m" if cadence == "monthly" else "%Y-%m-%d")
            path = directory / "minutes" / f"{name}.npz"
            if path.exists() and start < today:
                with np.load(path, allow_pickle=False) as cached:
                    cached_array = cached["minutes"]
                    expected = (midnight_us(_stop) - midnight_us(start)) // 60_000_000
                    if len(cached_array) == expected:
                        continue
            try:
                if start == today:
                    rows: list[list[str]] = []
                    cursor = midnight_us(start)
                    while cursor + 60_000_000 <= now_us:
                        params = urlencode(
                            {
                                "symbol": symbol,
                                "interval": "1m",
                                "startTime": cursor // 1000,
                                "limit": 1000,
                            }
                        )
                        payload = json.loads(http.get(f"{REST_BASE}/klines?{params}"))
                        if not isinstance(payload, list) or not payload:
                            break
                        rows.extend(
                            [
                                [str(item) for item in row]
                                for row in payload
                                if timestamp_us(int(row[0])) + 60_000_000 <= now_us
                            ]
                        )
                        next_cursor = timestamp_us(int(payload[-1][0])) + 60_000_000
                        if next_cursor <= cursor:
                            raise ValueError("minute pagination made no progress")
                        cursor = next_cursor
                    array = parse_minutes(rows, config.instrument.tick_size)
                else:
                    url = f"{ARCHIVE_BASE}/{cadence}/klines/{symbol}/1m/{symbol}-1m-{name}.zip"
                    array = archive_minutes(http, url, config.instrument.tick_size)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.with_suffix(".tmp").open("wb") as stream:
                    np.savez_compressed(stream, minutes=array)
                path.with_suffix(".tmp").replace(path)
            except DownloadError as exc:
                gaps.append({"partition": name, "error": str(exc)})
                if "budget" in str(exc):
                    raise
        day = config.history.start
        while day <= end:
            start_us, end_us = daily_sample(day, config.history.sample_seconds)
            path = directory / "trades" / f"{day}.npz"
            if end_us > now_us:
                gaps.append({"partition": str(day), "error": "sample window not complete yet"})
            elif path.exists():
                batch = load_batch(path, config.instrument, config.source.provider)
                if (
                    not batch.coverage
                    or batch.coverage[0].start_us != start_us
                    or batch.coverage[-1].end_us != end_us
                ):
                    raise ValueError(
                        "cached sample configuration differs; use a new data directory"
                    )
                completed.append(str(day))
            else:
                batch = source.fetch_history(symbol, start_us, end_us)
                save_batch(path, batch, config.instrument, source.id)
                completed.append(str(day))
            if len(completed) % 10 == 0:
                print(
                    f"history: {day}, samples={len(completed)}, requests={budget.requests}, "
                    f"MiB={budget.downloaded_bytes / 1048576:.1f}",
                    flush=True,
                )
            day += timedelta(days=1)
    except (DownloadError, ValueError, OSError) as exc:
        result["error"] = str(exc)
    finally:
        result.update(
            completed_sample_dates=completed,
            completed_sample_count=len(completed),
            gaps=gaps,
            requests=budget.requests,
            downloaded_bytes=budget.downloaded_bytes,
            sampling=f"{config.history.sample_seconds}-second rotating daily trade samples",
            updated_at=datetime.now(UTC).isoformat(),
        )
        write_json(manifest_path, result)
    return result


def load_minutes(config: AppConfig) -> NDArray[np.int64]:
    directory = config.history.data_dir / config.instrument.id / config.source.provider
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("instrument") != config.instrument.model_dump(mode="json"):
            raise ValueError("minute dataset instrument identity does not match configuration")
    partitions: list[NDArray[np.int64]] = []
    for file in sorted((directory / "minutes").glob("*.npz")):
        with np.load(file, allow_pickle=False) as archive:
            partitions.append(np.asarray(archive["minutes"], dtype=np.int64))
    minutes = np.concatenate(partitions) if partitions else np.empty((0, 5), dtype=np.int64)
    start = midnight_us(config.history.start)
    end = midnight_us(config.history.end_date() + timedelta(days=1))
    minutes = minutes[(minutes[:, 0] >= start) & (minutes[:, 0] < end)]
    if len(minutes):
        minutes = minutes[np.argsort(minutes[:, 0], kind="stable")]
        repeated = np.flatnonzero(np.diff(minutes[:, 0]) == 0)
        if len(repeated) and np.any(minutes[repeated] != minutes[repeated + 1]):
            raise ValueError("overlapping minute partitions disagree")
        _, indices = np.unique(minutes[:, 0], return_index=True)
        minutes = minutes[indices]
    return minutes


def dataset_summary(config: AppConfig) -> dict[str, object]:
    directory = config.history.data_dir / config.instrument.id / config.source.provider
    path = directory / "manifest.json"
    manifest: dict[str, object] = json.loads(path.read_text()) if path.exists() else {}
    minutes = load_minutes(config)
    samples = [
        file
        for file in sorted((directory / "trades").glob("*.npz"))
        if config.history.start <= date.fromisoformat(file.stem) <= config.history.end_date()
    ]
    total = 0
    sampled_us = 0
    for file in samples:
        batch = load_batch(file, config.instrument, config.source.provider)
        total += len(batch.trades)
        sampled_us += sum(item.end_us - item.start_us for item in batch.coverage)
    source_now = int(str(manifest.get("source_now_us", 0)))
    requested_end = min(source_now, midnight_us(config.history.end_date() + timedelta(days=1)))
    expected_minutes = max(0, (requested_end - midnight_us(config.history.start)) // 60_000_000)
    return {
        "manifest": manifest,
        "minute_rows": len(minutes),
        "minute_start_us": int(minutes[0, 0]) if len(minutes) else None,
        "minute_end_us": int(minutes[-1, 0] + 60_000_000) if len(minutes) else None,
        "expected_minute_rows": expected_minutes,
        "missing_minute_rows": max(0, expected_minutes - len(minutes)),
        "minute_gap_count": int(np.count_nonzero(np.diff(minutes[:, 0]) != 60_000_000)),
        "sample_dates": [file.stem for file in samples],
        "trade_rows": total,
        "sampled_seconds": sampled_us // 1_000_000,
        "local_bytes": sum(file.stat().st_size for file in directory.rglob("*") if file.is_file()),
        "coverage_note": "Exact trade evidence covers sampled intervals only.",
    }
