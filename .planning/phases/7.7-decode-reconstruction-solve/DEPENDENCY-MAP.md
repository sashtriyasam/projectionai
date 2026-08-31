# Phase 7.7 — Decode / Reconstruction / Solve UX: Dependency Map

**Created:** 2026-08-28
**Source:** Architecture audit of Phase 6 engines + Phase 7 workflow/UI

---

## 1. Pipeline Data Flow

```
CalibrationSequence
       ↓
CalibrationFrame[] (from CaptureSession)
       ↓
StructuredLightDecoder.decode()
       ↓
CorrespondenceSet
       ↓
ReconstructionBackend.reconstruct()
       ↓
ReconstructionResult
       ↓ (2+ orientations required)
solver.solve_calibration()
       ↓
CalibrationResult
```

## 2. Phase 6 Engine Inventory

### 2.1 Decode Engine

| File                                                     | Class                    | Lines | Input                                                  | Output              |
| -------------------------------------------------------- | ------------------------ | ----- | ------------------------------------------------------ | ------------------- |
| `services/structured_light_decoder.py`                   | `StructuredLightDecoder` | 147   | `tuple[CalibrationFrame, ...]` + `CalibrationSequence` | `CorrespondenceSet` |
| `infrastructure/projector_calibration/correspondence.py` | `CorrespondenceMatcher`  | 197   | Raw captures + `PatternSequence` (legacy)              | `CorrespondenceMap` |

**Validation performed:**

- Non-empty frames
- Frame count == pattern count
- Sequence/pattern ID match
- No duplicate pattern_ids
- Projector resolution > 0
- Finite projector_x/y on valid mask
- Projector coords within bounds (±0.5px)

**Quality metrics:** `valid_ratio: float` (fraction of valid pixels)

**Error type:** `StructuredLightDecodeError(ProjectorCalibrationError)`

**Cancellation:** None

---

### 2.2 Reconstruction Engine

| File                                  | Class                         | Lines | Input                                                     | Output                 |
| ------------------------------------- | ----------------------------- | ----- | --------------------------------------------------------- | ---------------------- |
| `services/reconstruction.py`          | `ReconstructionBackend` (ABC) | 237   | `CorrespondenceSet` + `CalibratedCamera` + `SurfacePlane` | `ReconstructionResult` |
| `calibration/reconstruction_stage.py` | `ReconstructionStage`         | 76    | StageContext                                              | StageContext           |

**Backends:**

| Backend                          | Name          | Notes                            |
| -------------------------------- | ------------- | -------------------------------- |
| `ReferenceReconstructionBackend` | `"reference"` | NumPy/OpenCV, production default |
| `NativeReconstructionBackend`    | `"native"`    | C++/pybind11, optional           |

**Backend selection:** `ReconstructionBackendFactory.create(mode: BackendMode)`

- `REFERENCE` → reference (default)
- `NATIVE` → native
- `AUTO` → try native, fallback reference

**Quality metrics:** Point count, finite point count, sampling stats

**Error type:** `ReconstructionError(ProjectorCalibrationError)`

**Cancellation:** None

---

### 2.3 Solver Engine

| File                                     | Class                   | Lines | Input                              | Output              |
| ---------------------------------------- | ----------------------- | ----- | ---------------------------------- | ------------------- |
| `calibration/solver.py`                  | `solve_calibration()`   | 551   | `tuple[ReconstructionResult, ...]` | `CalibrationResult` |
| `calibration/calibration_solve_stage.py` | `CalibrationSolveStage` | 128   | StageContext                       | StageContext        |

**Orientation diversity requirements:**

- Minimum 2 planes (`_MIN_PLANES = 2`)
- Minimum pairwise tilt 15° (`_MIN_TILT_DEG`)
- Condition number < 1e6 (`_MAX_COND`)
- Rank ≥ 2

**Quality metrics:**

- `reprojection_error` (float): Mean RMS (px)
- `coverage` (float): Unique projector pixels / area [0,1]
- `confidence` (float): Derived from RMS + coverage [0,1]
- `num_correspondences` (int): Total 3D points
- `per_point_errors` (tuple[float,...]): From best plane
- Metadata: joint_fx, joint_fy, joint_condition, joint_rank, per_plane_rms/p95/max

**Error type:** `CalibrationSolveError(ProjectionAIError)`

**Cancellation:** None

---

## 3. Phase 7 Workflow Inventory

### 3.1 ProductionWorkflow

| File                                  | Class                | Lines |
| ------------------------------------- | -------------------- | ----- |
| `application/calibration_workflow.py` | `ProductionWorkflow` | 499   |

**8 Stages:** prepare → capture → decode → reconstruct → solve → validate → warp → persist

**Stage status:**

| Stage       | Implementation  | Notes                                              |
| ----------- | --------------- | -------------------------------------------------- |
| prepare     | **REAL**        | `PatternEngine.generate()` → `CalibrationSequence` |
| capture     | **PLACEHOLDER** | No-op, doesn't use CaptureSession                  |
| decode      | **PLACEHOLDER** | No-op                                              |
| reconstruct | **PLACEHOLDER** | No-op                                              |
| solve       | **PLACEHOLDER** | No-op                                              |
| validate    | **PLACEHOLDER** | No-op                                              |
| warp        | **PLACEHOLDER** | No-op                                              |
| persist     | **PLACEHOLDER** | No-op                                              |

