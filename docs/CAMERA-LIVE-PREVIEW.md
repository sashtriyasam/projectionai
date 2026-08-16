# Camera Live Preview

The Cameras panel (left dock) shows a live video feed from the selected
camera at ~30 fps while keeping the UI thread responsive. Frames are
delivered on the main thread through the existing camera abstraction —
no second capture path is introduced.

## Data Flow

1. The user selects a camera and presses **Preview**.
2. `CameraPanel._start_preview` starts a 33 ms `QTimer` and schedules
   `DevicesViewModel.start_preview(camera_id)` through `run_async`.
3. The view model registers a frame handler
   (`CameraManager.subscribe_frames`) and starts the continuous capture
   loop (`CameraManager.start_capture`).
4. Every captured frame is delivered synchronously on the main thread to
   the view model's handler, which keeps only the newest frame
   (`latest_frame()`).
5. The panel's timer polls `latest_frame()` and paints it: `QImage`
   wraps the numpy buffer without copying, `QPixmap.fromImage` copies
   once, and the pixmap is scaled keeping the aspect ratio.
6. After painting, the panel calls `mark_frame_rendered(frame_number)`
   so the view model can count frames the renderer skipped.

```
Camera capture loop ──► CameraManager._deliver_frame
        (main thread)         │
                              ▼
              DevicesViewModel._on_frame   (keeps newest frame,
                                            counts dropped)
                              │ latest_frame()
                              ▼
              CameraPanel._render_preview_frame  (33 ms QTimer,
                                                  skips duplicates)
                              │ mark_frame_rendered()
                              ▼
                        QLabel.setPixmap
```

## Components

- **CameraManager** — frame-subscriber registry
  (`subscribe_frames` / `unsubscribe_frames` / `frame_subscriber_count`).
  `_deliver_frame` runs handlers synchronously inside the capture loop
  and isolates handler failures (a failing handler is logged, the loop
  keeps running).
- **DevicesViewModel** — Qt-free preview state machine:
  `start_preview` / `stop_preview`, `preview_camera_id`, `latest_frame`,
  `mark_frame_rendered`, `frame_count` / `dropped_count`, and
  `preview_error`. Subscribes to `CameraDisconnected` and `CameraClosed`
  so a hardware event tears the preview down automatically.
- **CameraPanel** — preview label (180 px minimum height, well
  background), an info line (`LIVE · <id> · WxH · fps · N frames ·
M dropped`), Preview/Stop/Open/Close actions, a **LIVE** marker on the
  active camera's list entry, and preview errors shown in the status
  line (LIVE red, taking priority over the camera count).

## Drop Counting

The panel renders only frames newer than the last one it painted
(duplicate frames are skipped). On every incoming frame, the view model
increments `dropped_count` if the previous newest frame was never
rendered (its `frame_number` differs from the rendered one). `_on_frame`
never notifies observers — a 30 fps refresh storm would re-render the
whole panel on every frame.

## Error Mapping

| Camera error              | Preview message                             |
| ------------------------- | ------------------------------------------- |
| `CameraNotFoundError`     | Camera not found                            |
| `CameraOpenError`         | Could not open camera                       |
| `CameraUnavailableError`  | Camera unavailable (in use or disconnected) |
| `CameraDisconnectedError` | Camera disconnected                         |
| `CameraCaptureError`      | Frame capture failed                        |
| other                     | `str(exc)` or "Camera error"                |

A failed `start_preview` leaves the view model idle and reports the
reason through `preview_error()`. A disconnect event sets
"Camera disconnected", tears the preview down, and keeps the message
visible; a close event clears the message during teardown.

## Concurrency Model

Capture, frame delivery, and painting all run on the asyncio/Qt main
thread, so no locks are needed. Instead of a blocking `qapp.exec()`,
`_run_qt()` drives the Qt event loop cooperatively with AnyIO:
`_drive_qt_loop()` alternates `qapp.processEvents()` with
`await anyio.sleep(0.02)`, so Qt callbacks (UI signals, frame delivery)
and asyncio tasks (view-model coroutines) both advance on the same
thread. `run_async` schedules view-model coroutines fire-and-forget
with a keep-alive set; panel actions stay non-blocking.

## Testing

- Subscriber registry: `tests/unit/test_camera_manager.py`
- View-model preview (real `EventBus`): `tests/unit/ui/viewmodels/test_devices_viewmodel.py`
- Panel rendering (offscreen): `tests/unit/ui/panels/test_camera_panel.py`

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run pytest -q --no-cov tests/unit/test_camera_manager.py tests/unit/ui/viewmodels/test_devices_viewmodel.py tests/unit/ui/panels/test_camera_panel.py
```

## Manual Verification

1. `uv run projectionai`
2. Cameras panel → **Refresh**.
3. Select a camera → **Preview**: a live image appears in the preview
   area; the info line reads `LIVE · <id> · 640x480 · 30 fps · …` and
   the camera's list entry shows **LIVE**.
4. **Stop**: the preview area resets to "No preview".
5. During preview, unplug the camera (physical hardware): the status
   line shows "Camera disconnected" and the preview stops.

Mock cameras (`mock-0`, `mock-1`) deliver synthetic frames, so steps 3–4
run without hardware; step 5 requires a real camera and is not covered
in CI.
