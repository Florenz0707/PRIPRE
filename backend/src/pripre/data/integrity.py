"""Stable research identity shared by offline reports and live model revisions."""

import hashlib
import json
from datetime import date

from pripre.config import AppConfig


def research_fingerprint(config: AppConfig) -> str:
    settings = {
        "instrument": config.instrument.model_dump(mode="json"),
        "source": config.source.model_dump(mode="json"),
        "grid": config.grid.model_dump(mode="json"),
        "paths": config.runtime.paths,
        "seed": config.runtime.seed,
    }
    fingerprint = hashlib.sha256(json.dumps(settings, sort_keys=True).encode())
    directory = config.history.data_dir / config.instrument.id / config.source.provider / "trades"
    for file in sorted(directory.glob("*.npz")):
        if config.history.start <= date.fromisoformat(file.stem) <= config.history.end_date():
            fingerprint.update(file.name.encode())
            fingerprint.update(file.read_bytes())
    return fingerprint.hexdigest()
