# ProjectionAI Roadmap

> Status tracking for ProjectionAI development milestones. Release notes
> are kept in [CHANGELOG.md](CHANGELOG.md); design decisions in
> [docs/ADR/](docs/ADR/).

## Milestone 0 — Foundation (v0.1.0)

**Goal:** Project skeleton, tooling, CI, empty packages compile and pass lint.

- [x] Directory structure and `__init__.py` files
- [x] `pyproject.toml` with build system and tool config
- [x] Linting (ruff), formatting (black, isort), type checking (mypy) — all green
- [x] `pre-commit` hooks
- [x] `tox` or `nox` for multi-env testing
- [x] `.gitignore`, `.env.example`
- [x] Basic `README.md`
- [x] GitHub repository with branch protection
- [x] GitHub Actions CI (lint, type-check, test)

## Milestone 1 — Core Framework (v0.2.0)

**Goal:** All abstractions defined, plugin system works, event bus works, managers operational.

- [x] `core/` — base classes, capability-based plugin registry, event bus, config, errors, logging
- [x] `services/` — all interfaces defined
- [x] `domain/` — all models defined (scene graph, project, asset, job, command, workspace)
- [x] Plugin discovery via entry points and directory scanning
- [x] Plugin lifecycle (initialize → shutdown)
- [x] Event bus with weak references and async dispatch
- [x] Config loading from `.env` and environment variables
- [x] Structured logging (console + rotating file)
- [x] `managers/` — 8 managers implemented and wired (Settings, Plugin, Command, Scene, Asset, Job, Project, Workspace)
- [x] `ManagerRegistry` with dependency injection
- [x] Capability-based plugin system (7 capability protocols)
- [x] Event types covering all manager operations (40+ events)
- [x] Error hierarchy for all manager domains (30+ error types)
- [x] Manager unit tests (5 test files)
- [x] `app.py` wiring all managers in dependency-safe order

## Milestone 2 — Vision Pipeline (v0.3.0)

**Goal:** Camera capture, surface detection, geometry estimation.

- [ ] Camera interface (USB camera, file input)
- [ ] OpenCV pipeline skeleton: `process_frame` flow
- [ ] Feature detection (SIFT/ORB) for correspondence estimation
- [ ] Planar surface detection (Hough transform / RANSAC)
- [ ] Pose estimation (PnP solver)
- [x] Camera calibration workflow (checkerboard pattern)
- [ ] Mesh reconstruction from depth / multi-view (Open3D integration)

## Milestone 3 — AI Integration (v0.4.0)

**Goal:** At least one AI provider fully working for image generation.

- [ ] Gemini provider: `generate` and `chat` implemented
- [ ] OpenAI provider: DALL-E 3 / GPT-4o image generation
- [ ] Anthropic provider (text generation)
- [ ] Replicate provider (Stable Diffusion, Flux)
- [ ] Provider selection via config
- [ ] Streaming support (`generate_stream`, `chat_stream`)
- [ ] Rate limiting and retry with exponential backoff
- [ ] Content filtering error handling
- [ ] Chat interface for iterative prompt refinement
- [ ] Image-to-image workflows (variations, inpainting)

## Milestone 4 — Rendering Engine (v0.5.0)

**Goal:** 3D viewport with scene rendering and warp preview.

- [ ] ModernGL context creation (viewport widget)
- [ ] Scene graph rendering (meshes, poses, cameras)
- [ ] Shader pipeline (vertex → fragment for mesh rendering)
- [ ] Texture loading and rendering
- [ ] Off-screen rendering for warp computation
- [ ] Warp engine: texture → target mesh projection
- [ ] Interactive camera controls (orbit, pan, zoom)
- [x] Grid, axis helpers, selection overlays

## Milestone 5 — Calibration (v0.6.0)

**Goal:** Full calibration workflow — manual and automatic.

- [x] Manual calibration UI (click correspondence points)
- [x] Point picking in 3D viewport
- [x] Calibration computation (solve PnP, minimize reprojection)
- [x] Calibration quality metrics display
- [ ] Automatic calibration (ICP registration)
- [ ] Structured light / Gray-code projection for auto-calibration
- [ ] Single-projector calibration complete
- [x] Calibration persistence (save/load to project)

## Milestone 6 — UI Application (v0.7.0)

**Goal:** Complete desktop application with all workflows wired.

- [x] Main window layout (menu bar, toolbars, dock panels)
- [x] 3D viewport widget in center
- [x] Scene panel (object list, properties)
- [ ] Surface panel (detected surfaces, selection)
- [x] Content panel (generated content browser)
- [ ] Chat panel (AI chat interface)
- [x] Preview panel (projected output preview)
- [x] Workspace manager integration (persistent layouts)
- [ ] Scan workflow (camera → surface detection → scene)
- [ ] Generate workflow (prompt → AI → content)
- [ ] Warp workflow (content → surface → warped)
- [x] Project save/load via ProjectManager
- [x] Undo/redo via CommandManager
- [ ] Background job progress via JobManager

## Milestone 7 — Display & Output (v0.8.0)

**Goal:** Hardware display management and safe projection output.

- [x] Display topology detection (multi-display / projector classification)
- [x] Display change tracking and typed change events
- [x] Display validation gates (renderer ready, projector present, resolution)
- [x] Output sessions (preview → live) with safe switching
- [x] Emergency blackout
- [ ] Real display full-screen output window
- [ ] Installer packaging (NSIS / WiX for Windows, DMG for macOS)

## Milestone 8 — Polish & Performance (v0.9.0)

**Goal:** Production-ready performance, error handling, UX.

- [ ] Real-time performance optimization (60 fps preview)
- [ ] GPU memory management
- [ ] Graceful error boundaries everywhere
- [ ] Toast notification system
- [ ] Progress indicators for long operations
- [ ] Keyboard shortcuts
- [ ] Dark/light theme
- [ ] Settings dialog (backed by SettingsManager)
- [ ] Export to video / image sequence
- [ ] Auto-update mechanism

## Milestone 9 — Multi-Projector & Collaboration (v1.0+)

**Goal:** Professional projection mapping features.

- [ ] Multi-projector calibration (projector overlap, blending)
- [ ] Edge blending (soft-edge masks)
- [ ] Color matching across projectors
- [ ] Projector output window (full-screen on second display)
- [ ] Network synchronization for multi-machine setups
- [ ] Timeline / media server integration
- [ ] DMX / Art-Net control
- [ ] Live input mixing (camera → projector)
- [ ] Remote control API
- [ ] Collaborative editing via WebSocket

## v1.0.0 Release

- [ ] All milestone features complete
- [ ] Comprehensive test suite (80%+ coverage)
- [ ] User documentation and tutorials
- [ ] Website and marketing materials
- [ ] Distribution channel (website, direct download)
