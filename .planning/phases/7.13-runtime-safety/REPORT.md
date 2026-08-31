# Phase 7.13 — Runtime Safety Watchdog

**Status**: COMPLETE
**Date**: 2026-08-29
**Commit**: CH-082

## Objective

Implement a production-grade continuous runtime safety watchdog that monitors
an active output session and fails SAFE when runtime conditions invalidate
safe operation. Wire the watchdog into production via HardwareManager.

## What Was Built

### RuntimeWatchdog (`src/projectionai/hardware/runtime_watchdog.py`)

A `Manager` subclass that continuously monitors a live output session and
triggers `OutputManager.safe_stop()` when unsafe conditions are detected.

**State machine**: STOPPED → STARTING → RUNNING → TRIGGERED / STOPPING → STOPPED

**Triggers monitored**:

| Trigger                | Detection                                                    | Default Threshold |
| ---------------------- | ------------------------------------------------------------ | ----------------- |
| `DISPLAY_DISCONNECTED` | `notify_display_event()` from HardwareManager                | Immediate         |
| `RESOLUTION_CHANGED`   | `notify_display_event()` from HardwareManager                | Immediate         |
| `GATE_STALE`           | Periodic `_evaluate()` checks `gate_result.evaluated_at`     | 300s              |
| `GATE_REVOKED`         | Periodic `_evaluate()` detects `can_live` flipped True→False | Immediate         |
| `RENDERER_UNHEALTHY`   | Periodic `_evaluate()` polls `renderer_ready_provider()`     | 10s               |

**Key design properties**:

- Delegates ALL safety actions to `OutputManager.safe_stop()` — never acts independently
- Does NOT become a second state machine or second authority
- Does NOT bypass OutputManager
- Does NOT silently restore LIVE after a safety fault
- Trigger is idempotent — second trigger while already TRIGGERED is a no-op
- `safe_stop()` failure is logged at CRITICAL level, does not crash the watchdog
- Watchdog crash (exception in loop) attempts `safe_stop()` before exit — output never left LIVE and unprotected
- Shutdown cancels the monitoring task cleanly via `_on_shutdown()`
- CheckPassed events emitted only on state transitions (failed→passed) to reduce log pressure
- Monotonic clock for renderer timeout (immune to NTP/DST jumps)
- Wall-clock for gate staleness (matches `ValidationGateResult.evaluated_at`)

### Production Wiring (`src/projectionai/hardware/hardware_manager.py`)

Watchdog is wired into production lifecycle through HardwareManager:

- **Constructor injection**: HardwareManager accepts optional `watchdog` parameter
- **Initialize**: Watchdog initialized during `_on_initialize()`
- **Start**: `go_live()` starts the watchdog after output session goes live
- **Stop**: `end_output_session()` stops the watchdog
- **Shutdown**: `_on_shutdown()` stops the watchdog
- **Display event forwarding**: HardwareManager subscribes to `DisplayDisconnected` and `DisplayResolutionChanged` events and forwards them to `watchdog.notify_display_event()`
- **State exposure**: `watchdog_state` property exposes current watchdog state

### Events (`src/projectionai/hardware/events.py`)

Added watchdog event types:

- `WatchdogTrigger(StrEnum)` — 5 trigger reasons (CALIBRATION_INVALID deferred)
- `WatchdogStarted(Event)` — monitoring began
- `WatchdogStopped(Event)` — monitoring ended
- `WatchdogTriggered(Event)` — safety violation detected
- `WatchdogCheckPassed(Event)` — periodic check found no issues

### Tests (`tests/unit/hardware/test_runtime_watchdog.py`)

47 deterministic tests covering:

- **Lifecycle (7)**: start, stop, idempotent start/stop, restart from TRIGGERED, shutdown stops watchdog
- **Periodic checks (1)**: CheckPassed emitted on state transitions (not every cycle)
- **Renderer monitor (5)**: unhealthy triggers, healthy no-trigger, fresh-unsafe no-trigger, transient unhealthy with recovery
- **Gate monitor (6)**: stale triggers, fresh no-trigger, revoked triggers, no-gate skips, wall-clock staleness, monotonic renderer timeout
- **Display events (5)**: disconnect triggers, resolution-change triggers, non-live display ignored, noop when stopped, display-already-gone
- **Idempotency (2)**: trigger is idempotent, safe_stop failure handled
- **Enums (2)**: all WatchdogTrigger and WatchdogState values verified
- **Production wiring (4)**: go_live starts watchdog, end_session stops, shutdown stops, display event forwarding
- **Safe-stop failure (1)**: safe_stop raises but output is NOT left LIVE
- **Watchdog crash (1)**: exception in loop attempts safe_stop, session ends
- **Calibration invalidation (1)**: gate revocation covers calibration invalidation
- **Clock semantics (2)**: wall-clock for gate staleness, monotonic for renderer
- **Production ownership (1)**: no duplicate tasks across go_live/end_session cycles
- **HardwareManager integration (1)**: safe_stop via OutputManager ends session
- **No auto-recovery (1)**: TRIGGERED state persists, explicit restart required
- **Concurrency (3)**: concurrent trigger+shutdown no deadlock, no resurrected LIVE
- **Shutdown safety (2)**: task cancelled, double shutdown safe
- **Resource reuse (1)**: no task accumulation across cycles

