# Phase 7.7 — Decode / Reconstruction / Solve UX: PLAN.md

**Created:** 2026-08-28
**Status:** PLANNING

---

## Goal

Replace placeholder decode/reconstruct/solve stages in `ProductionWorkflow` with real Phase 6 engine integrations, surface technical metrics and quality gates in the UI, and classify errors clearly.

## Non-Goals (7.8 owns these)

- Polished final result review/approval UX
- Full calibration presentation
- Final approve/reject screen

---

## Work Waves

### Wave 1 — Core Pipeline Integration (parallel, independent)

#### Task 1.1: Wire Decode Stage

**File:** `src/projectionai/application/calibration_workflow.py`
**What:** Replace placeholder `_run_decode()` with real `StructuredLightDecoder.decode()` call.
**Input:** `CalibrationFrame[]` from capture stage result
**Output:** `CorrespondenceSet` stored in `ctx.data["correspondence_set"]`
**Constraints:**

- Use existing `StructuredLightDecoder` — no new decode logic
- Preserve error handling: `StructuredLightDecodeError` → stage FAILED
- Store decode metrics (valid_ratio, frame count) in stage result metadata
- Source mode: if `is_synthetic`, display "SOURCE: SYNTHETIC"

#### Task 1.2: Wire Reconstruct Stage

**File:** `src/projectionai/application/calibration_workflow.py`
**What:** Replace placeholder `_run_reconstruct()` with real `ReconstructionBackend.reconstruct()` call.
**Input:** `CorrespondenceSet` + `CalibratedCamera` + `SurfacePlane`
**Output:** Reconstruction results collected by sequence ID and distinct orientation — multiple `ReconstructionResult` objects keyed by sequence ID, not a single `ctx.data["reconstruction"]` value.
**Constraints:**

- Use `ReconstructionBackendFactory.create(mode)` for backend selection
- Preserve error handling: `ReconstructionError` → stage FAILED
- Store reconstruction metrics (point count, backend name) in stage result metadata
- Respect measured backend decision (reference = production default)

#### Task 1.3: Wire Solve Stage

**File:** `src/projectionai/application/calibration_workflow.py`
**What:** Replace placeholder `_run_solve()` with real `solve_calibration()` call.
**Input:** `tuple[ReconstructionResult, ...]` (2+ orientations required)
**Output:** `CalibrationResult` stored in workflow.calibration_result
**Constraints:**

- Use existing `solve_calibration()` from `calibration/solver.py`
- Preserve error handling: `CalibrationSolveError` → stage FAILED
- Store solve metrics (RMS, coverage, confidence, condition_number) in stage result metadata
- Orientation diversity check must be visible in error message
- Never allow single-plane or near-degenerate to appear successful

#### Task 1.4: Wire Capture Stage

**File:** `src/projectionai/application/calibration_workflow.py`
**What:** Replace placeholder `_run_capture()` with real `CaptureSession.capture_sequence()` call.
**Input:** `CalibrationSequence` from prepare stage
**Output:** `CaptureResult.frames` → `CalibrationFrame[]` stored in context
**Constraints:**

- Use existing `CaptureSession` from Phase 7.6
- This stage requires a `FrameSource` — may need to accept it as a parameter or from context
- Preserve error handling: `CameraDisconnectError`, `CaptureTimeoutError` → stage FAILED
- Store capture metrics (frames accepted/rejected, latencies) in stage result metadata
- If no real camera available (synthetic mode), keep placeholder behavior

### Wave 2 — Metrics Display & Quality Gates (depends on Wave 1)

#### Task 2.1: Source Mode Display

**File:** `src/projectionai/ui/widgets/calibration_progress_widget.py`
**What:** Add prominent source mode indicator at top of widget.
**Display:** `SOURCE: SYNTHETIC | REPLAY | LIVE CAMERA`
**Constraints:**

- Never imply LIVE hardware when source is synthetic or replay
- Read from `workflow.is_synthetic` flag
- Also show hardware validation status

#### Task 2.2: Decode Metrics Display

**File:** `src/projectionai/ui/viewmodels/calibration_progress.py` + widget
**What:** Surface decode stage metrics in ViewModel and widget.
**Metrics:** sequence_id, pattern_count, captured_frame_count, accepted/rejected, valid_ratio, threshold
**Quality states:** READY / RUNNING / GOOD / WARNING / FAILED
**Constraints:**

- Do not reduce all quality info to a single checkmark
- Show valid_ratio with threshold comparison
- Show accepted vs rejected counts

#### Task 2.3: Reconstruction Metrics Display

