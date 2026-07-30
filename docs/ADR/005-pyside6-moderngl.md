# ADR-005: PySide6 + ModernGL for Viewport Rendering

## Status

Accepted

## Context

The application requires a real-time 3D viewport for previewing projection mappings. The viewport must support orbit/pan/zoom camera controls, render scene geometry, grids, overlays, selection highlights, and debug visualisations. Two approaches were considered: a pure Qt approach with QPainter, or embedding OpenGL via Qt's widget system.

## Decision

Use PySide6's `QOpenGLWidget` as the viewport host, with ModernGL providing the OpenGL API.

- `QOpenGLWidget` handles context creation, resize, and paint lifecycle.
- ModernGL provides a Pythonic wrapper around modern OpenGL (3.3+ core profile).
- Render pipeline is organised into ordered passes: scene, grid, overlay, selection, debug, background.
- Camera system uses ModernGL's OrbitCamera/PerspectiveCamera primitives.

## Consequences

- **Positive**: Qt-native viewport with full integration into the PySide6 widget tree.
- **Positive**: ModernGL abstracts away tedious GL boilerplate (VAO, VBO, shader compilation).
- **Positive**: Ordered pass system makes rendering modular and easy to extend.
- **Negative**: ModernGL has a smaller ecosystem than raw PyOpenGL.
- **Negative**: OpenGL core profile limits compatibility with older hardware.
- **Negative**: QOpenGLWidget threading model requires care with async operations.
