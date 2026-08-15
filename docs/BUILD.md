# Building ProjectionAI from Source

This document covers building and running ProjectionAI from a source
checkout. For producing the distributable Windows bundle, see
[PACKAGING.md](PACKAGING.md).

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Windows 10/11 (the packaging pipeline targets Windows; the app
  itself is cross-platform)

## Development Setup

```powershell
uv sync --extra dev
```

This installs the runtime dependencies plus the dev extra
(pytest, ruff, mypy, pre-commit, tox, PyInstaller, Pillow).

## Running from Source

```powershell
uv run projectionai            # or: python -m projectionai
```

Optional flags:

| Flag                | Purpose                           |
| ------------------- | --------------------------------- |
| `--version`         | Print version and exit            |
| `--config PATH`     | Use an explicit config file       |
| `--log-level LEVEL` | Override the configured log level |

## Tests, Lint, Type Checks

```powershell
# Full test suite with coverage gate (>= 60%)
uv run pytest -q

# UI tests headless
$env:QT_QPA_PLATFORM = "offscreen"

# Lint + format
uv run ruff check .
uv run ruff format --check .

# Strict type check
uv run mypy src/projectionai
```

## Project Layout

```
src/projectionai/   # Main package (src layout)
packaging/          # PyInstaller spec, launcher, icon generator
scripts/            # Build automation (build_package.ps1)
installer/          # Inno Setup script (optional, see PACKAGING.md)
tests/              # Unit tests
docs/               # Architecture, ADRs, hardware validation, packaging
```

## CI

The repository ships a GitHub Actions workflow (`.github/workflows/ci.yml`)
that runs lint, type check, tests with coverage, and an import/build check
on every push.
