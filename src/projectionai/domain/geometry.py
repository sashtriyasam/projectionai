"""Geometry primitives and 3D data structures."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

_logger = logging.getLogger(__name__)


def _rotation_to_quat(
    r: NDArray[np.float64],
) -> tuple[float, float, float, float] | None:
    if r.shape != (3, 3) or not np.all(np.isfinite(r)):
        return None
    if not np.allclose(r @ r.T, np.eye(3), atol=1e-6):
        return None
    if np.linalg.det(r) < 0.0:
        return None
    trace = float(np.trace(r))
    if trace > 0.0:
        s = float(np.sqrt(trace + 1.0)) * 2.0
        w = 0.25 * s
        x = (r[2, 1] - r[1, 2]) / s
        y = (r[0, 2] - r[2, 0]) / s
        z = (r[1, 0] - r[0, 1]) / s
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = float(np.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2])) * 2.0
        w = (r[2, 1] - r[1, 2]) / s
        x = 0.25 * s
        y = (r[0, 1] + r[1, 0]) / s
        z = (r[0, 2] + r[2, 0]) / s
    elif r[1, 1] > r[2, 2]:
        s = float(np.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2])) * 2.0
        w = (r[0, 2] - r[2, 0]) / s
        x = (r[0, 1] + r[1, 0]) / s
        y = 0.25 * s
        z = (r[1, 2] + r[2, 1]) / s
    else:
        s = float(np.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1])) * 2.0
        w = (r[1, 0] - r[0, 1]) / s
        x = (r[0, 2] + r[2, 0]) / s
        y = (r[1, 2] + r[2, 1]) / s
        z = 0.25 * s
    n = float(np.sqrt(w * w + x * x + y * y + z * z))
    if n == 0.0 or not np.isfinite(n):
        return None
    return (float(w) / n, float(x) / n, float(y) / n, float(z) / n)


@dataclass(frozen=True)
class Vec3:
    """A 3D vector."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def as_array(self) -> NDArray[np.float64]:
        return np.array([self.x, self.y, self.z], dtype=np.float64)

    @classmethod
    def from_array(cls, arr: NDArray[np.float64]) -> Vec3:
        return cls(float(arr[0]), float(arr[1]), float(arr[2]))


@dataclass(frozen=True)
class Pose:
    """6-DOF pose: position + orientation as a quaternion (w, x, y, z)."""

    position: Vec3 = field(default_factory=Vec3)
    rotation: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)  # w, x, y, z

    @staticmethod
    def identity() -> Pose:
        return Pose()

    def as_matrix(self) -> NDArray[np.float64]:
        """Convert to a 4x4 homogeneous transformation matrix."""
        w, x, y, z = self.rotation
        tx, ty, tz = self.position.x, self.position.y, self.position.z

        xx, yy, zz = x * x, y * y, z * z
        xy, xz, yz = x * y, x * z, y * z
        wx, wy, wz = w * x, w * y, w * z

        return np.array(
            [
                [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy), tx],
                [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx), ty],
                [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy), tz],
                [0, 0, 0, 1],
            ],
            dtype=np.float64,
        )

    @classmethod
    def from_matrix(cls, m: NDArray[np.float64]) -> Pose:
        """Create a Pose from a 4x4 homogeneous matrix.

        Image size, per_point_errors, coverage, warp_mesh and scale are not
        stored in a Pose; only position and orientation are recovered.
        Invalid rotation falls back to identity with a warning, preserving
        translation.
        """
        if m.shape != (4, 4):
            raise ValueError(f"Pose matrix must be (4, 4), got {m.shape}")
        pos = Vec3(float(m[0, 3]), float(m[1, 3]), float(m[2, 3]))
        quat = _rotation_to_quat(np.asarray(m[:3, :3], dtype=np.float64))
        if quat is None:
            _logger.warning(
                "Invalid rotation matrix (non-orthonormal, negative determinant, "
                "or non-finite); falling back to identity rotation. Matrix:\n%s",
                m[:3, :3],
            )
            return cls(position=pos)
        return cls(position=pos, rotation=quat)


def _array_eq(a: np.ndarray | None, b: np.ndarray | None) -> bool:
    """Compare two optional NumPy arrays with ``np.array_equal``."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return bool(np.array_equal(a, b))


@dataclass(frozen=True, eq=False)
class PointCloud:
    """A point cloud in 3D space."""

    points: NDArray[np.float64]  # (N, 3) array of 3D points
    colors: NDArray[np.uint8] | None = None  # (N, 3) optional RGB colors
    normals: NDArray[np.float64] | None = None  # (N, 3) optional normals

    def __post_init__(self) -> None:
        if self.points.ndim != 2 or self.points.shape[1] != 3:
            raise ValueError(f"points must be (N, 3), got {self.points.shape}")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PointCloud):
            return NotImplemented
        return (
            _array_eq(self.points, other.points)
            and _array_eq(self.colors, other.colors)
            and _array_eq(self.normals, other.normals)
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


@dataclass(frozen=True, eq=False)
class Mesh:
    """A triangle mesh."""

    vertices: NDArray[np.float64]  # (V, 3) vertex positions
    faces: NDArray[np.int32]  # (F, 3) triangle indices
    vertex_colors: NDArray[np.uint8] | None = None  # (V, 3) optional
    vertex_normals: NDArray[np.float64] | None = None  # (V, 3) optional
    uv_coords: NDArray[np.float64] | None = None  # (V, 2) optional

    @property
    def num_vertices(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def num_faces(self) -> int:
        return int(self.faces.shape[0])

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mesh):
            return NotImplemented
        return (
            _array_eq(self.vertices, other.vertices)
            and _array_eq(self.faces, other.faces)
            and _array_eq(self.vertex_colors, other.vertex_colors)
            and _array_eq(self.vertex_normals, other.vertex_normals)
            and _array_eq(self.uv_coords, other.uv_coords)
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounding box."""

    min_x: float = 0.0
    min_y: float = 0.0
    min_z: float = 0.0
    max_x: float = 1.0
    max_y: float = 1.0
    max_z: float = 1.0

    @property
    def center(self) -> Vec3:
        return Vec3(
            (self.min_x + self.max_x) / 2,
            (self.min_y + self.max_y) / 2,
            (self.min_z + self.max_z) / 2,
        )

    @property
    def dimensions(self) -> tuple[float, float, float]:
        return (
            self.max_x - self.min_x,
            self.max_y - self.min_y,
            self.max_z - self.min_z,
        )
