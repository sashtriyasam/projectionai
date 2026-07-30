# ADR-002: Ruff + MyPy Strict Mode for Code Quality

## Status

Accepted

## Context

The project needed a code quality toolchain that enforces consistent formatting, catches bugs statically, and minimises configuration overhead. Traditional Python tooling uses separate tools: Black (formatting), isort (imports), Flake8 (linting), and optionally MyPy (type checking).

## Decision

Use Ruff for all linting and formatting (replacing Black, isort, and Flake8) combined with MyPy in strict mode for type checking.

- Ruff configured with `line-length = 88`, target `py312`, and selects including E, W, F, I, N, UP, B, SIM, ARG, RUF.
- MyPy configured with `strict = true`, `warn_unused_ignores = true`, and third-party package ignores for cv2, open3d, PySide6, etc.

## Consequences

- **Positive**: Single dependency for linting + formatting vs four separate tools.
- **Positive**: MyPy strict mode catches real bugs (type mismatches, missing returns, unused ignores).
- **Positive**: Ruff is orders of magnitude faster than Flake8.
- **Negative**: ~500 type annotations required across the codebase to satisfy strict mode.
- **Negative**: Some third-party packages lack stubs, requiring `ignore_missing_imports` overrides.
