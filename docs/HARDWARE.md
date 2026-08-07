# HARDWARE — Hardware Management & Display Validation

## What Was Built

A hardware abstraction + display validation layer that gives the app a
single, event-driven view of the physical display chain (monitors,
projectors, virtual displays) and a validated output session lifecycle
(preview → armed → live → blackout). It lives in `src/projectionai/hardware/`
plus two `DisplayProvider` implementations:

| Module                                    | Responsibility                                                                        |
| ----------------------------------------- | ------------------------------------------------------------------------------------- |
| `hardware/models.py`                      | `DisplayInfo`, `DisplayMode`, `DisplayCapabilities`, `HardwareStatus`, `OutputWindow` |
| `hardware/classifier.py`                  | `DisplayClassifier` / `DisplayKind` — kinds displays by vendor/model name             |
| `hardware/display_manager.py`             | `DisplayManager` — topology cache, per-display diffing, typed change events           |
| `hardware/display_watcher.py`             | `DisplayWatcher` — polls the provider and triggers manager refresh                    |
| `hardware/display_validator.py`           | `DisplayValidator` — gate checks before any live switch                               |
| `hardware/output_manager.py`              | `OutputManager` — preview/live sessions with safe, validated switching                |
| `hardware/hardware_manager.py`            | `HardwareManager` — facade over manager + validator + watcher                         |
| `hardware/patterns.py`                    | `PATTERNS`, `PatternSpec`, `PatternKind` — 8 built-in test patterns                   |
| `hardware/events.py`                      | Typed events: display topology + output lifecycle                                     |
| `hardware/errors.py`                      | `HardwareError` hierarchy                                                             |
| `services/display.py`                     | `DisplayProvider` service contract (Protocol)                                         |
| `infrastructure/display/mock_provider.py` | Deterministic `MockDisplayProvider` (tests + offline dev)                             |
| `infrastructure/display/qt_provider.py`   | Qt screen enumeration provider (production)                                           |

Design goals:

- **No new external dependencies.** Qt (already present) + stdlib only.
- **Decoupled from the output path.** The status bar reads a polled
  `HardwareStatus` snapshot; the output path never waits on UI.
- **Safe switching.** A live switch is _validated first_; a failed switch
  raises `OutputSwitchError` and leaves the previous state untouched.
- **Testable headless.** `MockDisplayProvider` + Qt `offscreen` platform
  make the whole subsystem testable in CI without hardware.

---

## Data model

| Type                  | Role                                                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `DisplayInfo`         | One connected display: id, name, vendor/model, connection, kind, position, current + supported modes, capabilities |
| `DisplayMode`         | Resolution + refresh rate (`label` like `1920x1200 @ 60Hz`)                                                        |
| `DisplayCapabilities` | Fullscreen, primary-able, rotation, hotplug, mirroring                                                             |
| `HardwareStatus`      | Snapshot: display/projector/monitor/virtual/unknown counts, issue + warning counts, `healthy`, `ready`             |
| `OutputWindow`        | Window handle abstraction (move/fullscreen/geometry)                                                               |
| `ValidationReport`    | `is_ok` + `issues` (+ `summary`) from `DisplayValidator`                                                           |
| `ValidationIssue`     | Severity (`ERROR`/`WARNING`) + code + message (+ display id)                                                       |
| `PatternSpec`         | Test pattern: kind, name, description, `generate(width, height)`                                                   |

`DisplayInfo` is the canonical topology record consumed by every manager;
`HardwareStatus` is what the UI polls for the status bar.

---

## Display classifier

`DisplayClassifier` maps raw display metadata to a `DisplayKind`:

| Kind        | Meaning                                                                     |
| ----------- | --------------------------------------------------------------------------- |
| `PROJECTOR` | Vendor/model matches projector patterns (Epson, BenQ, Optoma, ViewSonic, …) |
| `MONITOR`   | Standard monitor                                                            |
| `VIRTUAL`   | Virtual/synthetic displays (e.g. IDD, Moonlight)                            |
| `UNKNOWN`   | Not otherwise classified                                                    |

`DEFAULT_CLASSIFIER` is the shared instance; patterns are extensible
(`projector_patterns` / `monitor_patterns` are tuple-appendable).

---

## Managers

### DisplayManager (topology cache)

- `refresh()` — pulls `provider.list_displays()`, diffs against the cache,
  and emits one event per change: `DisplayConnected`, `DisplayDisconnected`,
  `DisplayPrimaryChanged`, `DisplayResolutionChanged` (resolution changed),
  `DisplayRefreshRateChanged` (rate changed, same resolution),
  `DisplayOrientationChanged`, plus a `DisplaysRefreshed` summary event.
- `get(display_id)` / `has(display_id)` / `get_modes(display_id)` — typed
  lookups; `get` raises `DisplayNotFoundError` for unknown ids.
- `identify(display_id)` — forwards to the provider's identify pulse.
- `set_preview_output` / `set_live_output` — route tracking (emits
  `DisplayPreviewOutputChanged` / `DisplayLiveOutputChanged`).
- `set_fullscreen` / `move_window_to` / `restore_window` — window placement.

Change detection compares the _resolution_ for `DisplayResolutionChanged`
and the _refresh rate_ for `DisplayRefreshRateChanged` independently —
a mode change that only bumps the rate emits the rate event, not the
resolution event.

### DisplayWatcher (hotplug polling)

Periodically calls `display_manager.refresh()`. In the app it polls every
1 s; tests use 0.05 s. Gracefully handles provider errors (logged, not
raised) so a flaky driver can't crash the app.

### DisplayValidator (gate checks)

`validate(ValidateInputs) -> ValidationReport` runs, in order:

