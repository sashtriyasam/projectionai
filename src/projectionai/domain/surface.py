"""Unified surface domain model for projection mapping.

This module provides the canonical surface representation used across:
- Vision/detection (detected surfaces)
- Calibration (configured surfaces)
- Scene graph (SurfaceComponent)
- Projection mapping (ProjectionMapping → surface reference)

The model distinguishes between:
- DetectedSurface: Output from computer vision, may be incomplete
- ConfiguredSurface: User-defined or calibrated, complete with transform
- PhysicalSurface: Abstract base for common properties

Coordinate Spaces
=================

All surfaces are defined in SURFACE_LOCAL space (meters, origin at local origin,
X right, Y up, Z out). The transform to WORLD space is stored in
ConfiguredSurface.transform (Mat4x4).

UV Convention
=============

Surface UV: [0,1] x [0,1], origin bottom-left, V up (OpenGL convention).
Projector UV (stored in warp mesh): [0,1] x [0,1], origin top-left, V down.

See coordinates.py for full convention documentation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

import numpy as np
from numpy.typing import NDArray

from projectionai.calibration.types import Mat4x4, ProjectionType
from projectionai.domain.geometry import BoundingBox, Mesh
from projectionai.domain.geometry import Vec3 as GeoVec3


class SurfaceType(StrEnum):
    """Type of projection surface.

    Matches calibration.types.ProjectionType for configured surfaces.
    Uses StrEnum for stable serialization keys.
    """

    FLAT = "flat"
    CYLINDRICAL = "cylindrical"
    SPHERICAL = "spherical"
    DOME = "dome"
    IRREGULAR = "irregular"
    CORNER = "corner"
    CUSTOM = "custom"
    UNKNOWN = "unknown"

    @classmethod
    def from_projection_type(cls, pt: ProjectionType) -> SurfaceType:
        """Convert from calibration ProjectionType."""
        return cls(pt.value)

    def to_projection_type(self) -> ProjectionType:
        """Convert to calibration ProjectionType."""
        return ProjectionType(self.value)


def _array_eq(a: NDArray[np.float64] | None, b: NDArray[np.float64] | None) -> bool:
    """Compare two optional NumPy arrays with ``np.array_equal``."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return bool(np.array_equal(a, b))


@dataclass(frozen=True, eq=False)
class PhysicalSurface:
    """Base surface properties shared by detected and configured surfaces."""

    id: str
    surface_type: SurfaceType = SurfaceType.UNKNOWN

    # Physical dimensions in meters (surface-local space)
    width_m: float = 0.0
    height_m: float = 0.0
    depth_m: float = 0.0  # Non-zero for curved surfaces

    # Curvature parameters (for non-planar surfaces)
    curvature_radius: float = 0.0  # 0 = flat
    curvature_axis: str = "y"  # x, y, or z

    # Surface material properties
    material: str = "white"  # white, grey, black, custom
    reflectance: float = 0.8  # 0.0 - 1.0
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def __post_init__(self) -> None:
        if not (0.0 <= self.reflectance <= 1.0):
            raise ValueError("reflectance must be in [0, 1]")
        for c in self.color:
            if not (0.0 <= c <= 1.0):
                raise ValueError("color components must be in [0, 1]")

    @property
    def is_planar(self) -> bool:
        return self.surface_type == SurfaceType.FLAT or self.curvature_radius == 0.0

    @property
    def area_m2(self) -> float:
        """Approximate surface area in square meters."""
        if self.is_planar:
            return self.width_m * self.height_m
        if self.surface_type == SurfaceType.CYLINDRICAL:
            r = (
                self.curvature_radius
                if self.curvature_radius > 0
                else self.width_m / math.pi
            )
            theta = self.width_m / r  # arc angle in radians
            return r * theta * self.height_m
        return self.width_m * self.height_m  # rough approximation


