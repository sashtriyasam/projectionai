# Changelog

## [Unreleased]

### Added

- Open-source governance: `LICENSE` (MIT), `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
- GitHub templates: issue templates (bug report, feature request, question), pull request template
- CI pipeline in `.github/workflows/ci.yml` (lint, type-check, test with coverage, build & import check)
- Release automation: release-drafter workflow + config
- Real application screenshot in `screenshots/`, embedded in the README
- Root `ROADMAP.md` with milestone-by-milestone tracking
- Calibration subsystem documentation in `docs/Architecture.md`

### Changed

- Rewrote `README.md` with project overview, features, quick start, development guide, architecture diagram, and coding standards
- Licensed metadata in `pyproject.toml` pinned to SPDX `MIT` (PEP 639)

### Fixed

- License metadata inconsistency: `pyproject.toml` declared Proprietary while `LICENSE`, README, and CHANGELOG stated MIT

## [0.1.0] - 2026-07-31

### Added

- Initial release of ProjectionAI
- Initial project scaffold with `src/` layout
- PySide6 UI framework with main window and viewport widget
- ModernGL-based render pipeline with ordered passes (background, scene, grid, selection, overlay, debug)
- Domain models: scene, project, surface, calibration, geometry, material, asset, job, workspace
- Service layer interfaces for AI, vision, renderer, calibration, storage
- Infrastructure implementations for AI providers (Gemini, OpenAI, Anthropic, Replicate)
- Infrastructure implementations for vision (OpenCV) and persistence (SQLite)
- Plugin-based AI provider architecture with optional dependency groups
- Type-safe event bus for decoupled cross-layer communication
- Camera controller with orbit/pan/zoom interaction
- Editor subsystems: selection manager, snap manager, gizmo manager, transform tools, input manager
- Concrete managers: scene, asset, project, job, plugin, settings, workspace, command
- Projector calibration pipeline with validation
- Comprehensive test suite with 399 tests covering domain, editor, infrastructure, and core layers

### Changed

- License changed from Proprietary to MIT

### Fixed

- N/A (initial release)

### Deprecated

- N/A (initial release)

### Removed

- N/A (initial release)

### Security

- N/A (initial release)