**Progress:** `sum(stage_scores) / 8` (deterministic)

**Error handling:** Exception → FAILED state, marks running stage with error

**Retry:** `_run_stage_with_retry()` — bounded (0-5), exponential backoff

**Cancel:** `request_cancel()` sets flag, checked between stages

**Synthetic guard:** `is_synthetic=True` blocks LIVE state

---

### 3.2 CaptureSession (Phase 7.6)

| File                          | Class            | Lines |
| ----------------------------- | ---------------- | ----- |
| `services/capture_session.py` | `CaptureSession` | 858   |

**State machine:** IDLE → PRESENTING → WAITING → CAPTURED → VALIDATING → COMPLETE

**Status:** COMPLETE but NOT WIRED into ProductionWorkflow

**Key API:**

- `capture_sequence(sequence)` → `CaptureResult`
- `cancel()` → cooperative cancellation
- `metrics` → `CaptureMetrics`

---

## 4. UI Layer Inventory

### 4.1 CalibrationProgressViewModel

| File                                    | Class                          | Lines |
| --------------------------------------- | ------------------------------ | ----- |
| `ui/viewmodels/calibration_progress.py` | `CalibrationProgressViewModel` | 280   |

**Exposed properties:**

- workflow_state, current_stage, stage_status, stage_progress
- overall_progress, elapsed_time, estimated_remaining
- pattern_index, pattern_total (always 0 — workflow doesn't set them)
- camera_status, projector_status
- warnings, errors
- can_cancel, can_retry
- hardware_pending (7 gates)

**Gap:** `pattern_index`/`pattern_total` always 0

---

### 4.2 CalibrationProgressWidget

| File                                        | Class                       | Lines |
| ------------------------------------------- | --------------------------- | ----- |
| `ui/widgets/calibration_progress_widget.py` | `CalibrationProgressWidget` | 393   |

**8 displayed stages:** PREPARING, CAPTURING, DECODING, RECONSTRUCTING, SOLVING, VALIDATING, PREVIEW, SAVING

**Visual elements:**

- Stage status indicators (○ PENDING, ● RUNNING, ✓ COMPLETE, ✗ FAILED)
- Progress bars (overall + per-stage)
- Elapsed time + ETA
- Device status
- Hardware pending gates
- Warnings/errors
- Cancel/retry buttons

**Polling:** QTimer 100ms, revision-based

---

## 5. Domain Types

| Type                   | File                            | Key Fields                                                 |
| ---------------------- | ------------------------------- | ---------------------------------------------------------- |
| `CalibrationFrame`     | `domain/calibration_session.py` | capture, pattern                                           |
| `CalibrationSequence`  | `domain/calibration_session.py` | sequence_id, method, patterns, width, height               |
| `CorrespondenceSet`    | `domain/calibration_session.py` | projector_x/y, mask, valid_ratio                           |
| `ReconstructionResult` | `domain/calibration_session.py` | points_camera, projector_pixels, sequence_id               |
| `CalibrationResult`    | `domain/calibration_session.py` | intrinsics, pose, reprojection_error, coverage, confidence |

---

## 6. Error Hierarchy

```
ProjectionAIError
├── ProjectorCalibrationError
│   ├── StructuredLightDecodeError
│   └── ReconstructionError
└── CalibrationSolveError
```

Stage wrappers convert all engine errors → `StageError(RuntimeError)`

---

## 7. Critical Gaps for Phase 7.7

| Gap                              | Impact                             | Priority |
| -------------------------------- | ---------------------------------- | -------- |
| CaptureSession not wired         | Capture stage is placeholder       | HIGH     |
| Decode stage placeholder         | No real correspondence computation | HIGH     |
| Reconstruct stage placeholder    | No real 3D reconstruction          | HIGH     |
| Solve stage placeholder          | No real calibration result         | HIGH     |
| No cancellation in engines       | Can't stop long operations         | MEDIUM   |
| No progress callbacks in engines | Stage-level progress only          | MEDIUM   |
| pattern_index/total always 0     | UI can't show capture progress     | LOW      |

---

## 8. Files to Modify

| File                                        | Change                     | Reason                                |
| ------------------------------------------- | -------------------------- | ------------------------------------- |
| `application/calibration_workflow.py`       | Replace placeholder stages | Wire real decode/reconstruct/solve    |
| `ui/viewmodels/calibration_progress.py`     | Expose per-stage metrics   | Show decode/reconstruct/solve details |
| `ui/widgets/calibration_progress_widget.py` | Add quality gates display  | Show solver metrics/warnings          |

## 9. Files to Create

| File                                                   | Purpose                        |
| ------------------------------------------------------ | ------------------------------ |
| `tests/unit/services/test_decode_reconstruct_solve.py` | Integration tests for pipeline |

## 10. Files to Read Only

| File                                     | Purpose                            |
| ---------------------------------------- | ---------------------------------- |
| `services/structured_light_decoder.py`   | Decode engine (no changes)         |
| `services/reconstruction.py`             | Reconstruction engine (no changes) |
| `calibration/solver.py`                  | Solver engine (no changes)         |
| `calibration/reconstruction_stage.py`    | Stage wrapper (no changes)         |
| `calibration/calibration_solve_stage.py` | Stage wrapper (no changes)         |
| `domain/calibration_session.py`          | Domain types (no changes)          |
