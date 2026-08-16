# Smoke Test Procedure

Quick verification that a build actually works. Run this against the
source checkout **and** against the packaged bundle.

## 1. Version Flag

```powershell
# Source — capture the actual version string
uv run projectionai --version
# Expected: prints "ProjectionAI v<version>", exit code 0

# Packaged — must match the source value exactly
dist\ProjectionAI\ProjectionAI.exe --version
# Expected: same version string as the source run above, exit code 0
```

## 2. GUI Startup (Packaged Bundle)

```powershell
$p = Start-Process -FilePath "dist\ProjectionAI\ProjectionAI.exe" -PassThru
Start-Sleep -Seconds 8
if ($p.HasExited) { "CRASHED early, exit=$($p.ExitCode)" } else { "ALIVE"; Stop-Process -Id $p.Id -Force }
```

Expected: `ALIVE` — the main window opens without an exception dialog.

## 3. Manual GUI Checks (Human)

1. Main window opens with the 3D viewport and docked panels
   (scene, asset, devices).
2. The console panel mirrors application log records
   (watch it while doing step 4).
3. Open **Calibration Panel** → press **Run Camera Calibration**:
   a scan progress indicator appears and completes without an
   unhandled exception dialog.
4. The scene viewport renders the calibration overlay (board
   corners) after calibration completes.
5. Closing the window exits cleanly (no frozen process in Task
   Manager).
6. **Cameras panel → live preview**: select a camera and press
   **Preview**; a live image appears in the preview area with a
   `LIVE · <id> · WxH · fps · N frames · M dropped` info line, and the
   camera's list entry shows **LIVE**. Press **Stop** to reset the
   preview to "No preview". (See `CAMERA-LIVE-PREVIEW.md`.)

## 4. Headless Test Suite

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run pytest -q
```

Expected: all tests pass with coverage >= 60%.

## 5. Packaged Zip

Unzip `dist/ProjectionAI-<version>-win64.zip` to a fresh folder and
repeat steps 1–2 from the unzipped location (proves the zip is
self-contained).
