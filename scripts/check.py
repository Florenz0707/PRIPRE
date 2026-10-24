"""Run all project gates from any working directory; stop on the first failure."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = (
    ("uv", "lock", "--check"),
    ("pnpm", "install", "--frozen-lockfile"),
    ("uv", "run", "--locked", "pytest"),
    ("pnpm", "test"),
    ("pnpm", "build"),
    ("pre-commit", "run", "--all-files"),
    ("docker", "compose", "config", "--quiet"),
)


def main() -> None:
    for command in COMMANDS:
        print(f"\n>>> {' '.join(command)}", flush=True)
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
