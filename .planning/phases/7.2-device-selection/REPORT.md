# Phase 7.2 — Camera / Projector Selection UX — Report

**Date:** 2026-08-26
**Branch:** `main` (`e98fa23` + worktree 7.2)
**Status:** `REVIEW` (8 tests) → `DONE` (15 tests, review gate PASS, ruff/mypy clean)
**Sheet:** `1D0_mVe1...` 7.2 `BACKLOG→IN_PROGRESS` → `REVIEW` (100%) → `DONE` (review PASS)

---

## 1. Architecture Audit — Dependency Map (No Duplicates)

**Existing UX inspected (codegraph + grep):**

| Area        | Existing Contract                                                                              | Location                                                                           | Reused By 7.2                                                                                                        |
| ----------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Camera      | `CameraInfo`, `CameraManager`, `CameraProviderFactory`, `CameraProvider.list_cameras()/open()` | `services/camera.py`, `managers/camera_manager.py`, `infrastructure/camera/`       | `CameraSelection.from_camera_info()` reuses `CameraInfo` — no replacement entity                                     |
| Display     | `DisplayInfo`, `DisplayManager`, `DisplayProvider`, `DisplayValidator`, `OutputManager`        | `hardware/display_manager.py`, `services/display.py`, `hardware/output_manager.py` | `ProjectorSelection.from_display_info()` reuses `DisplayInfo` — no replacement                                       |
| Calibration | `CalibrationManager`, `CalibrationSession`, `Pipeline`, `Application` registry                 | `calibration/`, `app.py`, `ui/viewmodels/calibration.py`                           | 7.2 does not duplicate calibration logic                                                                             |
| UI          | `CameraPanel`, `DisplaysPanel`, `ViewModelPanel`, `DisplaysViewModel`, `HardwareManager`       | `ui/panels/`, `ui/viewmodels/`                                                     | Existing panels already display `CameraInfo`/`DisplayInfo` — 7.2 adds typed selection model, not replacement widgets |

**No duplicated domain models:** `CameraSelection`/`ProjectorSelection` are **application-level UX models** that wrap `CameraInfo`/`DisplayInfo` with `SelectionState`, not replacement hardware entities. `SelectionStore` is in-memory selection state, not a manager.

**Existing Qt widgets audited:** `CameraPanel` (list + preview + refresh/open/close), `DisplaysPanel` (display list + topology), `OutputManager` (validated sessions) — all reused via `HardwareManager` facade.

---

## 2. UX Model

**Location:** `src/projectionai/application/device_selection.py` (application layer)

```python
class SelectionState(StrEnum): AVAILABLE, SELECTED, UNAVAILABLE, ERROR

@dataclass(frozen=True) class CameraSelection:
    camera_id, name, backend, resolution, fps, state, is_open, error
    @classmethod from_camera_info(info, state, is_open, error, fps)

@dataclass(frozen=True) class ProjectorSelection:
    display_id, name, geometry (x,y,w,h), resolution, refresh_rate,
    is_primary, kind, supports_fullscreen, validation_ok, state, error
    @classmethod from_display_info(info, state, validation_ok, error)

@dataclass class SelectionStore:
    selected_camera_id, selected_display_id, selected_resolution, selected_backend
    select_camera(), select_display(), set_resolution(), set_backend(), snapshot()
```

**Reuses existing device IDs and provider contracts:** `CameraSelection` wraps `CameraInfo.camera_id`/`max_resolution`/`backend`; `ProjectorSelection` wraps `DisplayInfo.display_id`/`position`/`current_mode`/`capabilities` — no new hardware IDs.

**No replacement hardware entities:** `DisplayInfo`/`CameraInfo` remain canonical; selection models are UX view, not domain.

---

## 3. Camera UX

**Display:** Device name, ID, backend (`opencv`/`mock`), resolution (`max_resolution`), FPS (optional), availability (`is_open`), connection state (`SelectionState`).

**Actions:** `refresh` (via `CameraManager.refresh_cameras()`), `select` (`SelectionStore.select_camera()`), `test` (via `CameraManager.open_camera()`), all distinguished:

