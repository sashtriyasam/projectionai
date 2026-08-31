# Phase 7.11 — Scope Reconciliation Audit

**Date:** 2026-08-28
**Author:** Sisyphus
**Status:** SCOPE DEFINITION — DO NOT IMPLEMENT

---

## 1. Objective

Determine what 7.11 should actually deliver given that 7.9 (Warp Preview) and 7.10 (Persistence/Recall) are now DONE, and the historical "Validation & safety workflow" description is ambiguous.

---

## 2. Status Verification

| Phase | Status  | Evidence                                       |
| ----- | ------- | ---------------------------------------------- |
| 7.9   | DONE    | REPORT.md, 79/79 tests, Google Sheet           |
| 7.10  | DONE    | REPORT.md, 57/57 tests, hardened, Google Sheet |
| 7.11  | BACKLOG | MASTER_PLAN row 51, 01_MASTER_PLAN             |

**Dependencies:**

- 7.11 depends on: 7.10 ✓ (satisfied)
- 7.12 depends on: 7.11 (CRITICAL — blocks arm/live workflow)
- 7.15 depends on: 7.11 (CRITICAL — blocks hardware validation workflow)

---

## 3. Historical Scope

From `01_MASTER_PLAN` row 51:

- **Phase:** 7.11
- **Name:** "Validation" → "Validation & safety workflow"
- **Task:** "Validator, gates"
- **Priority:** CRITICAL
- **Gates:** (none defined)
- **Depends on:** 7.10

---

## 4. What Already Exists (Post-7.9 / Post-7.10)

### 4.1 Calibration Validation

**File:** `src/projectionai/calibration/validator.py`

- `CalibrationValidator` with `CalibrationCheck` subclasses
- `ValidationReport` (mutable): `passed`, `issues`, `quality_score`
- Checks: reprojection error, coverage, confidence, sample count, orientation consistency
- Called by `CalibrationManager.validate()`

### 4.2 Display/Output Validation

**File:** `src/projectionai/hardware/display_validator.py`

- `DisplayValidator` with `ValidateInputs`
- `ValidationReport` (frozen): `issues` tuple, `is_ok`, `errors`, `warnings`, `summary`
- Checks: renderer readiness, display presence, projector availability, resolution, refresh rate, GPU, duplicate output, window availability
- Called by `OutputManager` before live output

### 4.3 Reprojection Validation

**File:** `src/projectionai/infrastructure/projector_calibration/validation.py`

- `ReprojectionValidator`
- `ValidationReport` (frozen): `rms_error`, `coverage`, `passed`
- Post-solver quality check

### 4.4 Review Eligibility (7.8)

**File:** `src/projectionai/ui/viewmodels/calibration_result_review.py`

- `CalibrationResultReviewViewModel`
- `review_ok` = no blocking_errors
- `ReviewDecision`: ACCEPTED_FOR_PREVIEW / REJECTED / NEEDS_RECALIBRATION
- Surfaces warnings, blocking_errors, hardware_pending

### 4.5 Persistence Integrity (7.10)

**Files:** `calibration/persistence.py`, `calibration/recall.py`

- SHA-256 checksums on all asset files
- Schema versioning (forward-reject)
- Atomic writes (tmp + os.replace)
- Compatibility checks on recall (projector/camera/surface ID mismatch)

### 4.6 ProductionWorkflow (7.1)

**File:** `src/projectionai/application/calibration_workflow.py`

- State machine: stages from IDLE through calibration to READY_TO_ARM
- `hardware_pending` tuple exposed (7 gates)
- arm/go_live stages deferred to 7.12

---

## 5. Gap Analysis — What's Missing

### 5.1 No Unified Validation Gate Orchestrator

The validators exist independently. There is NO single entry point that:

- Collects validation state from ALL validators (calibration + display + hardware + persistence)
- Produces a unified "ready to arm/go_live" decision
- Can be queried by OutputManager, ProductionWorkflow, and UI

### 5.2 No Gate Integration with OutputManager

`OutputManager` uses `DisplayValidator` but does NOT check:

- Calibration quality (reprojection error, coverage, confidence)
- Persistence integrity (checksums, schema version)
- Hardware validation gates (H-01..07)

### 5.3 No Gate Integration with ProductionWorkflow

`ProductionWorkflow` exposes `hardware_pending` but does NOT:

- Block arm/go_live based on validation gate status
- Enforce that calibration quality passes before allowing live output
- Provide a "validation gate failed" pathway

### 5.4 7.15 Hardware Gates Not Wired

Hardware validation gates (H-01..07) exist as definitions in `10_VALIDATION_GATES` but are NOT wired into any software validation workflow. 7.15 expects this wiring.

### 5.5 Three Incompatible ValidationReport Classes

| Module                       | Type              | Fields                              | Usage                |
| ---------------------------- | ----------------- | ----------------------------------- | -------------------- |
| `calibration.validator`      | mutable dataclass | `passed`, `issues`, `quality_score` | Calibration quality  |
| `hardware.display_validator` | frozen dataclass  | `issues` tuple, `is_ok`, `summary`  | Display/output chain |
| `infrastructure.validation`  | frozen dataclass  | `rms_error`, `coverage`, `passed`   | Reprojection quality |

These are semantically different but share the same name. Unifying them is optional but the gate orchestrator needs to consume all three.