| Check                       | Severity | Condition                                      |
| --------------------------- | -------- | ---------------------------------------------- |
| `renderer_not_ready`        | ERROR    | Renderer not ready → live would show nothing   |
| `no_display_connected`      | ERROR    | No displays at all                             |
| `live_display_not_found`    | ERROR    | Live target id no longer connected             |
| `preview_display_not_found` | ERROR    | Preview target id no longer connected          |
| `no_projector_available`    | ERROR    | No live target chosen and no projector present |
| `live_target_not_projector` | WARNING  | Live target is not a projector                 |
| `resolution_unsupported`    | ERROR    | Target mode not in supported modes             |
| `low_resolution`            | WARNING  | Below minimum live resolution                  |
| `low_refresh_rate`          | WARNING  | Below minimum live refresh (motion stutter)    |
| `software_renderer`         | WARNING  | GPU is a software renderer                     |
| `duplicate_output`          | WARNING  | Live and preview target the same display       |

### OutputManager (output sessions)

Session lifecycle: `begin_session(preview_id?)` → `set_preview` / `arm` /
`go_live` / `blackout` / `end_session`, tracked by an immutable
`OutputSession` record (state machine: `IDLE → PREVIEW → ARMED → LIVE →
BLACKOUT`), with a session history.

- `begin_session()` with no preview → `IDLE`; with a preview display →
  `PREVIEW`. Unknown preview id raises `DisplayNotFoundError`.
- `go_live()` validates first; failure raises `OutputSwitchError` (with the
  report) and state is unchanged. With no explicit target it auto-routes to
  the first projector; no projector → rejected.
- `switch_live_to(display_id, window?)` = `set_live_target` + `go_live` +
  move the window onto the display (only after validation passes).
- `end_session()` is safe from any state and clears preview/live routing.

### HardwareManager (facade)

Aggregates the stack: `snapshot() -> HardwareStatus`,
`validate() -> ValidationReport`, session shortcuts
(`begin_output_session`, `arm_output`, `go_live`, `emergency_blackout`,
`end_output_session`), `get_display`, `identify_display`, `move_window_to`.
The UI and `Application` talk to _this_ object only.

---

## Events

All events are frozen dataclasses on the shared event bus:

| Event                         | Meaning                               |
| ----------------------------- | ------------------------------------- |
| `DisplayConnected`            | A display appeared                    |
| `DisplayDisconnected`         | A display disappeared                 |
| `DisplayPrimaryChanged`       | Primary display changed               |
| `DisplayResolutionChanged`    | Resolution changed (old/new mode)     |
| `DisplayRefreshRateChanged`   | Refresh rate changed, same resolution |
| `DisplayOrientationChanged`   | Orientation changed                   |
| `DisplaysRefreshed`           | Poll completed (summary)              |
| `DisplayPreviewOutputChanged` | Preview route changed                 |
| `DisplayLiveOutputChanged`    | Live route changed                    |
| `OutputSessionStarted`        | Session created (id, preview id)      |
| `OutputSessionEnded`          | Session closed (id)                   |
| `OutputPreviewChanged`        | Session preview target changed        |
| `OutputArmed`                 | Session armed (id, live target)       |
| `OutputLiveStarted`           | Session went live (id, display id)    |
| `OutputBlackout`              | Session blacked out (id)              |

---

## Test patterns

`PATTERNS` ships 8 built-in test patterns (each `PatternSpec` has a
`generate(width, height) -> PIL Image`):

`checkerboard`, `grid`, `crosshair`, `colour_bars`, `alignment_grid`,
`pixel_grid`, `gamma_ramp`, `safe_border`

— enough for alignment, focus, colour, and geometry checks before a show.

---

## Application wiring (`app.py`)

Built in `Application.initialize()` (injectable as `hardware_manager=` for
tests) and registered as `"hardware"`:

```
DisplayManager → DisplayWatcher (1 s poll) → DisplayValidator
              → OutputManager (renderer_ready_provider=lambda: self._renderer is not None)
              → HardwareManager (facade) → app.hardware
```

UI wiring:

- `StatusViewModel(hardware_provider=lambda: displays_vm.snapshot)` — the
  status bar polls a `HardwareStatus` snapshot instead of subscribing to
  events, keeping the output path decoupled.
- `StatusBar` shows `3 disp · 1 proj` (hardware segment) and `● OK` /
  `● WARN` (health dot: `HardwareStatus.healthy`).
- `MainWindow` presets (Projection / Calibration / Live Show / Multi
  Projector) enable the `displays` panel and pass the hardware provider
  through to the status bar.

---

## Verification

| Gate       | Result                                                                                                                    |
| ---------- | ------------------------------------------------------------------------------------------------------------------------- |
| Unit tests | 91 tests in `tests/unit/hardware/` + `tests/unit/infrastructure/display/`; full suite 735 passed                          |
| Ruff       | Clean on hardware, UI, app, and tests                                                                                     |
| Mypy       | Clean on `src/projectionai/hardware` + UI + `app.py` (strict)                                                             |
| Smoke test | Offscreen boot with `MockDisplayProvider`: status bar reads `3 disp · 1 proj` and `● OK`; window screenshot saved (26 KB) |
| Events     | Change events verified per-kind: connect/disconnect/resolution/refresh-rate/orientation/primary                           |

Test coverage highlights: refresh-rate-only changes emit
`DisplayRefreshRateChanged` (not the resolution event); unknown displays
raise `DisplayNotFoundError`; failed validation raises `OutputSwitchError`
with state unchanged; `begin_session()` without preview starts `IDLE`;
snapshot reflects topology only after the watcher applies it.
