# Known Limitations

This page tracks known gaps and limitations of the current
**Developer Preview (v0.1.0.dev0)** build. It is intentionally
honest: anything listed here is not yet implemented, is partially
implemented, or is knowingly constrained.

## Product Scope

- **Projection mapping is not implemented.** The platform currently
  provides the desktop shell, viewport, calibration preview, and
  panels — the actual scan-to-warp-to-project pipeline is future work.
- **AI content generation is not implemented.** AI provider
  infrastructure exists (plugin architecture, config plumbing), but no
  generation feature is wired into the UI yet.
- **Timeline playback is not implemented.**
- **Automatic warping is not implemented.**

## Calibration

- Camera calibration requires a physical camera with an OpenCV-
  compatible driver; the mock provider is used when no camera is
  configured, and real capture is validated on hardware separately
  (see `docs/HARDWARE-VALIDATION.md`).
- The calibration pipeline ships without per-camera tuning profiles;
  lens/pose estimates assume a conventional pinhole model.

## Display Output

- Live output sessions are gated by validation and are exercised in CI
  with deterministic mock providers only (`docs/OUTPUT.md`).
- Multi-monitor topology changes are detected but automatic display
  reconfiguration is not performed.

## Packaging (Windows Bundle)

- The PyInstaller bundle is **onedir** (folder with exe + DLLs), not a
  single-file exe; distribute the whole `dist/ProjectionAI/` folder or
  the zip.
- Bundle size is large (~300 MB zip) because it carries PySide6, Qt
  plugins, OpenCV, and the 3D/vision stack — including unused Qt SQL
  drivers that PyInstaller collects by default.
- The exe is unsigned; SmartScreen may warn on first launch.
- Inno Setup installer is optional; the portable zip is the primary
  artifact.
- The icon is generated programmatically at build time and is a simple
  placeholder mark — not final branding.

## Development

- Coverage gate is 60%; several infrastructure modules (AI providers,
  display backends) are exercised through mocks and are below the
  desired coverage.
- UI tests run headless (`QT_QPA_PLATFORM=offscreen`); pixel-level
  rendering is not asserted.
- Windows is the primary packaging target; macOS/Linux run from source
  but are not packaged.
