"""Projection surface representations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from projectionai.domain.geometry import Mesh, Vec3


class SurfaceType(Enum):
    """Categorisation of detected projection surfaces."""

    PLANAR = auto()
    CYLINDRICAL = auto()
    SPHERICAL = auto()
    CORNER = auto()
    IRREGULAR = auto()
    UNKNOWN = auto()


def _array_eq(a: np.ndarray | None, b: np.ndarray | None) -> bool:
    """Compare two optional NumPy arrays with ``np.array_equal``."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return bool(np.array_equal(a, b))


@dataclass(frozen=True, eq=False)
class ProjectionSurface:
    """A detected surface suitable for projection mapping."""

    id: str
    surface_type: SurfaceType = SurfaceType.UNKNOWN

    # Geometry (in world coordinates)
    mesh: Mesh | None = None
    bounding_box: tuple[Vec3, Vec3] | None = None

    # Surface normal and center
    normal: Vec3 | None = None
    center: Vec3 | None = None

    # Physical dimensions (in meters)
    width_m: float = 0.0
    height_m: float = 0.0
    depth_m: float = 0.0

    # Visibility / confidence
    confidence: float = 1.0
    fully_visible: bool = True

    # Projector-to-surface homography (if planar)
    homography: NDArray[np.float64] | None = None  # 3x3 matrix

    metadata: dict[str, object] = field(default_factory=dict)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProjectionSurface):
            return NotImplemented
        return (
            self.id == other.id
            and self.surface_type == other.surface_type
            and self.mesh == other.mesh
            and self.bounding_box == other.bounding_box
            and self.normal == other.normal
            and self.center == other.center
            and self.width_m == other.width_m
            and self.height_m == other.height_m
            and self.depth_m == other.depth_m
            and self.confidence == other.confidence
            and self.fully_visible == other.fully_visible
            and _array_eq(self.homography, other.homography)
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


@dataclass(frozen=True)
class SurfaceDetectionResult:
    """Result of a surface detection pass."""

    surfaces: tuple[ProjectionSurface, ...] = ()
    dominant_surface: ProjectionSurface | None = None
    coverage: float = 0.0  # What fraction of the scene is covered by surfaces
