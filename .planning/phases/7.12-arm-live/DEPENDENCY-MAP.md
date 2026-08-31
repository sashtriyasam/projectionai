# 7.12 Arm / Live Workflow — Dependency Map

Generated from 10-file architecture audit (Step 1).

## Existing State Machines (connected)

### 1. OutputManager (`hardware/output_manager.py`)

**Owns:** "output session" lifecycle — preview routing, arming, live switching, blackout, freeze, teardown.

**OutputState enum:**

- IDLE
- PREVIEW
- ARMED
- LIVE
- BLACKOUT
- FREEZE

**Key methods (already implemented):**

| Method              | Purpose                      | Safety                                                 |
| ------------------- | ---------------------------- | ------------------------------------------------------ |
| `begin_session()`   | Start session → PREVIEW/IDLE | ✅ validates display                                   |
| `end_session()`     | Safe end from any state      | ✅ clears routes                                       |
| `set_preview()`     | Change preview target        | ✅ validates display                                   |
| `set_live_target()` | Set live display (no switch) | ✅ rejects in FREEZE                                   |
| `arm()`             | Validate → transition ARMED  | ✅ dual validation (DisplayValidator + ValidationGate) |
| `go_live()`         | Validate → switch LIVE       | ✅ dual validation, raises OutputSwitchError           |
| `blackout()`        | Cut live → BLACKOUT          | ✅ keeps live route; works even when validation fails  |
| `freeze()`          | Hold frame → FREEZE          | ✅ only from LIVE/BLACKOUT                             |
| `unfreeze()`        | Resume from FREEZE           | ✅ handles display loss                                |
| `switch_live_to()`  | Atomic: target + live        | ✅ rolls back on failure                               |

**Gate integration (7.11):**

- `_run_gate()` evaluates ValidationGate with calibration/display/hardware_pending/source_mode
- `can_arm` / `can_live` properties reflect gate authorization
- Legacy: no gate = always True (backward compat)

---

### 2. ProductionWorkflow (`application/calibration_workflow.py`)

**Owns:** Operator calibration lifecycle (15 states).

**WorkflowState enum:**

- IDLE, PRECHECK, PREPARING, CAPTURING, DECODING, RECONSTRUCTING, SOLVING, VALIDATING, PREVIEW, SAVING, READY_TO_ARM, ARMED, LIVE, CANCELLED, FAILED

**Valid transitions (explicit):**

- READY_TO_ARM → ARMED, FAILED, CANCELLED
- ARMED → LIVE, FAILED, CANCELLED
- LIVE → IDLE, CANCELLED, FAILED

**Hardware pending (7 gates — HARDWARE_PENDING):**

- optical closure
- real vsync/frameSwapped
- settle-time
- camera buffer policy
- real sentinel coverage
- real two-plane calibration
- repeatability

**Gate integration (7.11):**

- `run_gate()` evaluates ValidationGate with accumulated state
- `is_synthetic` blocks LIVE transition

---

### 3. ValidationGate (`calibration/validation_gate.py`)

**Owns:** Single source of truth for "Is the system authorized?"

**Gate taxonomy (V-01..V-07):**

| Gate ID | Name                | Source               |
| ------- | ------------------- | -------------------- |
| V-01    | Calibration Quality | CalibrationValidator |
| V-02    | Display Routing     | DisplayValidator     |
| V-03    | Renderer Readiness  | DisplayValidator     |
| V-04    | Window Availability | DisplayValidator     |
| V-05    | Hardware Pending    | ProductionWorkflow   |
| V-06    | Source Mode         | ValidationGate       |
| V-07    | Warp Readiness      | WarpPipeline         |

**Authorization levels:**

| Level   | Meaning                                              |
| ------- | ---------------------------------------------------- |
| NONE    | Any gate FAIL                                        |
| PREVIEW | Software review OK (no FAIL; PENDING allowed)        |
| ARM     | Physical arm OK (no FAIL + no PENDING + LIVE source) |
| LIVE    | Full go-live (ARM + ARMED state)                     |

**Key constraints:**

- HARDWARE_PENDING ≠ PASS (V-05 PENDING when any hardware gate pending)
- can_preview ≠ can_arm ≠ can_live (three explicit levels)
- Source SYNTHETIC/REPLAY → max PREVIEW
- Gate is optional (legacy behavior preserved)

---

### 4. DisplayValidator (`hardware/display_validator.py`)

**Owns:** Pre-flight checks before output goes live.

**Checks (errors block switch):**

- renderer ready
- display connected
- live/preview display found
- projector available (when required)
- resolution supported
- window available
- (warnings: GPU software renderer, low resolution, duplicate output)

**Report buckets:** errors (block), warnings (allow), recommendations

---

### 5. DisplayManager (`hardware/display_manager.py`)

**Owns:** Display topology + live/preview routing.

**Key properties:**

- `displays` — all connected
- `projectors` — filtered
- `live_output` / `preview_output` — routed displays

**Operations:**

- `refresh()` — scans, diffs, emits events, clears dangling routes
- `set_live_output()` / `set_preview_output()` — route output
- `move_window_to()` / `set_fullscreen()` / `restore_window()` — window ops

---

### 6. OutputWindow Protocol (`hardware/models.py`)

**Implemented by:** `GLOutputWindow` (Qt + ModernGL)

