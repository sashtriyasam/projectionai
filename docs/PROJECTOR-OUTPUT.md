# Projector Output — Dedicated Fullscreen Display Window

The Displays panel (left dock) now drives a **dedicated borderless
fullscreen output window** rendered by ModernGL. Test patterns, blackout,
and freeze flow through the real render pipeline onto a display the user
**explicitly selects** — the primary monitor is never made fullscreen
unless explicitly chosen. ESC on the output window exits the session.

## Architecture

```
DisplaysPanel ──► DisplaysViewModel (Qt-free, gates + state)
      │                     │ attach_output_window()
      │  run_async()        ▼
      │               GLOutputWindow (borderless QOpenGLWidget)
      ▼                     │
DisplaysViewModel ◄─ event bus ◄── DisplayWatcher / OutputManager
      │  switch_live_output / move_window_to / freeze / blackout
      ▼
HardwareManager facade ──► DisplayManager + OutputManager
```

### Layers

- **HardwareManager** — new facade passthroughs (no new state machine):
  `refresh_displays()`, `switch_live_output(display_id, window=None)`,
  `restore_window(window)`, `freeze_output()`, `unfreeze_output()`.
- **DisplaysViewModel** (`ui/viewmodels/displays.py`) — Qt-free.
  Wraps the facade, owns the _output surface contract_:
  `OutputSurface` (a structural `Protocol` extending the hardware
  `OutputWindow` protocol with `set_pattern` / `set_blackout` /
  `set_freeze` / `hide`). The shell injects the real window through
  `attach_output_window(window)`; tests inject doubles. User feedback
  flows through `message` / `set_message` / `clear_message`.
- **DisplaysPanel** (`ui/panels/displays_panel.py`) — DISPLAYS /
  PROJECTORS / VALIDATION / OUTPUT sections. Display entries show
  `name · device · mode · kind · connection · primary`, with a
  **LIVE**/**PREVIEW** role marker and a tooltip listing supported
  modes. The OUTPUT section has the eight spec actions — **Select as
  Preview, Select as Live, Identify, Test Pattern, Fullscreen,
  Blackout, Exit Output, Refresh** — plus a checkable **Freeze** toggle
  and a pattern picker (all patterns except BLACK; blackout covers
  solid black). Action failures surface in the message label.
- **GLOutputWindow** (`infrastructure/renderer/output_window.py`) —
  the actual output surface: ModernGL viewport, `output_escape_requested`
  signal, `set_pattern` / `set_blackout` / `set_freeze`, solid black
  fallback when GL is not ready.
- **MainWindow** — creates the window in `_setup_ui`, attaches it to
  the VM, hooks `output_escape_requested` → `exit_output()`, and closes
  the window in `closeEvent` so no stray fullscreen window survives app
  exit.

## Session Flow

1. **Select as Live** (or **Select as Preview**) on a projector:
   the VM validates the display exists, then begins a session if none
   exists and routes the output (`switch_live_output` / preview target).
2. **Test Pattern** / **Fullscreen**: the VM checks the display is
   fullscreen-capable and no _other_ display is live, then moves the
   output window onto the display (`move_window_to(..., fullscreen=True)`)
   and renders the pattern through the GL pipeline.
3. **Blackout** cuts the session live output and blacks the window.
4. **Freeze** (toggle) holds the last rendered frame; unfreeze restores
   the pre-freeze state: the last pattern when the session was live,
   black when it was frozen while blacked out (or no pattern was set).
5. **Exit Output** ends the session, restores the window to normal and
   hides it. ESC on the output window does the same.

## Safety Gates (all in the view model, before touching hardware)

| Gate                            | Raises                         |
| ------------------------------- | ------------------------------ |
| Display not connected           | `DisplayNotFoundError`         |
| Display lacks fullscreen        | `OutputSessionError`           |
| No output window attached       | `OutputSessionError`           |
| Live session on another display | `OutputSessionError`           |
| Switch rejected by validation   | `OutputSwitchError` (+ report) |

The primary monitor is treated like any other display: it only becomes
fullscreen when the user selects it. MainWindow itself is never made
fullscreen.

## Event-Driven Refresh

The VM subscribes to `DisplayConnected`, `DisplayDisconnected`,
`DisplayLiveOutputChanged`, `DisplayPreviewOutputChanged`,
`OutputSessionEnded`, `OutputLiveStarted`, `OutputBlackout`,
`OutputFrozen`, `OutputUnfrozen`, and bumps `revision` so the panel
re-renders. A disconnect of the live/preview display sets a warning
message. The panel also re-renders on the main window's poll timer and
after every action.

## Testing

- View-model actions + gates: `tests/unit/ui/viewmodels/test_displays_viewmodel.py`
  (fake hardware manager + fake `OutputSurface`; handlers invoked directly
  because the test event bus records subscriptions without dispatching).
- Panel buttons/state: `tests/unit/ui/panels/test_displays_panel.py`
  (offscreen Qt; `run_async` runs coroutines synchronously outside a loop).
- Preview combo regression: `tests/unit/ui/panels/test_displays_panel_preview.py`.

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run pytest -q --no-cov tests/unit/ui/viewmodels/test_displays_viewmodel.py tests/unit/ui/panels/test_displays_panel.py tests/unit/ui/panels/test_displays_panel_preview.py
```

## Manual Verification

1. `uv run projectionai`
2. Displays panel → **Refresh**: all displays appear with mode/kind/
   connection info and supported modes in the tooltip.
3. Select a projector → **Test Pattern**: the output window appears
   fullscreen on that display showing the selected pattern.
4. **Freeze**: the frame holds; **Freeze** again resumes the pattern.
5. **Blackout**: output cuts to black; **Exit Output** hides the window.
6. **Select as Live** on a monitor: the monitor goes fullscreen only
   because it was explicitly chosen.
7. Press **ESC** on the output window: the session ends and the window
   hides.
8. During a session, unplug the live display: a warning appears in the
   VALIDATION section.

Steps 3–7 run with mock displays (no physical hardware); step 8 needs
real hardware and is not covered in CI.

## Known Limitations

- `display.capabilities.supports_fullscreen` gates fullscreen moves; a
  provider that cannot report it will reject the action.
- Freeze/unfreeze restores the last test pattern (or black, if the
  session was frozen while blacked out); camera/AI content routing to
  the output window is a future phase.
- Multi-projector simultaneous output is out of scope (one live
  display per session; switching requires exiting or switching live).
