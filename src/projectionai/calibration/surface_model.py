"""Surface model — physical projection surface properties.

Surfaces are the target for projection mapping. A surface can be planar
or non-planar (cylindrical, spherical, dome, irregular). The model stores
the surface geometry, pose, and physical dimensions.

Multi-surface support enables mapping across complex architectural
features: corners, pillars, curved walls, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from projectionai.calibration.types import Mat4x4, ProjectionType, Vec3


@dataclass
class SurfacePose:
    """Geometric description and pose of a projection surface.

    The surface is defined in local coordinates relative to its origin.
    The transform places the surface in world space.
    """

    surface_type: ProjectionType = ProjectionType.FLAT

    # Physical dimensions in world units (metres)
    width: float = 2.0
    height: float = 1.5
    depth: float = 0.0  # non-zero for curved/irregular surfaces

    # Parameters for non-planar surfaces
    curvature_radius: float = 0.0  # 0 = flat, >0 for cylindrical/spherical
    curvature_axis: str = "y"  # x, y, z — axis of curvature for cylindrical

    # Transform from surface-local to world space
    transform: Mat4x4 = field(default_factory=Mat4x4.identity)

    # UV mapping bounds (normalized 0-1, for sub-region mapping)
    uv_min: tuple[float, float] = (0.0, 0.0)
    uv_max: tuple[float, float] = (1.0, 1.0)

    enabled: bool = True
    label: str = ""

    # Optional mesh approximation for non-planar surfaces
    mesh_vertices: list[Vec3] = field(default_factory=list)
    mesh_indices: list[int] = field(default_factory=list)

    @property
    def area(self) -> float:
        """Approximate surface area in world units squared."""
        if self.surface_type == ProjectionType.FLAT:
            return self.width * self.height
        if self.surface_type == ProjectionType.CYLINDRICAL:
            import math

            r = (
                self.curvature_radius
                if self.curvature_radius > 0
                else self.width / math.pi
            )
            return 2.0 * math.pi * r * self.height
        return self.width * self.height  # rough planar approximation

    @property
    def is_planar(self) -> bool:
        """Return ``True`` if the surface is flat."""
        return self.surface_type == ProjectionType.FLAT or (
            self.curvature_radius == 0.0
        )


@dataclass
class SurfaceModel:
    """Complete projection surface description.

    Holds multiple ``SurfacePose`` instances for multi-surface setups.
    Each surface is keyed by a unique ID.
    """

    name: str = "Surface"
    material: str = "white"  # white, grey, black, custom
    reflectance: float = 0.8  # 0.0 - 1.0
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)  # RGB surface colour

    # Multi-surface support
    surfaces: dict[str, SurfacePose] = field(default_factory=dict)

    def add_surface(self, surface_id: str, pose: SurfacePose) -> None:
        """Add a projection surface."""
        self.surfaces[surface_id] = pose

    def remove_surface(self, surface_id: str) -> None:
        """Remove a projection surface."""
        self.surfaces.pop(surface_id, None)

    def get_surface(self, surface_id: str) -> SurfacePose | None:
        """Get a specific surface by ID."""
        return self.surfaces.get(surface_id)

    @property
    def surface_count(self) -> int:
        """Number of configured surfaces."""
        return len(self.surfaces)

    @property
    def all_enabled(self) -> list[SurfacePose]:
        """Return all enabled surfaces."""
        return [s for s in self.surfaces.values() if s.enabled]