**Capabilities:**

- `set_content()` / `set_pattern()` / `set_blackout()` / `set_freeze()`
- `gl_ready` property
- Fullscreen + ESC hook
- Degrades to black on GL failure

**GLOutputWindow handles:**

- PatternPass (test patterns, black, freeze)
- ProjectionPass (warp mesh + texture)
- ScreenTarget (FBO management)

---

### 7. Domain Models

**CalibrationResult (domain/calibration_session.py):**

- Canonical immutable calibration with projector pose, intrinsics, reprojection error, coverage, confidence
- `to_dict()` / `from_dict()` for persistence
- Legacy bridge to old domain types

**WarpMesh (domain/warp_mesh.py):**

- projector_uvs, content_uvs, indices for GPU warp

**ProjectionMapping (domain/projection.py):**

- projector_id, surface_id, calibration_id, warp_mesh_asset_id
- blend, mask, crop, color correction

---

## Missing / Gaps for 7.12

### State Machine Gaps

| Gap          | Current                 | Needed                      |
| ------------ | ----------------------- | --------------------------- |
| READY_TO_ARM | Exists in WorkflowState | ✅ Exists                   |
| ARMING       | Missing                 | Need transient ARMING state |
| FROZEN       | Exists in OutputState   | ✅ Exists                   |
| STOPPING     | Missing                 | Need explicit stopping path |
| FAILED       | Exists in both          | ✅ Exists                   |

### Missing Methods on OutputManager

| Missing                 | Purpose                                     |
| ----------------------- | ------------------------------------------- |
| `disarm()`              | Explicit ARMED → PREVIEW/IDLE               |
| `safe_stop()`           | Idempotent: live/armed/blackout → safe IDLE |
| `rearm_after_failure()` | Clear failed state, re-evaluate gate        |

### Missing Gate Re-evaluation

| Scenario                       | Current                       | Needed                    |
| ------------------------------ | ----------------------------- | ------------------------- |
| Stale gate before LIVE         | Not re-checked                | Must re-run gate          |
| Display disconnect during LIVE | Clears route but no safe stop | Must blackout + fail safe |
| Resolution change              | Detected by DisplayManager    | Invalidate authorization  |
| Calibration invalidation       | Not handled                   | Invalidate authorization  |

### Missing Error Types

| Error                     | When                         |
| ------------------------- | ---------------------------- |
| `ArmNotAuthorizedError`   | V-01..V-07 FAIL              |
| `LiveNotAuthorizedError`  | V-06 PENDING or V-05 PENDING |
| `DisplayLostError`        | Live display disappears      |
| `CalibrationInvalidError` | Calibration ID mismatch      |
| `OutputActivationError`   | GL window activation fails   |
| `SafeStopError`           | Safe stop fails              |

### Missing Concurrency Safety

| Scenario                    | Current  |
| --------------------------- | -------- |
| Double ARM                  | No guard |
| Double LIVE                 | No guard |
| STOP during ARMING          | No guard |
| STOP during LIVE transition | No guard |

---

## Files to Modify

| File                                                          | Changes                                                                                  |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `src/projectionai/hardware/output_manager.py`                 | Add ARMING state, disarm(), safe_stop(), gate re-check before LIVE, explicit error types |
| `src/projectionai/application/calibration_workflow.py`        | Ensure ARMING state, safe stop integration                                               |
| `src/projectionai/hardware/errors.py`                         | Add new typed errors                                                                     |
| `src/projectionai/ui/viewmodels/calibration_result_review.py` | UI state for ARMING/ARMED/LIVE/FREEZE/BLACKOUT                                           |
| `tests/unit/hardware/test_output_manager.py`                  | Extend for new behaviors                                                                 |

---

## Reuse Strategy (No Duplication)

| Component          | Reuse                                     | Do Not Create            |
| ------------------ | ----------------------------------------- | ------------------------ |
| OutputManager      | ✅ Single authority for session lifecycle | LiveManager, ArmManager  |
| DisplayValidator   | ✅ Display checks                         | Second display validator |
| ValidationGate     | ✅ Authorization decisions                | Second gate system       |
| OutputState        | ✅ Core states                            | Second state machine     |
| GLOutputWindow     | ✅ Rendering                              | Second output window     |
| ProductionWorkflow | ✅ Operator lifecycle                     | Second workflow          |

---

## Key Integration Points

1. **Before ARM:** OutputManager._run_gate() → can_arm
2. **Before LIVE:** OutputManager._run_gate() → can_live (re-evaluated!)
3. **On failure:** OutputSwitchError carries ValidationReport
4. **On display loss:** DisplayManager clears route + emits event
5. **On freeze:** OutputManager holds _pre_freeze_state
6. **On blackout:** Independent, works even when validation fails

---

## Test Coverage Required (from spec)

- Valid/invalid state transitions
- ARM blocked by V-01..V-07 failures
- LIVE blocked by non-LIVE source, stale gate, changed resolution/display/calibration
- ARM never auto-LIVE
- LIVE failure → blackout
- Freeze/unfreeze/blackout/safe stop
- Display disconnect → safe blackout
- Calibration invalidation → block
- Concurrency: double ARM, double LIVE, STOP during activation
- Startup always non-LIVE
- No primary-display failover
