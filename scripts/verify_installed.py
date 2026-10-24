"""Image gate: ensure the non-editable application wheel matches copied source."""

from importlib.util import find_spec
from pathlib import Path


def main() -> None:
    source = Path("backend/src/pripre").resolve()
    spec = find_spec("pripre")
    if spec is None or spec.origin is None:
        raise RuntimeError("application package is not installed")
    installed = Path(spec.origin).resolve().parent
    if installed == source:
        raise RuntimeError("artifact check requires a non-editable application install")
    files = list(source.rglob("*.py"))
    if not files:
        raise RuntimeError("no application source files found")
    for file in files:
        destination = installed / file.relative_to(source)
        if not destination.is_file() or destination.read_bytes() != file.read_bytes():
            raise RuntimeError(
                f"installed application differs from source: {file.relative_to(source)}"
            )
    print(f"Installed application matches all {len(files)} source files")


if __name__ == "__main__":
    main()
