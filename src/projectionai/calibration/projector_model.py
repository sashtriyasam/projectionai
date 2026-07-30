"""Projector model — physical and optical projector properties.

Designed for multi-projector setups from day one. Each projector instance
is identified by a unique ID and carries its own lens, intrinsics, extrinsics,
and pose data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from projectionai.calibration.types import (
    LensType,
    Mat4x4,
    Vec3,
    WarpMode,
)


@dataclass
class ProjectorLens:
    """Optical lens properties of a projector.

    These parameters describe the physical lens and its distortion model.
    Future: add radial / tangential distortion coefficients.
    """

    lens_type: LensType = LensType.STANDARD
    throw_ratio: float = 1.5  # distance / width
    lens_shift_x: float = 0.0  # normalized [-1, 1]
    lens_shift_y: float = 0.0  # normalized [-1, 1]
    vertical_offset: float = 0.0  # as fraction of image height
    focal_length_mm: float = 0.0
    distortion_model: str = "none"  # future: "radial", "brown", "fisheye"
    custom_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectorIntrinsics:
    """Intrinsic parameters — properties of the projector as a light source.

    These describe the projection frustum and serve as the forward model
    for converting 3D points to 2D projection coordinates.
    """

    resolution_x: int = 1920
    resolution_y: int = 1080
    aspect_ratio: float = 16.0 / 9.0

    # Frustum (in degrees, for perspective projection)
    horizontal_fov: float = 60.0
    vertical_fov: float = 0.0  # 0 = auto from aspect ratio

    # Pixel pitch / physical properties
    pixel_pitch_mm: float = 0.0
    brightness_lumens: int = 0
    contrast_ratio: int = 0

    # Calibration matrix (3x4 projection matrix flattened)
    # Default: identity-like for an ideal uncalibrated projector
    matrix: tuple[float, ...] = field(
        default_factory=lambda: (
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
        )
    )

    def __post_init__(self) -> None:
        if self.vertical_fov == 0.0 and self.aspect_ratio > 0.0:
            hfov_rad = math.radians(self.horizontal_fov)
            self.vertical_fov = math.degrees(
                2.0 * math.atan(math.tan(hfov_rad * 0.5) / self.aspect_ratio)
            )


@dataclass
class ProjectorExtrinsics:
    """Extrinsic parameters — projector position/orientation in world space.

    The pose defines where the projector is located and how it is oriented
    relative to the world coordinate system.
    """

    # 4x4 transform from projector-local to world space
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
class ProjectorPose:
    """Combined pose (intrinsics + extrinsics) for a single projector.

    This is the full description of a projector's state in the world.
    """

    intrinsics: ProjectorIntrinsics = field(default_factory=ProjectorIntrinsics)
    extrinsics: ProjectorExtrinsics = field(default_factory=ProjectorExtrinsics)
    lens: ProjectorLens = field(default_factory=ProjectorLens)

    # Warp configuration
    warp_mode: WarpMode = WarpMode.PERSPECTIVE
    warp_rows: int = 4
    warp_cols: int = 4

    # Per-projector blend zone (normalized [0,1] per edge)
    blend_left: float = 0.0
    blend_right: float = 0.0
    blend_top: float = 0.0
    blend_bottom: float = 0.0

    enabled: bool = True

    # Colour profile (future: ICC profile or per-channel curves)
    color_profile: str = "sRGB"
    brightness: float = 1.0
    gamma: float = 2.2


@dataclass
class ProjectorModel:
    """Complete projector description — metadata + optical + pose.

    Holds multiple ``ProjectorPose`` instances for multi-projector setups.
    Each pose is keyed by a unique screen/projector ID.
    """

    name: str = "Projector"
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    native_orientation: str = "landscape"  # landscape, portrait

    # Multi-projector support: one pose per output/screen
    poses: dict[str, ProjectorPose] = field(default_factory=dict)

    def add_pose(self, pose_id: str, pose: ProjectorPose) -> None:
        """Add a projector pose for a given output/screen."""
        self.poses[pose_id] = pose

    def remove_pose(self, pose_id: str) -> None:
        """Remove a projector pose."""
        self.poses.pop(pose_id, None)

    def get_pose(self, pose_id: str) -> ProjectorPose | None:
        """Get a specific pose by ID."""
        return self.poses.get(pose_id)

    @property
    def pose_count(self) -> int:
        """Number of configured projector poses (outputs)."""
        return len(self.poses)

    @property
    def all_enabled(self) -> list[ProjectorPose]:
        """Return all enabled poses."""
        return [p for p in self.poses.values() if p.enabled]
