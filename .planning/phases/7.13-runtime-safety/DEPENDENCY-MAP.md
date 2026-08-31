# Phase 7.13 — DEPENDENCY MAP: Runtime Safety Watchdog

## Audit Summary

Phase 7.13 adds a continuous runtime safety watchdog that monitors an active output session and fails SAFE when runtime conditions invalidate safe operation. The watchdog observes and triggers existing safety operations (OutputManager) — it does NOT become another authority or second state machine.

---

## Existing Runtime Mechanisms (Audited)

### 1. OutputManager (`src/projectionai/hardware/output_manager.py`)

**State Machine**: `IDLE → PREVIEW → ARMING → ARMED → LIVE → FREEZE/BLACKOUT/STOPPING/FAILED`

| Method                                           | Purpose                                             | Failure Mode                        |
| ------------------------------------------------ | --------------------------------------------------- | ----------------------------------- |
| `begin_session()`                                | Transition to PREVIEW                               | —                                   |
| `arm()`                                          | Pre-flight validation + gate check → ARMING → ARMED | Returns ValidationReport on failure |
| `go_live()`                                      | Re-evaluate gate → LIVE                             | Raises `LiveNotAuthorizedError`     |
| `freeze()`                                       | Freeze output                                       | —                                   |
| `blackout()`                                     | Black screen                                        | —                                   |
| `safe_stop()`                                    | Graceful shutdown (IDLE)                            | Raises `SafeStopError`              |
| `disarm()`                                       | ARMED → PREVIEW                                     | —                                   |
| `handle_display_loss(display_id)`                | Display disconnect → safe stop                      | Emits `OutputStopped`               |
| `handle_resolution_change(display_id, old, new)` | Resolution change → safe stop                       | Emits `OutputStopped`               |
| `check_gate_stale()`                             | Check if gate evaluation >300s old                  | Returns bool                        |
| `rearm_after_failure()`                          | FAILED → PREVIEW                                    | —                                   |

**Concurrency**: `asyncio.Lock` for state transitions, `_session_lock` for session operations.

### 2. ValidationGate (`src/projectionai/calibration/validation_gate.py`)

| Gate                | ID   | Level   | Purpose                                                |
| ------------------- | ---- | ------- | ------------------------------------------------------ |
| Calibration Quality | V-01 | PREVIEW | Calibration present and quality passed                 |
| Display Routing     | V-02 | PREVIEW | Display routing valid for target                       |
| Renderer Readiness  | V-03 | PREVIEW | GL renderer healthy                                    |
| Window Availability | V-04 | PREVIEW | Projection window exists and reachable                 |
| Hardware Pending    | V-05 | LIVE    | Aggregate H-gate blocker (H-01..H-07 HARDWARE_PENDING) |
| Source Mode         | V-06 | LIVE    | SYNTHETIC/REPLAY pass; LIVE fails if required          |
| Warp Readiness      | V-07 | LIVE    | Warp pipeline ready                                    |

**Key Properties**:

- `check()` → `ValidationGateResult` with `evaluated_at: datetime`
- `can_preview`, `can_arm`, `can_live` convenience booleans
- No periodic re-evaluation mechanism (one-shot only)

### 3. DisplayManager (`src/projectionai/hardware/display_manager.py`)

**Events Emitted**:

- `DisplayConnected(display_id, name, mode, is_primary)`
- `DisplayDisconnected(display_id, name)`
- `DisplayResolutionChanged(display_id, old_mode, new_mode)`
- `DisplayRefreshRateChanged(display_id, old_hz, new_hz)`
- `DisplayOrientationChanged(display_id, old_orientation, new_orientation)`
- `DisplayLiveOutputChanged(display_id, old_window, new_window)`
- `DisplayPreviewOutputChanged(display_id, old_window, new_window)`
- `DisplaysRefreshed(known_displays, active_displays)`

**Key Methods**:

- `refresh()` → scans OS displays, emits change events
- `get_display(display_id)` → `DisplayInfo | None`
- `get_active_display()` → `DisplayInfo | None`
- `get_live_display()` → `DisplayInfo | None`

### 4. DisplayWatcher (`src/projectionai/hardware/display_watcher.py`)

