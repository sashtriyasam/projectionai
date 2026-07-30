# Changelog

## v0.1.0.dev0 (Unreleased)

### Added

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
- Comprehensive test suite with 390+ tests covering domain, editor, infrastructure, and core layers

### Changed

- N/A (initial release)

### Fixed

- N/A (initial release)

### Deprecated

- N/A (initial release)

### Removed

- N/A (initial release)

### Security

- N/A (initial release)