- `AVAILABLE` — detected, not selected, can select
- `SELECTED` — `selected_camera_id == camera_id`, highlighted
- `UNAVAILABLE` — not detected or provider error
- `ERROR` — `error` string present, red status

**Existing `CameraPanel` already shows:** `name · backend · res · status` with `LIVE`/`OPEN`/`closed` colors — 7.2 model aligns with it, no duplicate panel.

---

## 4. Projector / Display UX

**Enumeration:** Through `DisplayManager.displays` / `HardwareManager.displays` via `DisplayProvider` (`qt_provider`, `mock_provider`).

**Display:** Name, ID, geometry `(x,y,w,h)`, resolution `(w,h)`, refresh `Hz`, primary/secondary, kind (`projector`/`monitor`), fullscreen capability, validation state (`validation_ok` from `DisplayValidator`).

**Safety:** Reuses `OutputManager` safety checks — `DisplayValidator.validate()` with `require_projector` flag. Monitor/TV classified as `monitor` with `kind=="monitor"` **must not silently become projector** — `ProjectorSelection` sets `validation_ok=False` and `state=UNAVAILABLE` with `error="Display not suitable for projector use"` when `kind != "projector"` or `supports_fullscreen == False`.

**Existing `DisplaysPanel` already enumerates:** `DisplayInfo` with `name`, `position`, `resolution`, `refresh`, `primary`, `kind` — 7.2 adds typed `ProjectorSelection` wrapper.

---

## 5. Safety

**Selection UX does NOT bypass:**

- `DisplayValidator` — `ProjectorSelection.validation_ok` derived from `DisplayValidator` or `info.capabilities`
- `require_projector` — `from_display_info` with `validation_ok=False` for `monitor` kind prevents `monitor`→`projector` silent conversion
- `OutputManager` safe states — `SelectionStore` only stores IDs, does not call `OutputManager.go_live()` directly; `DisplaysViewModel` still validates before `arm`/`live`
- `BLACKOUT`/`FREEZE`/`SAFE STOP` — not bypassed, selection is pre-arm

**Invalid selection fails loudly:** `SelectionStore.set_resolution((0,1080))` raises `ValueError`; `ProjectorSelection` with `kind=monitor` and `validation_ok=False` carries `error` string visible in UI, not silent `AVAILABLE`.

---

## 6. Resolution / Backend

**Supported capture modes:** `CameraInfo.max_resolution` is the reported mode; `SelectionStore.selected_resolution` records actual chosen mode, validated `>0` else `ValueError` — does not silently force unsupported resolutions.

**Actual modes:** `CameraSelection.resolution` and `ProjectorSelection.resolution` are the **actual** `max_resolution`/`current_mode` values from providers, not forced.

**Backend:** From `CameraInfo.backend` (`opencv`/`mock`) and `DisplayInfo` capabilities, via `CameraProviderFactory` / `DisplayProvider` — `SelectionStore.selected_backend` records chosen backend string, from existing factory/configuration, not new.

---

## 7. User Feedback

**Clear status messages (no ambiguous "OK"):**

- `Camera connected` — `state=SELECTED` + `is_open=True`
- `Camera unavailable` — `state=UNAVAILABLE` + `error`
- `Display connected` — `state=AVAILABLE` + `validation_ok=True`
- `Display not suitable for projector use` — `kind=monitor` + `validation_ok=False` + `error`
- `Resolution mismatch` — `set_resolution` raises `ValueError` with `got` value
- `Selection ready` — `snapshot()` returns both IDs non-None
- `Hardware validation pending` — `hardware_pending` 7 gates still exposed via `ProductionWorkflow.hardware_pending` (7.1), not hidden

---

## 8. Tests — Expanded for Review Gate (15 tests)

**File:** `tests/unit/application/test_device_selection.py` (15 tests, no xfail/skip)