- Polls `DisplayManager.refresh()` on interval (default 1.0s)
- Backoff: doubles on error, resets on success
- Runs as `asyncio.Task` named `"display-watcher"`
- Lifecycle: `start()` → polls → `cancel()` → `wait_until_stopped()`

### 5. GLOutputWindow (`src/projectionai/infrastructure/renderer/output_window.py`)

- `QOpenGLWidget` subclass
- `gl_ready: bool` — True after first successful `initializeGL()`
- `paintGL()` checks `_gl_ready` before rendering
- No explicit context-loss signal (degrades to black when GL fails)
- Frame callback: `set_frame_callback(callback)` for per-frame invocations

### 6. CalibrationManager (`src/projectionai/calibration/calibration_manager.py`)

- `active_session: CalibrationSession | None`
- `load_results(project_id)` → `CalibrationResult | None`
- `delete_session(project_id)` → clears calibration
- No explicit calibration change signal

### 7. HardwareManager (`src/projectionai/hardware/hardware_manager.py`)

- Facade aggregating DisplayManager, DisplayWatcher, OutputManager, DisplayValidator
- `cleanup()` → stops watcher, cleans up output manager

---

## Data Flow: Existing Safety Operations

```
DisplayWatcher polls → DisplayManager.refresh()
    ↓ (emits DisplayDisconnected)
OutputManager.handle_display_loss()
    ↓ (calls safe_stop())
OutputManager → IDLE
    ↓ (emits OutputStopped)
EventBus → UI (status bar updates)

---

Gate Staleness:
OutputManager.check_gate_stale()
    ↓ (if gate evaluated_at > 300s)
Returns True → arm() / go_live() should re-evaluate

---

Renderer Health:
GLOutputWindow.paintGL()
    ↓ (if _gl_ready = False)
Degrades to black frame (no explicit signal)
```

---

## Watchdog Responsibility Boundaries

### IN SCOPE (watchdog monitors)

1. **Display health** — Display disconnected → trigger safe_stop
2. **Resolution changes** — Display resolution changed → trigger safe_stop
3. **Gate staleness** — Gate evaluation >N seconds old → trigger safe_stop
4. **Renderer health** — GL context lost / renderer not rendering → trigger safe_stop
5. **Calibration invalidation** — ~~trigger safe_stop~~ **DEFERRED** — covered by gate revocation (V-01 fails when calibration removed); no dedicated CALIBRATION_INVALID signal implemented
6. **Authorization drift** — Gate re-evaluation shows not authorized → trigger safe_stop

### OUT OF SCOPE (watchdog does NOT do)

1. **No second state machine** — OutputManager owns state transitions
2. **No second validation engine** — ValidationGate owns authorization
3. **No second OutputManager** — OutputManager owns output lifecycle
4. **No bypass of OutputManager** — Watchdog triggers OutputManager.safe_stop()
5. **No silent failures** — All failures logged and emitted as events
6. **No automatic re-arm** — Watchdog never re-arms after safety fault
7. **No silent display switching** — DisplayManager owns display routing
8. **No silent resolution changes** — DisplayManager owns resolution
9. **No H-gate conversion** — H-01..H-07 remain HARDWARE_PENDING
10. **No hardware verification claims** — H-gates require physical evidence

---

## Dependency Graph

```
                    ┌─────────────────┐
                    │  ValidationGate  │
                    │  (7.11)         │
                    └────────┬────────┘
                             │ check()
                             ▼
┌──────────────┐    ┌─────────────────┐    ┌──────────────┐
│DisplayManager│───▶│  OutputManager  │◀───│DisplayWatcher│
│  (7.2)       │    │  (7.12)         │    │  (7.2)       │
└──────────────┘    └────────┬────────┘    └──────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
      ┌──────────┐  ┌──────────────┐  ┌──────────┐
      │ GLOutput │  │  EventBus    │  │CalManager│
      │ Window   │  │              │  │  (7.1)   │
      └──────────┘  └──────────────┘  └──────────┘

                    ┌─────────────────┐
                    │  Runtime        │  ◀── NEW (7.13)
                    │  Watchdog       │
                    └────────┬────────┘
                             │ observes + triggers safe_stop()
                             ▼
                    ┌─────────────────┐
                    │  OutputManager  │
                    │  .safe_stop()   │
                    └─────────────────┘
```