**File:** `src/projectionai/ui/viewmodels/calibration_progress.py` + widget
**What:** Surface reconstruction stage metrics.
**Metrics:** backend_name, point_count, valid_point_ratio, reconstruction_duration
**Constraints:**

- Explicitly show NATIVE or REFERENCE backend
- Never silently claim native acceleration

#### Task 2.4: Solver Metrics Display

**File:** `src/projectionai/ui/viewmodels/calibration_progress.py` + widget
**What:** Surface solver stage metrics.
**Metrics:** orientation_count, orientation_ids, angular_separation, condition_number, fx, fy, cx, cy, reprojection_rms, coverage, confidence, solver_duration
**Constraints:**

- Show orientation diversity visibly
- If diversity insufficient, block solve and explain why
- Show per-plane consistency when available

#### Task 2.5: Error Classification Display

**File:** `src/projectionai/ui/viewmodels/calibration_progress.py` + widget
**What:** Map typed errors to user-friendly messages.
**Categories:**

- CAPTURE_DATA_ERROR
- DECODE_ERROR
- RECONSTRUCTION_ERROR
- DEGENERATE_GEOMETRY
- INSUFFICIENT_ORIENTATION_DIVERSITY
- SOLVER_ERROR
- QUALITY_THRESHOLD_FAILURE
- HARDWARE_PENDING
- CANCELLED
  **Constraints:**
- Preserve original technical error for diagnostics
- Show WHY solve fails (e.g., "Required >=15°, measured 4.8°")
- Never just say "Calibration failed"

### Wave 3 — Cancellation, Tests, Quality Gates

#### Task 3.1: Cancellation Integration

**File:** `src/projectionai/application/calibration_workflow.py`
**What:** Ensure decode/reconstruct/solve stages check `_cancel_requested` flag.
**Constraints:**

- Check cancel before starting each stage
- Wrap synchronous engine calls in `asyncio.to_thread()` if they block
- Verify cancel stops cleanly

#### Task 3.2: Tests — Decode

**File:** `tests/unit/services/test_decode_reconstruct_solve.py`
**Tests:**

- Valid capture sequence → CorrespondenceSet
- Wrong sequence → StructuredLightDecodeError
- Missing pattern → error
- Duplicate pattern → error
- Decode quality metrics (valid_ratio)
- Invalid correspondence (out of bounds)

#### Task 3.3: Tests — Reconstruct

**Tests:**

- Valid correspondence → ReconstructionResult
- Zero/invalid points → ReconstructionError
- Backend selection visibility (reference vs native)
- Degenerate geometry
- NaN/Inf filtering
- Result metrics

#### Task 3.4: Tests — Solver

**Tests:**

- Valid two-orientation solve → CalibrationResult
- Insufficient diversity → error with message
- Frontal/frontal rejection
- 5°/5° rejection
- Orientation IDs visible
- Condition failure → error
- Solver failure → error
- Result metrics (RMS, coverage, confidence)

#### Task 3.5: Tests — Workflow Integration

**Tests:**

- Real decode stage produces CorrespondenceSet
- Real reconstruct stage produces ReconstructionResult
- Real solve stage produces CalibrationResult
- Stage result propagation
- Progress updates
- Failure propagation
- Cancellation
- Retry bounded

#### Task 3.6: Tests — UI Metrics

**Tests:**

- Technical metrics visible in ViewModel
- Source mode visible
- Warnings visible
- Failures visible
- Hardware-pending visible

#### Task 3.7: Quality Gates

**Commands:**

```
uv run ruff check src/
uv run ruff format --check src/
uv run mypy --strict src/projectionai/
```

**Plus regression suites:**

- test_structured_light_decoder
- test_capture_session
- test_capture_sync
- test_reconstruction_backends
- test_reconstruction_stage
- test_solver
- test_calibration_workflow
- test_device_selection
- test_surface_setup
- test_pattern_presentation
- calibration progress UI tests

---

## Verification Loop

After each wave:

1. Run focused tests → all pass
2. Run regression suites → all pass
3. Run mypy --strict → clean
4. Run ruff check + format → clean
5. Verify UI responsiveness (no blocking Qt event loop)
6. Verify hardware gates unchanged

---

## Constraints

- Do NOT touch `D:\PROJECTIONAI-camera`
- Do NOT rewrite Phase 6 decoder/reconstruction/solver algorithms
- Do NOT duplicate domain models
- Do NOT duplicate ProductionWorkflow
- Do NOT create second CalibrationResult / CorrespondenceSet / ReconstructionResult
- Do NOT bypass hardware safety
- Do NOT use xfail/skip to hide defects
- HARDWARE_PENDING remains unchanged
- STOP AT REVIEW — do NOT start 7.8
