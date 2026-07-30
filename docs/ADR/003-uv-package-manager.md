# ADR-003: uv as Package Manager

## Status

Accepted

## Context

The project needed a fast, reliable Python package manager with lockfile support. Traditional `pip` + `venv` workflows are slow (especially on CI) and lack a standard lockfile format. Tools like Poetry, PDM, and uv were evaluated.

## Decision

Use `uv` (Astral) for dependency management and virtual environment creation.

- `uv sync` replaces `pip install -e ".[dev]"`.
- `uv.lock` provides reproducible installs.
- CI uses `astral-sh/setup-uv` GitHub Action.

## Consequences

- **Positive**: ~10x faster installs compared to pip, both locally and on CI.
- **Positive**: Native lockfile support (`uv.lock`) for reproducible builds.
- **Positive**: `uv` can generate `requirements.txt` for compatibility.
- **Negative**: Newer tool — smaller community and fewer docs compared to pip.
- **Negative**: Developers must install uv separately (pip install uv or standalone installer).