---

## Signal Sources for Watchdog

| Signal               | Source             | Event/Method                       | Watchdog Response           |
| -------------------- | ------------------ | ---------------------------------- | --------------------------- |
| Display disconnected | DisplayManager     | `DisplayDisconnected`              | `OutputManager.safe_stop()` |
| Resolution changed   | DisplayManager     | `DisplayResolutionChanged`         | `OutputManager.safe_stop()` |
| Gate stale           | ValidationGate     | `check().evaluated_at` > threshold | `OutputManager.safe_stop()` |
| Renderer unhealthy   | GLOutputWindow     | `gl_ready = False`                 | `OutputManager.safe_stop()` |
| Calibration invalid  | CalibrationManager | `load_results()` returns None      | `OutputManager.safe_stop()` |
| Authorization drift  | ValidationGate     | `check().can_live = False`         | `OutputManager.safe_stop()` |

---

## Files to Create/Modify

| File                                             | Action | Purpose                      |
| ------------------------------------------------ | ------ | ---------------------------- |
| `src/projectionai/hardware/runtime_watchdog.py`  | CREATE | Watchdog implementation      |
| `src/projectionai/hardware/events.py`            | MODIFY | Add watchdog events          |
| `src/projectionai/hardware/hardware_manager.py`  | MODIFY | Integrate watchdog lifecycle |
| `tests/unit/hardware/test_runtime_watchdog.py`   | CREATE | Watchdog tests               |
| `.planning/phases/7.13-runtime-safety/REPORT.md` | CREATE | Final report                 |

> Note: `output_manager.py` is NOT modified by Phase 7.13 — the watchdog calls `OutputManager.safe_stop()` but OutputManager has no watchdog-specific hooks. The watchdog also calls `end_session()` via HardwareManager.

---

## Concurrency Model

- Watchdog runs as `asyncio.Task` (like DisplayWatcher)
- State protected by `asyncio.Lock`
- All event handlers are async
- Safe to call from any coroutine
- Idempotent start/stop (no-op if already in target state)

---

## Timing Constraints

| Parameter                | Default | Configurable | Purpose                         |
| ------------------------ | ------- | ------------ | ------------------------------- |
| `check_interval_s`       | 5.0     | Yes          | How often to re-evaluate gate   |
| `gate_stale_threshold_s` | 300.0   | Yes          | Max age of gate evaluation      |
| `renderer_timeout_s`     | 10.0    | Yes          | Max time without renderer frame |
| `start_timeout_s`        | 5.0     | Yes          | Max time for watchdog to start  |
| `stop_timeout_s`         | 5.0     | Yes          | Max time for watchdog to stop   |

---

## Event Types (New)

| Event                 | Payload                                  | Purpose                     |
| --------------------- | ---------------------------------------- | --------------------------- |
| `WatchdogStarted`     | `started_at: datetime`                   | Watchdog began monitoring   |
| `WatchdogStopped`     | `stopped_at: datetime, reason: str`      | Watchdog stopped monitoring |
| `WatchdogTriggered`   | `trigger: WatchdogTrigger, details: str` | Safety violation detected   |
| `WatchdogCheckPassed` | `checked_at: datetime`                   | All checks passed           |

---

## Test Strategy

- All tests use deterministic mocks (no hardware)
- Mock DisplayManager, ValidationGate, GLOutputWindow, CalibrationManager
- Test each trigger independently
- Test idempotent start/stop
- Test concurrency (asyncio.Lock)
- Test event emission
- Test timing constraints (mock asyncio.sleep)
- Test safe_stop propagation to OutputManager

---

## Audit Status

- [x] OutputManager — fully audited
- [x] ValidationGate — fully audited
- [x] DisplayManager — fully audited
- [x] DisplayWatcher — fully audited
- [x] GLOutputWindow — fully audited
- [x] CalibrationManager — fully audited
- [x] HardwareManager — fully audited
- [x] EventBus — fully audited
- [x] Error types — fully audited

**Step 1 COMPLETE**
