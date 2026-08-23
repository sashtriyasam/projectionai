"""Canonical transform types for projection mapping.

This module provides explicit, direction-aware transform objects that make
coordinate space conversions unambiguous. Each transform type encodes its
source and target space in the name, preventing the common error of applying
a transform in the wrong direction.

Coordinate Spaces (from coordinates.py):
- SURFACE_LOCAL: Surface local coordinates (meters, origin at surface center, X right, Y up, Z out)
- WORLD: World coordinates (meters, arbitrary origin)
- CAMERA: Camera coordinates (meters, origin at camera optical center, X right, Y down, Z forward)
- PROJECTOR: Projector coordinates (meters, origin at projector optical center, X right, Y down, Z forward)
- PROJECTOR_UV: Normalized projector image [0,1]x[0,1], origin top-left, V down
- PROJECTOR_PIXEL: Projector image pixels, origin top-left

Transform Naming Convention:
    {SourceSpace}To{TargetSpace}Transform
    e.g., SurfaceLocalToWorldTransform = surface_local -> world

All transforms are 4x4 homogeneous matrices (Mat4x4) stored in ROW-MAJOR order.
The Mat4x4 type from calibration.types uses ROW-MAJOR storage (translation at indices 3, 7, 11).
This matches the OpenCV / standard math convention where translation is in the last column.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from projectionai.calibration.types import Mat4x4
from projectionai.domain.geometry import Vec3 as GeoVec3

# =============================================================================
# Base Transform Types
# =============================================================================


@dataclass(frozen=True)
class Transform:
    """Base class for all 4x4 homogeneous transforms.

    The matrix is stored as a Mat4x4 (16 floats, row-major order).
    """

    matrix: Mat4x4 = field(default_factory=Mat4x4.identity)

    def __post_init__(self) -> None:
        # Validate matrix size
        if len(self.matrix.data) != 16:
            raise ValueError("Transform matrix must have 16 elements")

    def to_numpy(self) -> NDArray[np.float64]:
        """Convert to 4x4 numpy array (row-major)."""
        return np.array(self.matrix.data, dtype=np.float64).reshape(4, 4, order="C")

    @classmethod
    def from_numpy(cls, arr: NDArray[np.float64]) -> Transform:
        """Create from 4x4 numpy array (row-major)."""
        if arr.shape != (4, 4):
            raise ValueError(f"Expected 4x4 array, got {arr.shape}")
        return cls(matrix=Mat4x4(data=tuple(arr.ravel(order="C"))))

    def apply_point(self, point: GeoVec3) -> GeoVec3:
        """Apply transform to a 3D point (with homogeneous w=1)."""
        mat = self.to_numpy()
        v = np.array([point.x, point.y, point.z, 1.0], dtype=np.float64)
        result = mat @ v
        if abs(result[3]) < 1e-12:
            raise ValueError("Transform produced point at infinity (w ≈ 0)")
        return GeoVec3(
            result[0] / result[3], result[1] / result[3], result[2] / result[3]
        )

    def apply_vector(self, vector: GeoVec3) -> GeoVec3:
        """Apply transform to a 3D direction vector (with homogeneous w=0)."""
        mat = self.to_numpy()
        v = np.array([vector.x, vector.y, vector.z, 0.0], dtype=np.float64)
        result = mat @ v
        return GeoVec3(result[0], result[1], result[2])

    def inverse(self) -> Transform:
        """Return the inverse transform (always base Transform; direction changes)."""
        mat = self.to_numpy()
        inv = np.linalg.inv(mat)
        return Transform.from_numpy(inv)

    def compose(
        self, other: Transform, target_type: type[Transform] | None = None
    ) -> Transform:
        """Compose this transform with another: other @ self.

        If self: A → B and other: B → C, returns A → C.
        When target_type is provided, uses its from_numpy factory for the result.
        """
        mat = other.to_numpy() @ self.to_numpy()
        factory = (
            target_type.from_numpy if target_type is not None else Transform.from_numpy
        )
        return factory(mat)


# =============================================================================
# Explicit Space Transform Types
# =============================================================================


@dataclass(frozen=True)
class SurfaceLocalToWorldTransform(Transform):
    """Transform from surface-local coordinates to world coordinates.

    Source: SURFACE_LOCAL (meters, surface center, X right, Y up, Z out)
    Target: WORLD (meters, arbitrary origin)
    """

    pass


@dataclass(frozen=True)
class WorldToSurfaceLocalTransform(Transform):
    """Transform from world coordinates to surface-local coordinates.

    Source: WORLD
    Target: SURFACE_LOCAL
    """

    @classmethod
    def from_surface_to_world(
        cls, tw: SurfaceLocalToWorldTransform
    ) -> WorldToSurfaceLocalTransform:
        """Create inverse of a SurfaceLocalToWorldTransform."""
        return cls(matrix=tw.inverse().matrix)


@dataclass(frozen=True)
class WorldToCameraTransform(Transform):
    """Transform from world coordinates to camera coordinates.

    Source: WORLD
    Target: CAMERA (meters, camera optical center, X right, Y down, Z forward)

    This is the INVERSE of CameraExtrinsics.transform (which is camera_local → world).
    """

    @classmethod
    def from_camera_extrinsics(cls, camera_extrinsics: Any) -> WorldToCameraTransform:
        """Create from CameraExtrinsics (which has camera_local → world)."""
        # CameraExtrinsics.transform: camera_local → world
        # We need: world → camera_local = inverse(camera_local → world)
        inv = Transform(matrix=camera_extrinsics.transform).inverse()
        return cls(matrix=inv.matrix)


@dataclass(frozen=True)
class CameraToWorldTransform(Transform):
    """Transform from camera coordinates to world coordinates.

    Source: CAMERA
    Target: WORLD
    """

    @classmethod
    def from_camera_extrinsics(cls, camera_extrinsics: Any) -> CameraToWorldTransform:
        """Create from CameraExtrinsics (which has camera_local → world)."""
        return cls(matrix=camera_extrinsics.transform)


@dataclass(frozen=True)
class WorldToProjectorTransform(Transform):
    """Transform from world coordinates to projector coordinates.

    Source: WORLD
    Target: PROJECTOR (meters, projector optical center, X right, Y down, Z forward)

    This is the INVERSE of ProjectorExtrinsics.transform (which is projector_local → world).
    """

    @classmethod
    def from_projector_extrinsics(
        cls, projector_extrinsics: Any
    ) -> WorldToProjectorTransform:
        """Create from ProjectorExtrinsics (which has projector_local → world)."""
        inv = Transform(matrix=projector_extrinsics.transform).inverse()
        return cls(matrix=inv.matrix)


@dataclass(frozen=True)
class ProjectorToWorldTransform(Transform):
    """Transform from projector coordinates to world coordinates.

    Source: PROJECTOR
    Target: WORLD
    """

    @classmethod
    def from_projector_extrinsics(
        cls, projector_extrinsics: Any
    ) -> ProjectorToWorldTransform:
        """Create from ProjectorExtrinsics (which has projector_local → world)."""
        return cls(matrix=projector_extrinsics.transform)


@dataclass(frozen=True)
class CameraToProjectorTransform(Transform):
    """Transform from camera coordinates to projector coordinates.

    Source: CAMERA
    Target: PROJECTOR

    This is the INVERSE of ProjectorCalibrationResult.projector_pose
    (which is projector_local → camera_frame).
    """

    @classmethod
    def from_projector_pose(cls, projector_pose: Mat4x4) -> CameraToProjectorTransform:
        """Create from projector pose (projector_local → camera_frame)."""
        inv = Transform(matrix=projector_pose).inverse()
        return cls(matrix=inv.matrix)


@dataclass(frozen=True)
class ProjectorToCameraTransform(Transform):
    """Transform from projector coordinates to camera coordinates.

    Source: PROJECTOR
    Target: CAMERA

    This IS ProjectorCalibrationResult.projector_pose
    (projector_local → camera_frame).
    """

    @classmethod
    def from_projector_pose(cls, projector_pose: Mat4x4) -> ProjectorToCameraTransform:
        """Create from projector pose (projector_local → camera_frame)."""
        return cls(matrix=projector_pose)


# =============================================================================
# Projector Projection (3D → 2D)
# =============================================================================


@dataclass(frozen=True)
class ProjectorIntrinsics:
    """Projector intrinsic parameters (pinhole model).

    Matrix K (3x3, row-major for math, but Mat4x4 stores column-major):
        [fx,  0, cx]
        [ 0, fy, cy]
        [ 0,  0,  1]

    Coordinate system: PROJECTOR space → PROJECTOR_PIXEL
    - PROJECTOR: X right, Y down, Z forward (meters)
    - PROJECTOR_PIXEL: u right, v down (pixels, origin top-left)
    """

    fx: float
    fy: float
    cx: float
    cy: float
    resolution_x: int
    resolution_y: int

    # Distortion (not modeled in Phase 5.4; documented for future)
    distortion_model: str = "none"
    distortion_coeffs: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("Focal lengths must be positive")
        if self.resolution_x <= 0 or self.resolution_y <= 0:
            raise ValueError("Resolution must be positive")

    @property
    def resolution(self) -> tuple[int, int]:
        return (self.resolution_x, self.resolution_y)

    def camera_matrix(self) -> NDArray[np.float64]:
        """Return 3x3 camera matrix K (row-major for math operations)."""
        return np.array(
            [[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )

    def project_point(self, point_projector: GeoVec3) -> tuple[float, float]:
        """Project a point in PROJECTOR coordinates to PROJECTOR_PIXEL.

        Args:
            point_projector: (X, Y, Z) in meters, PROJECTOR space

        Returns:
            (u, v) in pixels, PROJECTOR_PIXEL space (origin top-left)
        """
        if point_projector.z <= 0:
            raise ValueError(
                f"Point behind or at projector plane (z={point_projector.z})"
            )

        x, y, z = point_projector.x, point_projector.y, point_projector.z
        u = self.fx * (x / z) + self.cx
        v = self.fy * (y / z) + self.cy
        return (float(u), float(v))

    def project_points(self, points: list[GeoVec3]) -> list[tuple[float, float]]:
        """Project multiple points."""
        return [self.project_point(p) for p in points]

    def pixel_to_uv(self, pixel: tuple[float, float]) -> tuple[float, float]:
        """Convert PROJECTOR_PIXEL to PROJECTOR_UV [0,1]x[0,1]."""
        u, v = pixel
        return (u / self.resolution_x, v / self.resolution_y)

    def uv_to_pixel(self, uv: tuple[float, float]) -> tuple[float, float]:
        """Convert PROJECTOR_UV to PROJECTOR_PIXEL."""
        u, v = uv
        return (u * self.resolution_x, v * self.resolution_y)


# =============================================================================
# Complete Transform Chain
# =============================================================================


@dataclass(frozen=True)
class SurfaceToProjectorChain:
    """Complete transform chain from surface-local to projector pixels.

    Chain: SURFACE_LOCAL → WORLD → CAMERA → PROJECTOR → PROJECTOR_PIXEL

    This is the core projection-mapping transform chain. For calibration
    purposes, the WORLD step may be bypassed by going directly from
    SURFACE_LOCAL → CAMERA (if surface is defined in camera frame).
    """

    # Core transforms
    surface_to_world: SurfaceLocalToWorldTransform
    world_to_camera: WorldToCameraTransform
    camera_to_projector: CameraToProjectorTransform
    projector_intrinsics: ProjectorIntrinsics

    # Optional direct path (for calibration frame)
    surface_to_camera: Any = None  # SurfaceLocalToCameraTransform if available

    def project_surface_point(
        self,
        point_surface: GeoVec3,
        use_direct_path: bool = False,
    ) -> tuple[float, float]:
        """Project a surface-local point to projector pixels.

        Args:
            point_surface: Point in SURFACE_LOCAL coordinates (meters)
            use_direct_path: If True and surface_to_camera is available,
                bypass WORLD step for calibration-frame accuracy.

        Returns:
            (u, v) in PROJECTOR_PIXEL coordinates
        """
        # SURFACE_LOCAL → WORLD (or CAMERA directly)
        if use_direct_path and self.surface_to_camera is not None:
            point_camera = self.surface_to_camera.apply_point(point_surface)
        else:
            point_world = self.surface_to_world.apply_point(point_surface)
            point_camera = self.world_to_camera.apply_point(point_world)

        # CAMERA → PROJECTOR
        point_projector = self.camera_to_projector.apply_point(point_camera)

        # PROJECTOR → PROJECTOR_PIXEL
        return self.projector_intrinsics.project_point(point_projector)

    def project_surface_point_uv(
        self,
        point_surface: GeoVec3,
        use_direct_path: bool = False,
    ) -> tuple[float, float]:
        """Project surface point to normalized projector UV [0,1]x[0,1]."""
        u, v = self.project_surface_point(point_surface, use_direct_path)
        return self.projector_intrinsics.pixel_to_uv((u, v))

    def surface_uv_to_projector_uv(
        self,
        surface_uv: tuple[float, float],
        surface_width_m: float,
        surface_height_m: float,
        use_direct_path: bool = False,
    ) -> tuple[float, float]:
        """Convert surface UV [0,1]x[0,1] to projector UV [0,1]x[0,1].

        Surface UV: origin bottom-left (0,0), V up (OpenGL convention)
        Projector UV: origin top-left (0,0), V down (image convention)

        Args:
            surface_uv: (u, v) in [0,1]x[0,1], OpenGL convention
            surface_width_m: Surface width in meters (for local coordinate scaling)
            surface_height_m: Surface height in meters
            use_direct_path: If True, use direct camera path

        Returns:
            (u, v) in [0,1]x[0,1], image/projector convention
        """
        # Surface UV -> Surface local point
        # Surface local origin is at center, X right, Y up
        u, v = surface_uv
        x = (u - 0.5) * surface_width_m
        y = (v - 0.5) * surface_height_m  # V up: v=0 bottom (-hh), v=1 top (+hh)
        z = 0.0  # Planar surface at Z=0
        point_surface = GeoVec3(x, y, z)

        return self.project_surface_point_uv(point_surface, use_direct_path)

    def surface_uv_to_projector_pixel(
        self,
        surface_uv: tuple[float, float],
        surface_width_m: float,
        surface_height_m: float,
        use_direct_path: bool = False,
    ) -> tuple[float, float]:
        """Convert surface UV directly to projector pixels."""
        proj_uv = self.surface_uv_to_projector_uv(
            surface_uv, surface_width_m, surface_height_m, use_direct_path
        )
        return self.projector_intrinsics.uv_to_pixel(proj_uv)


# =============================================================================
# Homography for Planar Surfaces
# =============================================================================


@dataclass(frozen=True)
class PlanarHomography:
    """3x3 homography matrix for planar surface projection.

    Maps: surface_uv (homogeneous) -> projector_uv (homogeneous)
    or equivalently: surface_local (Z=0) -> projector_pixels

    H is a 3x3 matrix such that:
        [u, v, 1]^T ~ H @ [x, y, 1]^T
    where (x, y) are surface-local coordinates on the plane Z=0.
    """

    matrix: NDArray[np.float64]  # 3x3

    def __post_init__(self) -> None:
        if self.matrix.shape != (3, 3):
            raise ValueError(f"Homography must be 3x3, got {self.matrix.shape}")

    @classmethod
    def from_surface_to_projector(
        cls,
        surface_to_world: SurfaceLocalToWorldTransform,
        world_to_camera: WorldToCameraTransform,
        camera_to_projector: CameraToProjectorTransform,
        projector_intrinsics: ProjectorIntrinsics,
    ) -> PlanarHomography:
        """Compute homography for a planar surface at Z=0.

        This is the optimized path for flat surfaces - avoids full 3D chain per point.
        """
        # Compose the 3D chain for points on Z=0 plane
        # Surface local (x, y, 0) -> World -> Camera -> Projector -> Pixels

        # Build 4x4 matrix for surface_local (Z=0) -> projector_local
        chain = (
            Transform(matrix=surface_to_world.matrix)
            .compose(Transform(matrix=world_to_camera.matrix))
            .compose(Transform(matrix=camera_to_projector.matrix))
        )
        m = chain.to_numpy()  # 4x4: surface_local (homogeneous) -> projector_local

        # Extract 3x3 for points on Z=0 plane
        # [X_p]   [M00 M01 M02 M03] [x]
        # [Y_p] = [M10 M11 M12 M13] [y]
        # [Z_p]   [M20 M21 M22 M23] [0]
        # [1  ]   [M30 M31 M32 M33] [1]
        #
        # Projector pixel: [u, v, 1]^T ~ K_proj @ [X_p, Y_p, Z_p]^T
        # In homogeneous: [u, v, w]^T = K_proj @ [X_p, Y_p, Z_p, 1]^T
        # where [X_p, Y_p, Z_p] = M @ [x, y, 0, 1]^T
        #
        # So: [X_p, Y_p, Z_p, 1]^T = M @ [x, y, 0, 1]^T
        # Let M' be the 3x4 submatrix [M00 M01 M03; M10 M11 M13; M20 M21 M23]
        # [X_p]   [M00 M01 M03] [x]
        # [Y_p] = [M10 M11 M13] [y]
        # [Z_p]   [M20 M21 M23] [1]
        #
        # Then pixel = K_proj @ [X_p, Y_p, Z_p]^T / Z_p
        # In homogeneous: [u*w, v*w, w]^T = K_proj @ [X_p, Y_p, Z_p]^T
        # So the homography H = K_proj @ M'
        k = projector_intrinsics.camera_matrix()  # 3x3
        m_prime = m[:3, [0, 1, 3]]  # 3x3: columns 0, 1, 3
        h = k @ m_prime
        return cls(matrix=h)

    def apply_local_point(self, point: GeoVec3) -> tuple[float, float]:
        """Apply homography to surface-local point (Z=0 assumed) -> projector pixels."""
        x, y = point.x, point.y
        # Homogeneous: [x, y, 1]
        v = np.array([x, y, 1.0], dtype=np.float64)
        result = self.matrix @ v
        if abs(result[2]) < 1e-12:
            raise ValueError("Homography produced point at infinity")
        u = result[0] / result[2]
        v_ = result[1] / result[2]
        return (float(u), float(v_))

    def apply_local_point_uv(
        self, point: GeoVec3, resolution: tuple[int, int]
    ) -> tuple[float, float]:
        """Apply homography and return normalized UV."""
        u, v = self.apply_local_point(point)
        return (u / resolution[0], v / resolution[1])


# =============================================================================
# Factory Functions
# =============================================================================


def create_surface_to_world(surface: Any) -> SurfaceLocalToWorldTransform:
    """Create SurfaceLocalToWorldTransform from ConfiguredSurface."""
    return SurfaceLocalToWorldTransform(matrix=surface.transform)


def create_world_to_camera(camera_extrinsics: Any) -> WorldToCameraTransform:
    """Create WorldToCameraTransform from CameraExtrinsics."""
    return WorldToCameraTransform.from_camera_extrinsics(camera_extrinsics)


def create_camera_to_projector(projector_pose: Mat4x4) -> CameraToProjectorTransform:
    """Create CameraToProjectorTransform from projector pose (projector_local → camera_frame)."""
    return CameraToProjectorTransform.from_projector_pose(projector_pose)


def create_projector_intrinsics(
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    resolution_x: int,
    resolution_y: int,
) -> ProjectorIntrinsics:
    """Create ProjectorIntrinsics from standard parameters."""
    return ProjectorIntrinsics(
        fx=fx,
        fy=fy,
        cx=cx,
        cy=cy,
        resolution_x=resolution_x,
        resolution_y=resolution_y,
    )
