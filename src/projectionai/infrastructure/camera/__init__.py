"""Camera capture backends.

Importing this package must not load OpenCV: the mock provider is the
only dependency-free backend imported eagerly, and the OpenCV classes
are exposed lazily via module ``__getattr__`` for code that references
them at package level.
"""

from __future__ import annotations

from projectionai.infrastructure.camera.mock_camera import (
    MockCamera,
    MockCameraProvider,
)

__all__ = ["MockCamera", "MockCameraProvider"]

_LAZY_EXPORTS = frozenset({"OpenCVCamera", "OpenCVCameraProvider"})


def __getattr__(name: str) -> object:
    """Expose the OpenCV camera implementation on demand."""
    if name in _LAZY_EXPORTS:
        from projectionai.infrastructure.camera import opencv_camera

        return getattr(opencv_camera, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
