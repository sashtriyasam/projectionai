# Phase 7.5 — DEPENDENCY-MAP — Pattern Presentation Integration

## Existing Presentation Paths

### Path A: Qt QLabel Path (`QtPatternProjector`)

- **File:** `src/projectionai/infrastructure/display/qt.py`
- **Mechanism:** `QLabel` + `QPixmap.fromImage()` in a `_ProjectionWindow`
- **Used by:** `SynchronizedCaptureSession` (calibration capture)
- **Capabilities:** Fullscreen, display selection via `screen_index`, blank via black paint
- **Limitations:** No frame boundary/vsync, no GPU acceleration, QLabel scaling

### Path B: QOpenGLWidget Path (`GLOutputWindow`)

- **File:** `src/projectionai/infrastructure/renderer/output_window.py`
- **Mechanism:** `QOpenGLWidget` + ModernGL + `PatternPass` + `ProjectionPass`
- **Used by:** `OutputManager` for live/preview output
- **Capabilities:** GPU-accelerated, proper GL context, fullscreen, freeze, blackout, projection warp
- **Swap interval:** `fmt.setSwapInterval(1)` — requests vsync from driver

## Decision: Production Path

**Use Path A (`QTPatternPresentationTarget` wrapping `QtPatternProjector`) as the production presentation path for calibration patterns.**

Rationale:

- `QTPatternPresentationTarget` wraps `QtPatternProjector` to satisfy the `PatternPresentationTarget` protocol
- Uses `QLabel`/`QPixmap` with `Format_Grayscale8` to display arbitrary grayscale calibration images at native resolution
- `GLOutputWindow` is **not** the production path for calibration patterns — it only supports predefined `PatternKind` test patterns (solid colours, grids, etc.) via `PatternPass`, not arbitrary grayscale images from `CalibrationSequence`
- `OutputManager` continues to manage display routing, validation, and safety

### Correction Note (Phase 7.5 doc accuracy)

> Earlier drafts stated Path B (`GLOutputWindow`) was the production path.
> This was incorrect: `GLOutputWindow` can only render predefined `PatternKind`
> patterns via `PatternPass`, not the arbitrary grayscale images produced by
> `CalibrationSequence`. The actual production path is `QTPatternPresentationTarget`
> wrapping `QtPatternProjector`.

## Key Components to Build

| Component                    | Responsibility                            | Consumes                                           |
| ---------------------------- | ----------------------------------------- | -------------------------------------------------- |
| `PatternPresentationSession` | Orchestrate pattern sequence presentation | `CalibrationSequence`                              |
| `PatternPresentationTarget`  | Display routing + resolution validation   | `DisplayManager`, display_id                       |
| `PatternPresentationBarrier` | Frame boundary abstraction                | `QOpenGLWidget.frameSwapped` or monotonic fallback |

## Dependency Flow

```
CalibrationSequence (Phase 6.3)
    ↓ patterns
PatternPresentationSession
    ↓ select target
PatternPresentationTarget (Phase 7.2 device selection)
    ↓ display geometry + fullscreen
QTPatternPresentationTarget (wraps QtPatternProjector)
    ↓ QLabel/QPixmap + Format_Grayscale8
Pattern image displayed at native resolution
    ↓ best-effort monotonic timestamp (conceptual — deferred to Phase 8)
CaptureSession (Phase 6.4) consumes timestamp
```

> **Note:** `PatternPresentationBarrier` uses `time.monotonic_ns()` as a
> best-effort approximation — hardware vsync observation is not yet implemented.

## Safety Boundaries

- `OutputManager` remains authoritative for safety (BLACKOUT, FREEZE, SAFE STOP)
- `PatternPresentationSession` does NOT create parallel safety state machine
- Presentation session uses `OutputManager` for display routing and validation

## What NOT to Change

- `PatternEngine` (Phase 6.3) — pattern generation unchanged
- `GrayCodePatternGenerator` — math unchanged
- `CorrespondenceMatcher` — decoder unchanged
- `ReconstructionBackend` — solver unchanged
- `WarpMesh` — warp math unchanged
- `OutputManager` safety architecture — authoritative

## Phase 7.2 Integration

- Display selection from `DeviceSelectionViewModel`
- Secondary display geometry from `DisplayManager`
- Resolution validation against `DisplayInfo.current_mode`
- Fullscreen via `DisplayManager.set_fullscreen()`

## Phase 7.1 Integration

- `ProductionWorkflow` stages: warp → persist
- Presentation happens during "warp" stage
- Cancellation from workflow → presentation session stops safely
