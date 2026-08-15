# Packaging ProjectionAI for Windows

ProjectionAI ships as a **portable zip** containing a PyInstaller
bundle, with an optional Inno Setup installer for machines that have
ISCC available. No binary assets live in the repository — the icon is
generated programmatically at build time.

## Requirements

- A working dev environment (see [BUILD.md](BUILD.md))
- The dev extra installed: `uv sync --extra dev`
  (provides `pyinstaller` and `Pillow`)

## Build the Distributable

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_package.ps1
```

This script:

1. Generates `build/icon.ico` programmatically from
   `packaging/make_icon.py` (Pillow; no binary assets committed)
2. Runs PyInstaller against `packaging/projectionai.spec`
3. Produces `dist/ProjectionAI/ProjectionAI.exe` (onedir, windowed)
4. Zips the bundle to `dist/ProjectionAI-<version>-win64.zip`

## Manual PyInstaller Invocation

```powershell
uv run python packaging/make_icon.py
uv run pyinstaller --noconfirm --clean packaging/projectionai.spec
```

## What the Spec Includes

- `packaging/launcher.py` — entry script; hands off to
  `projectionai.main:main` so the exe behaves like `python -m projectionai`
- `collect_all("PySide6")` — Qt binaries, plugins, and translations
- Shader sources from `projectionai/infrastructure/renderer/shaders/`
- Windowed bootloader (`console=False`) with the generated icon

## Installer (Optional)

The portable zip is the primary artifact. If you have Inno Setup 6
installed, you can additionally build an installer:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer/ProjectionAI.iss
```

Output: `dist/ProjectionAI-<version>-setup.exe`.

## Verification

After building, follow the smoke test procedure in
[SMOKE-TEST.md](SMOKE-TEST.md) before distributing. Known gaps and
limitations of the packaged build are documented in
[KNOWN-LIMITATIONS.md](KNOWN-LIMITATIONS.md).
