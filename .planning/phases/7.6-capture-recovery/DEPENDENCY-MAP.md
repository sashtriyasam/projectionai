# Phase 7.6 — Dependency Map

## Contracts Audited (via codegraph)

### SynchronizedCaptureSession (`sync.py:67`)

- **Purpose**: Per-pattern presentation → capture → validation → retry
- **Takes**: `FrameSource`, `camera_id: str`, `PatternProjector`, `SyncConfig`
- **Key methods**: `capture_sequence(sequence) -> tuple[CalibrationFrame, ...]`
- **Metrics**: `CaptureMetrics` (latencies_ms, p50/p95/p99, retries, mismatches, dropped)
- **15 callers** — must NOT duplicate

### PatternPresentationSession (`pattern_presentation.py:197`)

- **Purpose**: Managed display lifecycle (enter_fullscreen → show pattern → hide → exit)
- **Takes**: `PatternPresentationTarget` (protocol: enter_fullscreen, show_pattern, exit_fullscreen, hide)
- **Key methods**: `show(sequence)`, `show_single(pattern)`, `hide()`, `state` (PresentationState with timestamp_ns)
- **17 callers** — compose with, do not duplicate

### CalibrationFrame (`calibration_session.py:364`)

- **Purpose**: Stamped frame with pattern metadata
- **Fields**: `capture: CameraCapture`, `pattern: CalibrationPattern`
- **15 callers**

### CalibrationPattern (`calibration_session.py:110`)

- **Purpose**: Single pattern in a sequence
- **Fields**: `pattern_id: int`, `image`, `display_id`, `sequence_id`

### CalibrationSequence (`calibration_session.py:167`)

- **Purpose**: Ordered collection of patterns
- **Fields**: `sequence_id`, `patterns: list[CalibrationPattern]`

### CameraCapture (`calibration_session.py:282`)

- **Purpose**: Raw capture metadata
- **Fields**: `frame`, `display_id`, `projector_state`, `capture_latency_ms`

### CameraManager (`camera_manager.py:48`)

- **Purpose**: Camera lifecycle management
- **Key method**: `get_camera(camera_id) -> Camera`, `is_open`

### QtPatternProjector (`qt.py:96`)

- **Purpose**: Qt display implementation
- **Implements**: `PatternProjector` (show, hide), `PatternPresentationTarget` (fullscreen, show_pattern, exit_fullscreen, hide, resolution)

### PatternProjector protocol (`projector_calibration.py`)

- **Fields**: `resolution: tuple[int, int]`, `show(image)`, `hide()`

### Frame (`services/camera.py`)

- **Purpose**: Camera frame with metadata
- **Key fields**: `image: ndarray`, `timestamp: float`, `timestamp_ns: int`, `camera_id: str`, `frame_number: int`, `sequence_id`, `pattern_id`, `capture_latency_ms`, `presentation_timestamp_ns`, `projector_state`

### ProductionWorkflow (`calibration_workflow.py`)

- **Purpose**: Global calibration state machine
- **Must NOT duplicate** — CaptureState maps to workflow stage externally

## Composition Plan

```
CaptureSession (NEW — 7.6)
├── PatternPresentationSession (7.5 — display lifecycle)
│   └── PatternPresentationTarget (7.5 — protocol)
│       └── QtPatternProjector (7.3 — Qt impl)
├── FrameSource (Phase 6 — camera capture)
│   └── CameraManager (Phase 6)
├── CalibrationSequence/Pattern (Phase 6 — domain)
└── CalibrationFrame (Phase 6 — output)

SynchronizedCaptureSession (Phase 6 — NOT used directly)
  Its per-pattern mechanics are reimplemented in CaptureSession
  to support partial recovery and disconnect detection.
```

## What CaptureSession Adds (vs. SynchronizedCaptureSession)

| Feature                         | SynchronizedCaptureSession | CaptureSession (7.6)                       |
| ------------------------------- | -------------------------- | ------------------------------------------ |
| Per-pattern capture             | ✅                         | ✅                                         |
| Retry with bounds               | ✅                         | ✅                                         |
| Latency bounds                  | ✅                         | ✅                                         |
| Metrics (latency, retries)      | ✅                         | ✅                                         |
| **State machine**               | ❌                         | ✅ CaptureState enum                       |
| **Camera disconnect detection** | ❌                         | ✅ `_check_camera()` between patterns      |
| **Partial sequence recovery**   | ❌ (raises, losing frames) | ✅ Returns partial_frames                  |
| **Enhanced metrics**            | ❌ (just latencies)        | ✅ frames_accepted/rejected/stale/timeouts |
| **Safe cancellation**           | ❌ (CancelledError only)   | ✅ Cooperative cancel flag                 |
| **Presentation integration**    | ❌ (uses PatternProjector) | ✅ Uses PatternPresentationSession         |