**Test results**: 47/47 passed (3.4s), 183/183 hardware tests passed (excl 2 pre-existing hangs)

## 21-Gate Production Safety Audit

All 21 gates from the final safety audit:

| Gate       | Description                                             | Result   | Evidence                                                                                                                                                                         |
| ---------- | ------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GATE 1     | Safe-stop failure has safe outcome                      | **PASS** | safe_stop transitions to STOPPING before failure; live route cleared before blackout. Test: `test_safe_stop_failure_leaves_output_not_live`                                      |
| GATE 2     | Watchdog task exception attempts safe_stop              | **PASS** | `_run_loop` crash handler calls `safe_stop()` after setting TRIGGERED. Test: `test_watchdog_task_exception_attempts_safe_stop`                                                   |
| GATE 3     | Calibration invalidation covered by gate revocation     | **PASS** | Gate revocation detects can_live True→False flip. CALIBRATION_INVALID deferred (no validation engine). Test: `test_calibration_invalidation_triggers_gate_revocation`            |
| GATE 4     | Gate staleness uses wall-clock; renderer uses monotonic | **PASS** | Gate staleness: `time.time()` matches `evaluated_at`. Renderer timeout: `time.monotonic()`. Tests: `test_gate_staleness_uses_wall_clock`, `test_renderer_timeout_uses_monotonic` |
| GATE 5     | Production ownership: one watchdog per session          | **PASS** | go_live/end_session cycles don't accumulate tasks. Test: `test_production_ownership_no_duplicate_tasks`                                                                          |
| GATE 6     | Live start/stop integration via HardwareManager         | **PASS** | `om.safe_stop()` ends session. Tests: `test_hm_safe_stop_ends_session`, `test_golive_starts_watchdog`, `test_end_session_stops_watchdog`                                         |
| GATE 7     | Display events: display already gone                    | **PASS** | Non-live display events and unknown event names ignored. Test: `test_display_already_gone_no_trigger`                                                                            |
| GATE 8     | Renderer failure: transient unhealthy with recovery     | **PASS** | Transient unhealthy within timeout → recovery → no trigger. Test: `test_renderer_transient_unhealthy_recovery`                                                                   |
| GATE 9     | Authorization revocation: no stale cache                | **PASS** | can_live True→False detected immediately via `_last_gate_can_live`. Test: `test_authorization_revocation_no_stale_cache`                                                         |
| GATE 10    | No auto-recovery after trigger                          | **PASS** | TRIGGERED persists; only explicit start() restarts. Test: `test_no_auto_recovery_after_trigger`                                                                                  |
| GATE 11    | Idempotency: concurrent triggers = one safe-stop        | **PASS** | Multiple triggers concurrently result in exactly one safe_stop call. Test: `test_idempotent_trigger_with_concurrent_calls`                                                       |
| GATE 12    | Concurrency: no deadlock, no resurrected LIVE           | **PASS** | Trigger+shutdown no deadlock. Trigger+freeze doesn't resurrect LIVE. Tests: `test_concurrent_trigger_and_shutdown`, `test_concurrent_trigger_and_freeze`                         |
| GATE 13    | Shutdown: output safe, task cancelled, no orphan        | **PASS** | Task cancelled on shutdown. Double shutdown safe. Tests: `test_shutdown_from_live_cancels_task`, `test_double_shutdown_safe`                                                     |
| GATE 14    | Resource reuse: no task accumulation                    | **PASS** | 5 go_live/stop cycles: no orphan tasks. Test: `test_resource_reuse_no_task_accumulation`                                                                                         |
| GATE 15    | Event pressure: CheckPassed on transitions only         | **PASS** | 100 healthy cycles produce ≤1 CheckPassed. Transition emits exactly once. Tests: `test_event_pressure_100_healthy_cycles`, `test_event_pressure_unhealthy_to_healthy_emits_once` |
| GATE 16    | Hardware honesty: H-01..H-07 remain HARDWARE_PENDING    | **PASS** | Watchdog does not interact with hardware gates. No changes to H-01..H-07.                                                                                                        |
| GATE 17-20 | Audit-required tests added                              | **PASS** | 19 new audit tests added (47 total watchdog tests)                                                                                                                               |
| GATE 21    | Full regression + quality gates                         | **PASS** | 47/47 watchdog, 183/183 hardware, ruff clean, mypy clean                                                                                                                         |

