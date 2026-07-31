"""Calibration overlay — visualises calibration board detections in the viewport.

The :class:`CalibrationOverlay` is a CPU-side overlay component in the same
style as :class:`GridRenderer` and :class:`AxisRenderer`: it holds data and
produces line-segment vertices for the GPU overlay pass, but never touches
OpenGL itself.

It displays the most recent calibration board detection (the detected corner
grid) and the calibration progress/status. Corner coordinates are consumed in
camera pixel space ``(N, 2)`` together with the source image size; the overlay
pass converts them to screen space using the viewport size, so the corner
grid is drawn exactly where the board appeared in the captured frame.

The overlay holds no vision logic and imports nothing from the calibration
framework — it is a pure view-layer component that receives already-detected
data (see ``ViewportController.set_calibration_detection``).
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

# Colour used for the detected corner grid lines (RGBA, 0..1).
_CORNER_COLOR: NDArray[np.float32] = np.array(
    [0.2, 1.0, 0.4, 1.0],
    dtype=np.float32,  # bright green
)


class CalibrationOverlay:
    """Holds the latest board detection and calibration status.

    Vertex generation follows the ``GridRenderer`` convention: line segments
    are emitted as start/end vertex pairs with a colour per vertex, ready to
    be uploaded as a ModernGL ``LINES`` VAO.

    When no detection is available (or the overlay is disabled) the vertex
    arrays are empty ``(0, 2)`` / ``(0, 4)`` so passes can draw nothing.
    """

    CORNER_COLOR: ClassVar[tuple[float, float, float, float]] = tuple(
        _CORNER_COLOR.tolist()
    )

    def __init__(self) -> None:
        self._enabled: bool = True

        # Latest detection (camera pixel space)
        self._corners: NDArray[np.float32] | None = None
        self._image_size: tuple[int, int] = (0, 0)

        # Calibration status
        self._progress: float = 0.0
        self._status_text: str = ""

        # Pre-computed line geometry
        self._dirty: bool = False
        self._vertices: NDArray[np.float32] = np.zeros((0, 2), dtype=np.float32)
        self._colors: NDArray[np.float32] = np.zeros((0, 4), dtype=np.float32)

        # Bumped whenever geometry-affecting data changes (used by the
        # viewport widget to avoid re-uploading unchanged vertices).
        self._revision: int = 0

    # -- Properties ---------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        if value != self._enabled:
            self._enabled = value
            self._revision += 1

    @property
    def revision(self) -> int:
        """Monotonic counter bumped when the displayed geometry changes.

        Consumers (e.g. the viewport widget's overlay-pass sync) can use
        this to skip re-uploading vertices that have not changed.
        """
        return self._revision

    @property
    def has_detection(self) -> bool:
        """``True`` when a board detection is currently displayed."""
        return self._corners is not None

    @property
    def corners(self) -> NDArray[np.float32] | None:
        """Latest detected corner positions ``(N, 2)`` in pixel space."""
        if self._corners is None:
            return None
        return self._corners.copy()

    @property
    def image_size(self) -> tuple[int, int]:
        """``(width, height)`` of the frame the corners were detected in."""
        return self._image_size

    @property
    def corner_count(self) -> int:
        """Number of corners in the latest detection (``0`` if none)."""
        return 0 if self._corners is None else int(self._corners.shape[0])

    @property
    def progress(self) -> float:
        """Calibration progress in the range ``0.0`` — ``1.0``."""
        return self._progress

    @property
    def status_text(self) -> str:
        """Human-readable calibration status message."""
        return self._status_text

    @property
    def vertices(self) -> NDArray[np.float32]:
        """(M, 2) line-segment vertices in camera pixel space.

        Corners are connected in detection order (row-major as produced by
        ``findChessboardCornersSB``), forming a snake polyline through the
        board; consecutive pairs of vertices form one line segment.
        Empty ``(0, 2)`` when no detection is set, the overlay is disabled,
        or fewer than two corners are available.
        """
        if self._dirty:
            self._rebuild()
        if not self._enabled:
            return np.zeros((0, 2), dtype=np.float32)
        return self._vertices

    @property
    def colors(self) -> NDArray[np.float32]:
        """(M, 4) RGBA colour per vertex (one colour for the whole grid)."""
        if self._dirty:
            self._rebuild()
        if not self._enabled:
            return np.zeros((0, 4), dtype=np.float32)
        return self._colors

    @property
    def line_count(self) -> int:
        """Number of line segments in the corner grid."""
        return int(self.vertices.shape[0] // 2)

    # -- Data updates -------------------------------------------------------

    def set_detection(
        self,
        corners: NDArray[np.float32] | None,
        image_size: tuple[int, int],
    ) -> None:
        """Set the latest board detection.

        Args:
            corners: Corner positions ``(N, 2)`` in pixel space, or ``None``
                to clear the detection.
            image_size: ``(width, height)`` of the source frame.
        """
        if corners is None:
            self.clear()
            return
        corners = np.asarray(corners, dtype=np.float32)
        if corners.ndim != 2 or corners.shape[1] != 2:
            raise ValueError(f"corners must have shape (N, 2), got {corners.shape}")
        self._corners = corners.copy()
        self._image_size = (int(image_size[0]), int(image_size[1]))
        self._dirty = True
        self._revision += 1

    def set_status(self, progress: float, status_text: str) -> None:
        """Update the calibration progress and status message.

        Args:
            progress: Value from ``0.0`` to ``1.0`` (clamped).
            status_text: Human-readable status message.
        """
        self._progress = max(0.0, min(1.0, float(progress)))
        self._status_text = status_text

    def clear(self) -> None:
        """Clear the detection (keeps the overlay enabled and status)."""
        self._corners = None
        self._image_size = (0, 0)
        self._vertices = np.zeros((0, 2), dtype=np.float32)
        self._colors = np.zeros((0, 4), dtype=np.float32)
        self._dirty = False
        self._revision += 1

    # -- Internal -----------------------------------------------------------

    def _rebuild(self) -> None:
        """Build the corner polyline line segments.

        Corners are connected consecutively in detection order (row-major,
        as produced by ``findChessboardCornersSB``), producing a snake
        polyline that traces the detected board. With fewer than two corners
        no segments are emitted.
        """
        self._vertices = np.zeros((0, 2), dtype=np.float32)
        self._colors = np.zeros((0, 4), dtype=np.float32)
        if self._corners is None:
            self._dirty = False
            return

        corners = self._corners
        n = corners.shape[0]
        if n < 2:
            self._dirty = False
            return

        segments: list[NDArray[np.float32]] = []
        # Row-wise connections (consecutive corners, row-major order)
        for i in range(n - 1):
            segments.append(
                np.stack([corners[i], corners[i + 1]], axis=0).astype(np.float32)
            )

        self._vertices = np.concatenate(segments, axis=0)
        self._colors = np.tile(_CORNER_COLOR, (self._vertices.shape[0], 1))
        self._dirty = False
