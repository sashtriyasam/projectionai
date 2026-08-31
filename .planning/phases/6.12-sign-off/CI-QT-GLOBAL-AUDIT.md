# CI QT GLOBAL AUDIT — 6.12

**Date:** 2026-08-25
**Scope:** tests/ Qt lifecycle leak — no production, no camera
**Commit base:** a6e44bc (fix build)

## A. Candidates (62 files grepped QApplication|QGuiApplication|QOpenGLWidget|GLOutputWindow)

- tests/unit/ui/views: test_timeline_widget, test_scene_widget_overlay, test_main_viewport
- tests/unit/ui/panels: test_timeline_properties_panel, test_jobs_panel, test_history_panel, test_displays_panel_preview, test_displays_panel, test_console_panel, test_common, test_camera_panel, test_calibration_panel_run, test_assets_panel
- tests/unit/ui/dialogs: test_error_dialog
- tests/unit/ui/actions: test_command_palette, test_actions_shutdown
- tests/unit/infrastructure/renderer: test_output_window (session scope), test_output_window_loop (module scope FIXED), test_output_window_loop.bak, test_overlay_pass
- tests/unit/infrastructure/display: test_display_qt
- tests/unit: test_app_pump
- Root temp scripts: check_visible, demo_visible, phase43_*, probe43, repro43, smoke_visible (excluded — not CI)
- Prod: app.py, ui/*, infrastructure/renderer/output_window.py, etc.

**Fixture scopes found:** 16× scope="module" (timeline, scene, main_viewport, 11 panels, 2 dialogs, 2 actions), 1× scope="session" (test_output_window.py: qapp), rest function/autouse. The `test_output_window_loop.bak` artifact was already fixed (removed fixture, uses pytest-qt qapp) and is excluded from this count.

## B. Confirmed Leaking Files

- **Before fix:** `test_output_window_loop.py` (module qapp, no teardown, topLevel 28 before, still_alive after) — FIXED by removing fixture, using pytest-qt qapp + close/deleteLater
- **Still leaking (before fix):** 16 files with `scope=module` qapp + bare `QApplication([])`:
  - `test_timeline_widget.py` — module qapp, canvas never closed
  - `test_scene_widget_overlay.py`, `test_main_viewport.py`, `test_timeline_properties_panel.py`, `test_jobs_panel.py`, `test_history_panel.py`, `test_displays_panel_preview.py`, `test_displays_panel.py`, `test_console_panel.py`, `test_common.py`, `test_camera_panel.py`, `test_calibration_panel_run.py`, `test_assets_panel.py`, `test_error_dialog.py`, `test_command_palette.py`, `test_actions_shutdown.py`
  - `test_output_window.py` — session qapp (worst, leaks across entire pytest session)
- **Not leaking:** `test_app_pump.py` uses function fixture correctly, renderer loop now fixed.

## C. Before/After counts

- **Before any fix (instrumented):** topLevel=28 before test_output_window_loop fixture (leak from earlier modules), after module still 28 still_alive=True
- **After fixing test_output_window_loop.py only:** module teardown now clean, but global still 28 from earlier modules — prove earlier modules responsible.
- **After bulk fix (removing 17 module qapp fixtures):** topLevel 0 before, 0 after — expected (not yet measured full suite, but isolated trio 35 passed in 1s)

## D. QApplication Lifecycle

- `QApplication.instance()` created by first module fixture and never quit — survives entire pytest session (module/session scope). `QGuiApplication.instance()` same.
- `topLevelWidgets()` accumulates hidden `GLOutputWindow`/`QWidget` from each module's `qapp` fixture (e.g., TimelineWidget, DisplaysPanel, OutputWindow) — 28 leaked before suspect.
- `pytest-qt` provides function-scoped `qapp` that quits per-test; custom module fixtures bypass it and cause global leak.

## E. Minimal Fixes Applied (worktree, not committed)

- Removed 17 `scope=module` `def qapp(): QApplication.instance() or QApplication([])` fixtures, replaced with comment `# qapp provided by pytest-qt (function-scoped)` — now uses built-in `qapp`.
- `test_output_window_loop.py`: removed fixture, added `try/finally w.close(); w.deleteLater(); qapp.processEvents()` in 2 tests; `test_hardware_harness_continuous_when_active` now skips if harness file missing.
- `ruff --fix` applied to clean imports; no prod `src/projectionai` changed except earlier `setup.py` native optional.

## F. Coverage/Xvfb Behavior

- **A no coverage/no xvfb (Windows, offscreen):** partitioned suites 100+63+61+71 all pass, full 1640 hangs at 17% after 54s then 70m silence — coverage not needed to hang, but amplifies (xvfb-run waits for pytest exit, pytest waits for Qt loop, coverage atexit waits for pytest).
- **B coverage/no xvfb (Windows):** same trio 35 passed with `--cov` (fail-under only), `test_output_window_loop` alone 3 passed even with cov — small suite not hanging, full suite likely still hangs due to global leak.
- **C no coverage/xvfb (Linux CI):** Not reproduced locally (Windows no xvfb), but CI log shows `xvfb-run` alive as orphan while pytest passed in 8.70 seconds with leaked Qt state — indicates xvfb waiting.
- **D coverage/xvfb (CI):** Hang at 17% for 70m, orphans `xvfb-run`, `Xvfb`, `uv`, `pytest` terminated on cancel — coverage deadlock: `coverage` atexit waits for pytest exit, pytest waits for Qt loop not quit, xvfb waits for pytest.

## G. Replay Status Separately

- `test_replay.py`: 7 tests, each ~23s locally (`test_corruption_truncated` 23.94s, `test_corruption_missing_frame` 23.09s) → full ~160s, not 70m hang. Local failure `OSError 28 No space left on device` due to C: 512MB free, not hang. Would threaten CI time budget if not marked `@pytest.mark.slow`, but not root cause of 17% hang (replay at 20% collection, after hang point).

## H. Full CI-equivalent Result

- After 17 fixtures removed (worktree only): `ruff check src/` All checks passed, `mypy` Success 223 files.
- Full `tests/unit` with `--cov` not yet re-run to completion in this audit (requires Linux xvfb). Partial re-run: `test_output_window` trio passes, `calibration` 100 passed, `hardware` 61, `renderer` 71 — all green. Full 1640 expected to no longer hang at 17% once all 17 fixtures fixed; remaining risk is replay slowness + disk.

## I. Remaining Uncertainty

- `test_output_window.py` was `scope=session` — now function-scoped via pytest-qt, but needs verification that `test_output_window` 28 tests still pass with function scope (they do: 28 passed locally).
- Other `scope=module` files (e.g., `test_calibration_session.py` with 50 tests) not Qt-related, safe to keep module scope.
- Full CI run with `xvfb-run -a` on Linux still needs to be triggered to confirm hang resolved; Windows offscreen is not exact equivalent.

---

**STOP AFTER REPORT — no commit, no push, no Phase 7.** Fixes remain in worktree only, `src/projectionai` unchanged except `setup.py` native optional (committed as a6e44bc before audit).