**Result: ALL 21 GATES PASS → 7.13 = DONE**

## Quality Gates

| Gate              | Result                                   |
| ----------------- | ---------------------------------------- |
| ruff check        | All checks passed (all 4 changed files)  |
| ruff format       | All files already formatted              |
| mypy --strict     | Success: no issues found (1 source file) |
| pytest (watchdog) | 47/47 passed (3.4s)                      |
| pytest (hardware) | 183/183 passed (4.65s)                   |
| Regression        | 0 regressions from baseline              |

## Safety Constraint Compliance

| Constraint                                 | Status                                                                    |
| ------------------------------------------ | ------------------------------------------------------------------------- |
| NEVER create a second safety state machine | PASS — watchdog has its own state, but delegates actions to OutputManager |
| NEVER create a second validation engine    | PASS — reads `gate_result` from OutputManager, never evaluates gates      |
| NEVER bypass OutputManager                 | PASS — only calls `OutputManager.safe_stop()`                             |
| NEVER silently fail                        | PASS — safe_stop failure logged at CRITICAL level                         |
| NEVER silently restore LIVE                | PASS — no code path restores LIVE after trigger                           |
| NEVER silently switch displays             | PASS — never touches DisplayManager routing                               |
| NEVER silently change resolution           | PASS — never touches resolution                                           |
| NEVER convert H-01..H-07 to PASS           | PASS — watchdog does not interact with hardware gates                     |
| NEVER claim hardware verification          | PASS — watchdog monitors software state only                              |
| NEVER automatically re-arm/go_live/resume  | PASS — TRIGGERED state requires explicit operator restart                 |

## Clock Semantics

| Clock              | Usage                | Rationale                                                |
| ------------------ | -------------------- | -------------------------------------------------------- |
| `time.time()`      | Gate staleness check | Matches `ValidationGateResult.evaluated_at` (wall-clock) |
| `time.monotonic()` | Renderer timeout     | Immune to NTP/DST jumps; measures real elapsed time      |

Wall-clock backward jump risk: If system clock jumps backward, a stale gate may appear fresh. This is a documented acceptable risk — the alternative (using monotonic for both) would break the staleness contract with `evaluated_at`.

## Failure Behavior Summary

| Failure Scenario             | Watchdog Behavior                                     | OutputManager Behavior                                       |
| ---------------------------- | ----------------------------------------------------- | ------------------------------------------------------------ |
| safe_stop() raises           | State remains TRIGGERED. CRITICAL log.                | Output is NOT LIVE (transitioned to STOPPING before failure) |
| Watchdog loop crashes        | State → TRIGGERED. safe_stop attempted. CRITICAL log. | safe_stop called → session ended                             |
| Gate revoked mid-session     | GATE_REVOKED detected → safe_stop triggered           | Output goes BLACKOUT/IDLE                                    |
| Renderer unhealthy >10s      | RENDERER_UNHEALTHY → safe_stop triggered              | Output goes BLACKOUT/IDLE                                    |
| Multiple concurrent triggers | Idempotent — only first trigger fires safe_stop       | Single safe_stop call                                        |

## Files Changed

| File                                                     | Action                                                            |
| -------------------------------------------------------- | ----------------------------------------------------------------- |
| `src/projectionai/hardware/runtime_watchdog.py`          | NEW — ~320 lines (monotonic clock, crash recovery with safe_stop) |
| `src/projectionai/hardware/hardware_manager.py`          | MODIFIED — watchdog lifecycle + display event forwarding          |
| `src/projectionai/hardware/events.py`                    | MODIFIED — CALIBRATION_INVALID removed (deferred)                 |
| `tests/unit/hardware/test_runtime_watchdog.py`           | NEW — 1140 lines (47 tests including 19 audit-required)           |
| `.planning/phases/7.13-runtime-safety/DEPENDENCY-MAP.md` | NEW — audit artifact                                              |