@dataclass(frozen=True, eq=False)
class DetectedSurface(PhysicalSurface):
    """A surface detected by computer vision.

    May have incomplete geometry. Used as input to calibration workflow.
    """

    # Detection confidence
    confidence: float = 1.0
    fully_visible: bool = True

    # Geometry (in WORLD coordinates, from detection)
    mesh: Mesh | None = None
    bounding_box: BoundingBox | None = None
    normal: GeoVec3 | None = None
    center: GeoVec3 | None = None

    # Projector-to-surface homography (if planar, in camera frame)
    homography: NDArray[np.float64] | None = None  # 3x3 matrix

    # Source detection metadata
    detection_method: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DetectedSurface):
            return NotImplemented
        return (
            self.id == other.id
            and self.surface_type == other.surface_type
            and abs(self.width_m - other.width_m) < 1e-6
            and abs(self.height_m - other.height_m) < 1e-6
            and abs(self.depth_m - other.depth_m) < 1e-6
            and abs(self.confidence - other.confidence) < 1e-6
            and self.fully_visible == other.fully_visible
            and self.mesh == other.mesh
            and self.bounding_box == other.bounding_box
            and self.normal == other.normal
            and self.center == other.center
            and _array_eq(self.homography, other.homography)
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


@dataclass(frozen=True, eq=False)
class ConfiguredSurface(PhysicalSurface):
    """A surface configured for projection mapping.

    Complete with transform to world space and UV mapping bounds.
    This is the surface referenced by ProjectionMapping.surface_id.
    """

    # Transform from surface-local to WORLD space
    transform: Mat4x4 = field(default_factory=Mat4x4.identity)

    # UV mapping bounds (normalized 0-1, for sub-region mapping)
    uv_min: tuple[float, float] = (0.0, 0.0)
    uv_max: tuple[float, float] = (1.0, 1.0)

    # Optional mesh approximation for non-planar surfaces
    # Stored in SURFACE_LOCAL coordinates
    mesh_vertices: list[GeoVec3] = field(default_factory=list)
    mesh_indices: list[int] = field(default_factory=list)

    # User-facing
    label: str = ""
    enabled: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()
        umin, vmin = self.uv_min
        umax, vmax = self.uv_max
        if not (0.0 <= umin < umax <= 1.0):
            raise ValueError("uv_min.u < uv_max.u required in [0,1]")
        if not (0.0 <= vmin < vmax <= 1.0):
            raise ValueError("uv_min.v < uv_max.v required in [0,1]")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ConfiguredSurface):
            return NotImplemented
        return (
            self.id == other.id
            and self.surface_type == other.surface_type
            and abs(self.width_m - other.width_m) < 1e-6
            and abs(self.height_m - other.height_m) < 1e-6
            and abs(self.depth_m - other.depth_m) < 1e-6
            and self.transform == other.transform
            and self.uv_min == other.uv_min
            and self.uv_max == other.uv_max
            and self.label == other.label
            and self.enabled == other.enabled
            and abs(self.curvature_radius - other.curvature_radius) < 1e-6
            and self.curvature_axis == other.curvature_axis
            and self.mesh_vertices == other.mesh_vertices
            and self.mesh_indices == other.mesh_indices
            and self.material == other.material
            and abs(self.reflectance - other.reflectance) < 1e-6
            and self.color == other.color
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    def get_world_corners(self) -> list[GeoVec3]:
        """Get the four corners of the surface in WORLD space (for planar)."""
        if not self.is_planar:
            raise ValueError("Only planar surfaces have well-defined corners")
        # Surface-local corners (bottom-left, bottom-right, top-right, top-left)
        hw = self.width_m * 0.5
        hh = self.height_m * 0.5
        local_corners = [
            GeoVec3(-hw, -hh, 0.0),
            GeoVec3(hw, -hh, 0.0),
            GeoVec3(hw, hh, 0.0),
            GeoVec3(-hw, hh, 0.0),
        ]
        # Transform to world
        mat = np.array(self.transform.data, dtype=np.float64).reshape(4, 4, order="C")
        world_corners = []
        for c in local_corners:
            v = np.array([c.x, c.y, c.z, 1.0], dtype=np.float64)
            w = mat @ v
            world_corners.append(GeoVec3(w[0], w[1], w[2]))
        return world_corners


@dataclass(frozen=True)
class SurfaceMeshRef:
    """Reference to a surface mesh asset.

    Used by SceneNode SurfaceComponent and ProjectionMapping.warp_mesh_asset_id.
    """

    asset_id: str  # References Asset(Mesh) or Asset(Projection)
    uv_bounds: tuple[tuple[float, float], tuple[float, float]] = (
        (0.0, 0.0),
        (1.0, 1.0),
    )


def create_planar_surface(
    surface_id: str,
    width_m: float,
    height_m: float,
    transform: Mat4x4 | None = None,
    label: str = "",
) -> ConfiguredSurface:
    """Factory for a flat rectangular surface."""
    return ConfiguredSurface(
        id=surface_id,
        surface_type=SurfaceType.FLAT,
        width_m=width_m,
        height_m=height_m,
        transform=transform or Mat4x4.identity(),
        label=label,
    )


def create_cylindrical_surface(
    surface_id: str,
    width_m: float,
    height_m: float,
    curvature_radius: float,
    curvature_axis: str = "y",
    transform: Mat4x4 | None = None,
    label: str = "",
) -> ConfiguredSurface:
    """Factory for a cylindrical surface."""
    return ConfiguredSurface(
        id=surface_id,
        surface_type=SurfaceType.CYLINDRICAL,
        width_m=width_m,
        height_m=height_m,
        curvature_radius=curvature_radius,
        curvature_axis=curvature_axis,
        transform=transform or Mat4x4.identity(),
        label=label,
    )


def create_spherical_surface(
    surface_id: str,
    width_m: float,
    height_m: float,
    curvature_radius: float,
    transform: Mat4x4 | None = None,
    label: str = "",
) -> ConfiguredSurface:
    """Factory for a spherical/dome surface."""
    return ConfiguredSurface(
        id=surface_id,
        surface_type=SurfaceType.SPHERICAL,
        width_m=width_m,
        height_m=height_m,
        curvature_radius=curvature_radius,
        transform=transform or Mat4x4.identity(),
        label=label,
    )


@dataclass(frozen=True)
class SurfaceDetectionResult:
    """Result of a surface detection pass."""

    surfaces: tuple[DetectedSurface, ...] = ()
    dominant_surface: DetectedSurface | None = None
    coverage: float = 0.0  # What fraction of the scene is covered by surfaces
