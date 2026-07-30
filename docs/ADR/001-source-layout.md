# ADR-001: Source Layout with src/ Namespace Packages

## Status

Accepted

## Context

The project needed a standardised source layout that supports clean imports, test isolation, and future monorepo expansion. Two common approaches exist: a flat layout where the Python package sits at the repository root, and a `src/` layout where the package is nested under a `src/` directory.

## Decision

Use the `src/` layout with `src/projectionai/` as the package root, configured via `[tool.setuptools.packages.find]` with `where = ["src"]`.

## Consequences

- **Positive**: Tests run against the installed package, not the source tree — prevents accidental imports from unbuilt code.
- **Positive**: Clean separation between project metadata (pyproject.toml, README) and actual source code.
- **Positive**: Easier to add companion packages (e.g., `projectionai-plugins`) in a monorepo later.
- **Negative**: One extra directory level (`src/projectionai/` vs `projectionai/`).
- **Negative**: Requires explicit `find` configuration in `pyproject.toml`.
