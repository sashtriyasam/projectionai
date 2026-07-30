"""Axis renderer — draws world orientation axes in the viewport."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray


class AxisRenderer:
    """Renders world-space orientation axes (X, Y, Z) in the viewport.

    Axes are drawn as coloured lines from the origin extending to a
    configurable length. The colours follow the standard convention:
    X = red, Y = green, Z = blue.
    """

    AXIS_COLORS: ClassVar[dict[str, tuple[float, float, float]]] = {
        "x": (1.0, 0.2, 0.2),  # red
        "y": (0.2, 1.0, 0.2),  # green
        "z": (0.2, 0.4, 1.0),  # blue
    }

    def __init__(self) -> None:
        self._enabled: bool = True
        self._size: float = 1.0
        self._origin: NDArray[np.float32] = np.zeros(3, dtype=np.float32)

        # Pre-built axis lines
        self._vertices: NDArray[np.float32] | None = None
        self._colors: NDArray[np.float32] | None = None

    # -- Properties ---------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def size(self) -> float:
        return self._size

    @size.setter
    def size(self, value: float) -> None:
        if value != self._size:
            self._size = max(value, 0.01)
            self._rebuild()

    @property
    def origin(self) -> NDArray[np.float32]:
        return self._origin.copy()

    @origin.setter
    def origin(self, value: tuple[float, float, float] | NDArray[np.float32]) -> None:
        self._origin = np.asarray(value, dtype=np.float32)
        self._rebuild()

    @property
    def vertices(self) -> NDArray[np.float32]:
        """(6, 3) line-segment vertices for X, Y, Z axes."""
        if self._vertices is None:
            self._rebuild()
        return self._vertices  # type: ignore[return-value]

    @property
    def colors(self) -> NDArray[np.float32]:
        """(6, 3) RGB colours per vertex."""
        if self._colors is None:
            self._rebuild()
        return self._colors  # type: ignore[return-value]

    # -- Internal -----------------------------------------------------------

    def _rebuild(self) -> None:
        """Build axis line vertices."""
        s = self._size
        o = self._origin
        # Each axis: two vertices (origin, tip)
        self._vertices = np.array(
            [
                [o[0], o[1], o[2]],
                [o[0] + s, o[1], o[2]],  # X
                [o[0], o[1], o[2]],
                [o[0], o[1] + s, o[2]],  # Y
                [o[0], o[1], o[2]],
                [o[0], o[1], o[2] + s],  # Z
            ],
            dtype=np.float32,
        )
        self._colors = np.array(
            [
                self.AXIS_COLORS["x"],
                self.AXIS_COLORS["x"],
                self.AXIS_COLORS["y"],
                self.AXIS_COLORS["y"],
                self.AXIS_COLORS["z"],
                self.AXIS_COLORS["z"],
            ],
            dtype=np.float32,
        )
