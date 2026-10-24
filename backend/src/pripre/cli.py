"""Explicit, opt-in public data acquisition and reproducible research commands."""

import argparse
import json
from pathlib import Path

from pripre.backtesting.experiments import run_experiments
from pripre.backtesting.research import run_research
from pripre.config import load_config
from pripre.data.history import collect_history, dataset_summary


def main() -> None:
    parser = argparse.ArgumentParser(prog="pripre")
    parser.add_argument("command", choices=["collect", "inspect", "backtest", "experiments"])
    parser.add_argument("--config", type=Path, default=Path("config/default.toml"))
    args = parser.parse_args()
    config = load_config(args.config)
    commands = {
        "collect": collect_history,
        "inspect": dataset_summary,
        "backtest": run_research,
        "experiments": run_experiments,
    }
    result = commands[args.command](config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
