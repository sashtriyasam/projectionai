"""Grid renderer — draws a ground-plane grid in the viewport."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


class GridRenderer:
    """Renders a ground-plane grid in world space.

    The grid is always drawn on the XZ plane (Y=0) using a configurable
    size and subdivision count. The grid appearance can be customised
    via ``editor_preferences``.
    """

    def __init__(self) -> None:
        self._enabled: bool = True
        self._size: int = 20  # world units (half-extent)
        self._subdivisions: int = 10
        self._color: tuple[float, float, float] = (0.3, 0.3, 0.3)
        self._center_color: tuple[float, float, float] = (0.5, 0.5, 0.5)
        self._opacity: float = 0.6

        # Pre-computed vertices for the grid (CPU side — GPU rendering in
        # GridPass handles the actual draw call).
        self._dirty: bool = True
        self._vertices: NDArray[np.float32] = np.zeros((0, 3), dtype=np.float32)
        self._colors: NDArray[np.float32] = np.zeros((0, 3), dtype=np.float32)

    # -- Properties ---------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def size(self) -> int:
        return self._size

    @size.setter
    def size(self, value: int) -> None:
        if value != self._size:
            self._size = max(value, 1)
            self._dirty = True

    @property
    def subdivisions(self) -> int:
        return self._subdivisions

    @subdivisions.setter
    def subdivisions(self, value: int) -> None:
        if value != self._subdivisions:
            self._subdivisions = max(value, 1)
            self._dirty = True

    @property
    def color(self) -> tuple[float, float, float]:
        return self._color

    @color.setter
    def color(self, value: tuple[float, float, float]) -> None:
        if value != self._color:
            self._color = value
            self._dirty = True

    @property
    def opacity(self) -> float:
        return self._opacity

    @opacity.setter
    def opacity(self, value: float) -> None:
        self._opacity = max(0.0, min(value, 1.0))

    @property
    def vertices(self) -> NDArray[np.float32]:
        """(N, 3) line-segment vertices for the grid.

        Returns alternating start/end points for each grid line segment.
        """
        if self._dirty:
            self._rebuild()
        return self._vertices

    @property
    def vertex_colors(self) -> NDArray[np.float32]:
        """(N, 3) RGB colors per vertex."""
        if self._dirty:
            self._rebuild()
        return self._colors

    @property
    def line_count(self) -> int:
        """Number of line segments in the grid."""
        return int(self.vertices.shape[0] // 2)

    def rebuild(self) -> None:
        """Force grid vertex rebuild. Call after changing size or subdivisions."""
        self._dirty = True

    # -- Internal -----------------------------------------------------------

    def _rebuild(self) -> None:
        """Generate grid line vertices as line-segment pairs."""
        half = self._size
        step = (2.0 * half) / self._subdivisions
        lines: list[NDArray[np.float32]] = []
        cols: list[NDArray[np.float32]] = []

        center_col = np.array(self._center_color, dtype=np.float32)
        reg_col = np.array(self._color, dtype=np.float32)

        # Lines along X (Z varies)
        for i in range(self._subdivisions + 1):
            z = -half + i * step
            lines.append(np.array([[-half, 0.0, z], [half, 0.0, z]], dtype=np.float32))
            cols.append(center_col if abs(z) < 1e-6 else reg_col)

        # Lines along Z (X varies)
        for i in range(self._subdivisions + 1):
            x = -half + i * step
            lines.append(np.array([[x, 0.0, -half], [x, 0.0, half]], dtype=np.float32))
            cols.append(center_col if abs(x) < 1e-6 else reg_col)

        self._vertices = (
            np.concatenate(lines, axis=0)
            if lines
            else np.zeros((0, 3), dtype=np.float32)
        )
        # Repeat each color for both vertices of the line segment
        repeated_cols = [np.tile(c, (2, 1)) for c in cols]
        self._colors = (
            np.concatenate(repeated_cols, axis=0)
            if repeated_cols
            else np.zeros((0, 3), dtype=np.float32)
        )
        self._dirty = False