---

## 6. Recommended Final Scope

### 6.1 Name

**Validation & Safety Workflow** (keep historical name)

### 6.2 Objective

Provide a unified validation gate orchestrator that:

1. Collects validation state from all existing validators
2. Produces a single readiness decision ("can arm/go_live?")
3. Gates the arm/go_live transition in OutputManager
4. Exposes gate status to ProductionWorkflow and UI

### 6.3 In Scope

| Deliverable                           | Description                                                                                    |
| ------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `ValidationGateOrchestrator`          | Collects from CalibrationValidator + DisplayValidator + HardwareManager + PersistenceIntegrity |
| `ValidationGateReport`                | Unified pass/fail per gate, summary, blocking errors                                           |
| `OutputManager` gate integration      | Block arm/go_live unless orchestrator reports ready                                            |
| `ProductionWorkflow` gate integration | Expose gate status, block READY_TO_ARM if gates fail                                           |
| Tests                                 | Unit tests for orchestrator, integration tests for gate blocking                               |

### 6.4 Non-Goals (Deferred)

| Item                                  | Defers To                                      |
| ------------------------------------- | ---------------------------------------------- |
| Actual hardware validation (H-01..07) | 7.15                                           |
| arm/live workflow implementation      | 7.12                                           |
| New calibration validators            | Use existing CalibrationValidator              |
| ValidationReport unification          | Optional — orchestrator wraps existing reports |
| Schema migration                      | 7.10 follow-up                                 |

### 6.5 Constraints

| Constraint                                     | Status |
| ---------------------------------------------- | ------ |
| Do NOT create a second CalibrationResult model | ✓      |
| Do NOT create a second WarpMesh model          | ✓      |
| Do NOT create a second replay format           | ✓      |
| Do NOT create a parallel persistence framework | ✓      |
| Do NOT silently overwrite a valid calibration  | ✓      |
| Do NOT silently load corrupt calibration data  | ✓      |
| Do NOT convert HARDWARE_PENDING into PASS      | ✓      |
| Do NOT recalculate calibration while loading   | ✓      |
| Do NOT introduce a large concurrency framework | ✓      |
| Do NOT implement 7.12 arm/live                 | ✓      |
| Do NOT implement 7.15 hardware validation      | ✓      |

---

## 7. Architecture Dependency Review

```
7.11 Validation Gate Orchestrator
    ├── consumes: CalibrationValidator (existing)
    ├── consumes: DisplayValidator (existing)
    ├── consumes: HardwareManager.hardware_pending (existing)
    ├── consumes: CalibrationPersistence integrity (existing)
    ├── produces: ValidationGateReport
    ├── blocks: OutputManager.arm/go_live (7.12 integration)
    └── exposes: gate status to ProductionWorkflow (7.1)
```

No new domain models required. No new persistence format. No new UI components (surfaces existing validation status through existing UI).

---

## 8. Duplication Check

| Concern               | Duplicated?                    | Resolution                               |
| --------------------- | ------------------------------ | ---------------------------------------- |
| CalibrationValidator  | No — unique to calibration     | Keep as-is                               |
| DisplayValidator      | No — unique to display         | Keep as-is                               |
| ReprojectionValidator | No — unique to solver          | Keep as-is                               |
| ValidationReport      | YES — 3 classes with same name | Orchestrator wraps; unification optional |
| FileLock              | No — consolidated in 7.10      | Keep as-is                               |
| Checksum utilities    | No — consolidated in 7.10      | Keep as-is                               |

---

## 9. Hardware Boundary

**SOFTWARE-READY**: All deliverables are software-only. No physical validation required.

**HARDWARE-PENDING**: H-01..07 remain HARDWARE_PENDING. 7.11 does NOT touch them.

---

## 10. Expected Files

| File                                                   | Action | Purpose                                           |
| ------------------------------------------------------ | ------ | ------------------------------------------------- |
| `src/projectionai/calibration/validation_gate.py`      | NEW    | ValidationGateOrchestrator + ValidationGateReport |
| `src/projectionai/calibration/__init__.py`             | MODIFY | Export new classes                                |
| `src/projectionai/hardware/output_manager.py`          | MODIFY | Gate arm/go_live through orchestrator             |
| `src/projectionai/application/calibration_workflow.py` | MODIFY | Expose gate status                                |
| `tests/unit/calibration/test_validation_gate.py`       | NEW    | Unit tests                                        |
| `tests/unit/hardware/test_output_manager_gate.py`      | NEW    | Integration tests                                 |

---

## 11. Acceptance Criteria

1. `ValidationGateOrchestrator.validate()` returns `ValidationGateReport` with per-gate pass/fail
2. `OutputManager.arm()` blocked when orchestrator reports NOT_READY
3. `OutputManager.go_live()` blocked when orchestrator reports NOT_READY
4. `ProductionWorkflow` exposes gate status for UI consumption
5. All existing tests pass (no regressions)
6. ruff clean, mypy --strict clean
7. Google Sheet updated (status history, changelog)
8. REPORT.md written with gate audit

---

## 12. Decision Required

**DO NOT IMPLEMENT until user confirms this scope.**

The scope above is a recommendation based on gap analysis. User must approve before any code changes.

---

**STOP AFTER THIS REPORT. DO NOT IMPLEMENT.**