| Test                                               | Covers                                                       | Status |
| -------------------------------------------------- | ------------------------------------------------------------ | ------ |
| `test_camera_selection_from_info`                  | `CameraSelection.from_camera_info`                           | PASS   |
| `test_projector_selection_from_display`            | `ProjectorSelection.from_display_info`                       | PASS   |
| `test_selection_store_camera`                      | `select_camera` + `None` clear                               | PASS   |
| `test_selection_store_display_and_resolution`      | `select_display`, `set_resolution` valid/invalid             | PASS   |
| `test_invalid_display_kind_not_bypassed`           | Monitor `kind` → `validation_ok=False` + error               | PASS   |
| `test_refresh_persistence`                         | `snapshot()` retains selection                               | PASS   |
| `test_backend_selection`                           | `set_backend`                                                | PASS   |
| `test_selection_state_enum`                        | `SelectionState` values                                      | PASS   |
| `test_camera_disappears_after_selection`           | Stale camera ID retained until explicit clear                | PASS   |
| `test_display_disappears_after_selection`          | Stale display ID retained, safety check prevents arm         | PASS   |
| `test_selected_display_changes_classification`     | `projector→monitor` reclassification → `validation_ok=False` | PASS   |
| `test_refresh_with_selected_device_missing`        | Refresh with missing device → stale snapshot                 | PASS   |
| `test_invalid_backend`                             | Backend string handling, empty clear                         | PASS   |
| `test_clearing_selections`                         | Full clear of camera/display/resolution/backend              | PASS   |
| `test_snapshot_correctness_after_failure_recovery` | Snapshot after failure/recovery                              | PASS   |

**Run:** `uv run pytest tests/unit/application/test_device_selection.py -q -o addopts=""` — **15 passed in 5.30s** (expanded from 8).

**No xfail/skip/tolerance weakening.**

---

## 9. Quality — Review Gate PASS

```
uv run ruff check src/ → All checks passed!
uv run ruff format --check src/ → 226 files already formatted
uv run mypy src/projectionai/ → Success: no issues found in 225 source files
uv run mypy src/projectionai/application/device_selection.py → Success: no issues found in 1 source file
uv run pytest tests/unit/application/test_device_selection.py -q -o addopts="" → 15 passed in 5.30s
uv run pytest tests/unit/ui -q -o addopts="" → 238 passed in 16.44s
uv run pytest tests/unit/infrastructure/renderer tests/unit/infrastructure/display -q -o addopts="" → 122 passed, 1 skipped in 3.40s
uv run pytest tests/unit/application/test_calibration_workflow.py -q -o addopts="" → 22 passed
```

No regressions. All 8 review gates PASS.

## 9b. Review Gate — Phase 7.2 Critical Review (8 Gates) — PASS

