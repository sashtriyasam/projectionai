"""Camera model — physical and optical camera properties.

Designed for multi-camera setups. Each camera is identified by a unique ID
and carries its own intrinsics, extrinsics, and pose.

Cameras are used during calibration to observe projected patterns on
surfaces and compute the projector-to-surface transform.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from projectionai.calibration.types import Mat4x4, Vec3

# Common distortion models
DISTORTION_NONE = "none"
DISTORTION_RADIAL_TANGENTIAL = "radial_tangential"  # Brown-Conrady
DISTORTION_EQUIDISTANT = "equidistant"  # fisheye
DISTORTION_FOV = "fov"  # F-theta fisheye


@dataclass
class CameraIntrinsics:
    """Intrinsic camera parameters — sensor and lens properties.

    Defines the mapping from 3D camera-space coordinates to 2D pixel
    coordinates using the standard pinhole model.

    Future: add distortion map support for non-parametric models.
    """

    resolution_x: int = 1920
    resolution_y: int = 1080

    # Focal length in pixels
    fx: float = 1000.0
    fy: float = 1000.0

    # Principal point in pixels
    cx: float = 960.0
    cy: float = 540.0

    # Distortion coefficients (Brown-Conrady model: k1, k2, p1, p2, k3)
    distortion_model: str = DISTORTION_NONE
    distortion_coeffs: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 0.0)

    # Skew factor (typically 0 for modern sensors)
    skew: float = 0.0

    # Camera matrix (3x3)
    # [fx, skew, cx]
    # [ 0,   fy, cy]
    # [ 0,    0,  1]

    def camera_matrix(self) -> tuple[float, ...]:
        """Return the 3x3 camera matrix as a flat tuple (row-major)."""
        return (
            self.fx,
            self.skew,
            self.cx,
            0.0,
            self.fy,
            self.cy,
            0.0,
            0.0,
            1.0,
        )

    @property
    def aspect_ratio(self) -> float:
        """Calculate sensor aspect ratio from resolution."""
        if self.resolution_y == 0:
            return 16.0 / 9.0
        return self.resolution_x / self.resolution_y


@dataclass
class CameraExtrinsics:
    """Extrinsic parameters — camera position/orientation in world space.

    The 4x4 transform maps from camera-local coordinates to world space.
    """

    transform: Mat4x4 = field(default_factory=Mat4x4.identity)

    @property
    def position(self) -> Vec3:
        """Extract position from the transform (col 3, rows 0-2)."""
        return Vec3(
            x=float(self.transform.data[3]),
            y=float(self.transform.data[7]),
            z=float(self.transform.data[11]),
        )


@dataclass
class CameraPose:
    """Combined pose (intrinsics + extrinsics) for a single camera.

    This is the full description of a camera's state during calibration.
    """

    intrinsics: CameraIntrinsics = field(default_factory=CameraIntrinsics)
    extrinsics: CameraExtrinsics = field(default_factory=CameraExtrinsics)

    enabled: bool = True
    label: str = ""


@dataclass
class CameraModel:
    """Complete camera description — metadata + intrinsic + extrinsic.

    Holds multiple ``CameraPose`` instances for multi-camera setups.
    Each pose is keyed by a unique camera ID.
    """

    name: str = "Camera"
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    interface: str = "usb"  # usb, ethernet, hdmi, mipi, custom

    # Multi-camera support
    poses: dict[str, CameraPose] = field(default_factory=dict)

    def add_pose(self, pose_id: str, pose: CameraPose) -> None:
        """Add a camera pose for a given camera."""
        self.poses[pose_id] = pose

    def remove_pose(self, pose_id: str) -> None:
        """Remove a camera pose."""
        self.poses.pop(pose_id, None)

    def get_pose(self, pose_id: str) -> CameraPose | None:
        """Get a specific pose by ID."""
        return self.poses.get(pose_id)

    @property
    def pose_count(self) -> int:
        """Number of configured camera poses."""
        return len(self.poses)

    @property
    def all_enabled(self) -> list[CameraPose]:
        """Return all enabled poses."""
        return [p for p in self.poses.values() if p.enabled]
