# Hardware Validation

## Overview

The hardware-validation workflow turns the existing projector-calibration
pipeline (gray-code structured light) into a reproducible, self-contained
validation run: connect a camera and projector display, capture the pattern
sequence, decode correspondences, calibrate, and produce a single report
with metrics, visualizations, and exportable artifacts.

It lives in `calibration/hardware_validation/` and composes existing
building blocks — it **adds no new calibration algorithms**:

```
calibration/hardware_validation/
├── runner.py          ← ValidationRunner: the 9-step workflow
├── models.py          ← CaptureSequence, ValidationMetrics, CalibrationReport
├── environment.py     ← EnvironmentInfo, collect_environment
├── visualization.py   ← correspondence/coverage/contact-sheet/histogram renders
├── export.py          ← JSON / PNG / A4 PDF / zip calibration package
└── __init__.py        ← package exports

infrastructure/display/ ← DisplayInfo, list_displays, QtPatternProjector
```

Design goals:

- **No new algorithms.** The runner orchestrates
  `GrayCodeProjectorCalibration`, `PatternCaptureSession`,
  `ReprojectionValidator`, and `ProjectorCornerEstimator` as-is.
- **Always returns a report.** Success → `COMPLETED`; failure/cancellation →
  `FAILED`/`CANCELLED` with collected errors. Callers never hit an exception
  from `run()`.
- **Pure exporters.** Every export function reads a report and writes files —
  fully testable with a synthetic report and no hardware.
- **Self-contained artifacts.** A zip package bundles the JSON report,
  calibration matrices, captured frames, and visualization PNGs.

---

## The 9-step workflow

`ValidationRunner.run()` executes, in order:

| #   | Step                | Result                                                  |
| --- | ------------------- | ------------------------------------------------------- |
| 1   | `connect_camera`    | Enumerate cameras, open the requested (or first) one    |
| 2   | `connect_projector` | Resolve the `PatternProjector` (injected or Qt-based)   |
| 3   | `detect_displays`   | Enumerate displays; warn (not fail) when none are found |
| 4   | `select_projector`  | Pick the projector resolution (explicit or display)     |
| 5   | `build_sequence`    | Build the gray-code pattern sequence                    |
| 6   | `capture`           | Project each pattern and capture a frame (timed)        |
| 7   | `decode`            | Decode correspondences from the captured frames         |
| 8   | `calibrate`         | Calibrate projector + validate reprojection + corners   |
| 9   | `report`            | Freeze the session into a `CalibrationReport`           |

Each step is timed into `report.step_times` and drives the live
`HardwareValidationSession` (status, progress, status text) for UI use.

### Validation gates

The `ReprojectionValidator` applies the same thresholds as the rest of the
pipeline:

- `max_rms` = 1.0 px
- `min_coverage` = 0.8

`ValidationMetrics.passed` reflects the combined gates; `corner_error` is the
RMS projector-pixel error of known 3D points when
`expected_corner_points`/`expected_corner_pixels` are supplied.

---

## Data model

| Type                        | Role                                                                |
| --------------------------- | ------------------------------------------------------------------- |
| `CaptureSequence`           | Frozen record of a capture run (validates shape/timing consistency) |
| `ValidationMetrics`         | Quality gates: RMS, coverage, corner error, confidence, counts      |
| `CalibrationReport`         | Frozen, self-contained report of a run                              |
| `HardwareValidationSession` | Mutable live state machine driven by the runner                     |
| `EnvironmentInfo`           | Host snapshot (OpenCV/Python versions, CPU, memory, timing)         |
| `DisplayInfo`               | One connected display (index, name, resolution, primary)            |

A `CalibrationReport` aggregates the environment snapshot, optional capture,
correspondences, calibration, validation, metrics, per-step timings, and
warnings/errors — everything needed to audit or reproduce a run.

---

## Exports

| Function                     | Output                                                                        |
| ---------------------------- | ----------------------------------------------------------------------------- |
| `export_report_json`         | The full report as a JSON document                                            |
| `export_captured_images`     | `frame_000.png`, … per captured gray-code frame                               |
| `export_visualizations`      | correspondence/coverage/contact-sheet/histogram PNGs                          |
| `export_report_pdf`          | Multi-page A4 PDF: summary + visualization pages                              |
| `export_calibration_package` | Zip bundle: `report.json`, `calibration.json`, `visualizations/`, `captures/` |

Exporters use only the standard library plus Pillow (already a project
dependency) — no new dependencies. PDF pages are rendered at A4 (794×1123 @
96 dpi) with a 60 px margin and a bundled/TrueType font fallback.

---

## Testing

The workflow is covered by 79 unit tests, all in-process and hardware-free:

- **Runner e2e** — drives the full 9-step workflow against the synthetic
  scene (`tests/unit/calibration/_synthetic_scene.py`): a stub camera renders
  what a calibrated camera sees of each projected gray-code pattern, and a
  stub projector records every shown pattern. Asserts `COMPLETED`, all 9
  steps timed, ground-truth metrics (RMS < 1 px, coverage > 0.8,
  corner error < 2 px), failure paths (`FAILED`, `CANCELLED`).
- **Models / environment / visualization / export** — pure unit tests with
  synthetic data, no hardware.
- **Display** — Qt `offscreen` platform plugin selected before the
  `QApplication` is created, so enumeration/projection tests run headless on
  every OS, including CI.

Run everything:

```bash
pytest -q --no-cov -p no:cacheprovider
```