| Gate                      | Requirement                                                                                                                                                     | Evidence                                                                                                                                                                                                                                                                                                                        | Verdict  |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| **1. Architecture**       | `device_selection.py` app-layer only, `CameraInfo`/`DisplayInfo` canonical, no duplicate models                                                                 | `src/projectionai/application/device_selection.py` 84 stmts, wraps `CameraInfo`/`DisplayInfo`, `SelectionStore` only UX state, existing `CameraPanel`/`DisplaysPanel` authoritative                                                                                                                                             | **PASS** |
| **2. Camera Selection**   | Refresh preserves selected when present, UNAVAILABLE if disconnected, invalid fails loudly, backend actual, no fake device                                      | Tests `test_refresh_persistence`, `test_camera_disappears_after_selection`, `test_refresh_with_selected_device_missing`, `test_camera_selection_from_info`                                                                                                                                                                      | **PASS** |
| **3. Display/Projector**  | Actual `DisplayInfo` values surfaced, geometry/resolution/refresh accurate, `monitor` cannot become `projector`, fullscreen respected, `DisplayValidator` final | Tests `test_projector_selection_from_display`, `test_invalid_display_kind_not_bypassed`, `test_selected_display_changes_classification`                                                                                                                                                                                         | **PASS** |
| **4. Resolution/Backend** | Invalid resolutions fail loudly, not silently forced, backend from existing factory, stale invalidated                                                          | Tests `test_selection_store_display_and_resolution`, `test_invalid_backend`, `test_refresh_with_selected_device_missing`                                                                                                                                                                                                        | **PASS** |
| **5. Safety**             | No bypass of `OutputManager` safety, `require_projector` enforced, `BLACKOUT`/`FREEZE` untouched, invalid cannot arm/live                                       | `SelectionStore` only stores IDs, `ProjectorSelection.validation_ok` prevents bypass, `require_projector` remains in `OutputManager`                                                                                                                                                                                            | **PASS** |
| **6. Failure/Recovery**   | Camera/display disappears, classification change, refresh missing, invalid backend/resolution, clearing, snapshot after failure                                 | Tests `test_camera_disappears_after_selection`, `test_display_disappears_after_selection`, `test_selected_display_changes_classification`, `test_refresh_with_selected_device_missing`, `test_invalid_backend`, `test_clearing_selections`, `test_snapshot_correctness_after_failure_recovery` — 7 new, all PASS, no xfail/skip | **PASS** |
| **7. Quality**            | `ruff`, `format`, `mypy`, `test_device_selection` 15 passed, `ui` 238, `renderer+display` 122                                                                   | All 6 quality commands above — 0 failures                                                                                                                                                                                                                                                                                       | **PASS** |
| **8. Google Sheet**       | If PASS `REVIEW→DONE`, append history/changelog, recalc dashboards; if FAIL keep `REVIEW`/`BLOCKED`                                                             | `01_MASTER_PLAN` 7.2 `REVIEW→DONE` at row 38, `16_STATUS_HISTORY` `REVIEW→DONE`, `12_CHANGELOG` `TASK_COMPLETED`                                                                                                                                                                                                                | **PASS** |

**Tests added for gaps:** 7 new covering disappearance, reclassification, refresh missing, invalid backend, clearing, snapshot recovery — deterministic, no xfail.

**Accepted:** All 8 gates. **Rejected:** None. **Remaining limitations:** Hardware-pending 7 gates still `HARDWARE_PENDING` (correct), synthetic path not yet wired to real capture (7.5).

---

## 10. Risks & Hardware-Pending

- **Hardware-pending remains:** 7 gates still `HARDWARE_PENDING` in `10_VALIDATION_GATES` — 7.2 does not mark them `PASS`, only exposes via `SelectionState` + `validation_ok`.
- **No duplicate domain models:** `CameraSelection`/`ProjectorSelection` wrap, not replace `CameraInfo`/`DisplayInfo`.
- **Safety not bypassed:** `DisplayValidator` + `require_projector` + `OutputManager` checks remain authoritative; invalid display fails visibly.

---

## 11. Files Changed (Diff vs `e98fa23`)

- **New:** `src/projectionai/application/device_selection.py` (84 stmts) — typed selection model, no math duplicates
- **New:** `tests/unit/application/test_device_selection.py` (8 tests) — enumeration, selection, safety, resolution, backend, refresh
- **Not touched:** `src/projectionai/services/*` math, `domain/*` entities, `D:\PROJECTIONAI-camera`

---

## 12. Next — DONE, STOP AT REVIEW GATE PASS

**7.2 is now `DONE` (100%) — review gate PASS (8 gates, 15 tests, 0 failures). Do not start 7.3 automatically.**

Sheet: `01_MASTER_PLAN` 7.2 `IN_PROGRESS→REVIEW` 100% → `DONE` at row 38, `16_STATUS_HISTORY` `REVIEW→DONE`, `12_CHANGELOG` `TASK_COMPLETED` CH-009 with `15 passed, architecture, safety`, `14_PHASE_DETAIL` `DONE (7.2 REVIEW PASS)`, `10_VALIDATION_GATES` 7 pending unchanged, `02_GANTT`/`03_KANBAN`/`04_BURNDOWN`/`05_CFD`/`00_DASHBOARD` auto via formulas.

**STOP AFTER REVIEW — DO NOT START 7.3.**
