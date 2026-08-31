# 7.11 Validation & Safety Workflow — Dependency Map

Generated from 10-file architecture audit (Step 1).

## Existing Gate Systems (all disconnected)

### 1. CalibrationValidator (`calibration/validator.py`)

- **Report type**: `CalibrationValidationReport` (mutable, frozen post-7.10)
- **Checks**: reprojection error vs threshold, coverage, confidence, correspondence count, intrinsics sanity, pose sanity
- **Domain**: calibration quality only
- **No knowledge of**: display state, hardware_pending, source mode, arm/live eligibility

### 2. DisplayValidator (`hardware/display_validator.py`)

- **Report type**: `ValidationReport` (frozen)
- **Checks**: display connectivity, projector presence (when required), renderer readiness, window availability
- **Domain**: display routing only
- **No knowledge of**: calibration quality, hardware_pending, source mode

### 3. ReprojectionValidator (`infrastructure/.../validation.py`)

- **Report type**: `ValidationReport` (frozen)
- **Checks**: rms_error, coverage against thresholds
- **Domain**: reprojection quality only
- **No knowledge of**: display state, arm/live eligibility

### 4. ProductionWorkflow (`application/calibration_workflow.py`)

- **Tracks**: `hardware_pending: tuple[str, ...]` — 7 gate strings
- **States**: 15 states including READY_TO_ARM, ARMED, LIVE
- **Gap**: hardware_pending is data only — never gates transitions
- **Gap**: No calibration quality gate before READY_TO_ARM

### 5. OutputManager (`hardware/output_manager.py`)

- **`arm()`**: Calls `_validate_current()` → DisplayValidator only. Returns ValidationReport.
- **`go_live()`**: Same DisplayValidator only. Raises OutputSwitchError on failure.
- **Gap**: No calibration quality check
- **Gap**: No hardware_pending integration
- **Gap**: No source mode gating

### 6. CalibrationResultReviewViewModel (`ui/viewmodels/...`)

- **Has**: source_mode, hardware_pending, warnings, blocking_errors
- **Gap**: Does NOT gate on calibration quality thresholds
- **Gap**: Does NOT gate on hardware_pending for preview eligibility

### 7. CalibrationProgressViewModel (`ui/viewmodels/...`)

- **Has**: hardware_pending pass-through, error_category mapping
- **Gap**: No gate logic — pure presentation

## Unified Gate Model Requirements

### Three authorization decisions

| Decision      | Meaning                      | Gate combination                                          |
| ------------- | ---------------------------- | --------------------------------------------------------- |
| `can_preview` | Software review passed       | Calibration quality PASS + no blocking errors             |
| `can_arm`     | Safe to arm projector output | can_preview + display routing valid + no HARDWARE_PENDING |
| `can_live`    | Safe to go live              | can_arm + ARMED state + display still valid               |

### Gate taxonomy (V-01..V-07)

| Gate | Name                | Domain      | Owner                  |
| ---- | ------------------- | ----------- | ---------------------- |
| V-01 | Calibration quality | calibration | CalibrationValidator   |
| V-02 | Display routing     | hardware    | DisplayValidator       |
| V-03 | Renderer readiness  | hardware    | DisplayValidator       |
| V-04 | Window availability | hardware    | DisplayValidator       |
| V-05 | Hardware pending    | physical    | ProductionWorkflow     |
| V-06 | Source mode         | meta        | ValidationGate (new)   |
| V-07 | Warp readiness      | domain      | Existing warp pipeline |

### HARDWARE_PENDING ≠ PASS (enforcement)

- Hardware pending gates are NEVER collapsed into a single boolean
- `software_ready` and `physical_ready` kept distinct at all layers
- Gate result must expose individual gate statuses

### Source mode gating

- SYNTHETIC: can_preview YES, can_arm NO, can_live NO
- REPLAY: can_preview YES, can_arm NO, can_live NO
- LIVE: can_preview YES, can_arm depends on gates, can_live depends on gates

## Wiring Plan (Steps 2-9)

### Step 2: Create `calibration/validation_gate.py`

- `ValidationGateResult` dataclass with per-gate statuses
- `ValidationGate.check()` orchestrator method
- `GateStatus` enum: PASS, FAIL, PENDING, SKIP
- `AuthorizationLevel` enum: NONE, PREVIEW, ARM, LIVE

### Step 3: Wire CalibrationValidator → Gate

- Map CalibrationValidationReport to V-01 status

### Step 4: Wire DisplayValidator → Gate

- Map DisplayValidator report to V-02, V-03, V-04 statuses

### Step 5: Wire hardware_pending → Gate

- Map ProductionWorkflow.hardware_pending to V-05 status

### Step 6: Wire source mode → Gate

- Map source_mode to V-06 status

### Step 7: Wire OutputManager → Gate

- Replace DisplayValidator call in `arm()` with ValidationGate
- Replace DisplayValidator call in `go_live()` with ValidationGate

### Step 8: Wire ProductionWorkflow → Gate

- Gate READY_TO_ARM transition on ValidationGate.check()

### Step 9: Wire UI → Gate

- CalibrationResultReviewViewModel uses gate result for eligibility
- CalibrationProgressViewModel shows gate status
