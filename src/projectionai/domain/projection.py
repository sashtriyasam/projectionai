"""Projection mapping domain model.

A ProjectionMapping represents the relationship between a projector, a surface,
and the content to be projected, including warp, blend, mask, and crop configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

import numpy as np
from numpy.typing import NDArray


class BlendMode(StrEnum):
    """Edge blending strategy for overlapping projections.

    Matches the calibration-layer MultiProjectorBlendMode but defined here
    for domain-layer independence.
    """

    ALPHA_BLEND = "alpha_blend"
    LINEAR = "linear"
    GAMMA_CORRECT = "gamma_correct"
    CUSTOM = "custom"


def _validate_normalized_range(name: str, value: float) -> None:
    """Validate that a value is in [0, 1]."""
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{name} must be in [0, 1], got {value}")


def _validate_positive(name: str, value: float) -> None:
    """Validate that a value is positive."""
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")
    if value <= 0.0:
        raise ValueError(f"{name} must be positive, got {value}")


@dataclass(frozen=True)
class BlendConfig:
    """Edge blend configuration for a projection mapping.

    All blend zones are normalized [0, 1] relative to the projector
    output resolution. A value of 0.0 means no blending on that edge.
    """

    left: float = 0.0
    right: float = 0.0
    top: float = 0.0
    bottom: float = 0.0
    mode: BlendMode = BlendMode.ALPHA_BLEND
    gamma: float = 2.2

    def __post_init__(self) -> None:
        for edge in ("left", "right", "top", "bottom"):
            _validate_normalized_range(edge, getattr(self, edge))
        _validate_positive("gamma", self.gamma)

    @property
    def has_any_blend(self) -> bool:
        """Return True if any blend zone is non-zero."""
        return any(
            getattr(self, edge) > 0.0 for edge in ("left", "right", "top", "bottom")
        )


@dataclass(frozen=True)
class CropRegion:
    """Normalized crop region in projector output space.

    Coordinates are normalized [0, 1] x [0, 1] relative to the projector
    output resolution. The region defines which portion of the projector
    output is active.
    """

    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0
    enabled: bool = True

    def __post_init__(self) -> None:
        for coord in ("x", "y", "width", "height"):
            _validate_normalized_range(coord, getattr(self, coord))
        if self.enabled:
            if self.width <= 0 or self.height <= 0:
                raise ValueError(
                    f"width and height must be > 0 when enabled, "
                    f"got width={self.width}, height={self.height}"
                )
            x = self.x
            y = self.y
            w = self.width
            h = self.height
            if x + w > 1.0 + 1e-6:
                raise ValueError(f"Crop x + width must be <= 1, got {x + w}")
            if y + h > 1.0 + 1e-6:
                raise ValueError(f"Crop y + height must be <= 1, got {y + h}")

    @property
    def is_full(self) -> bool:
        """Return True if the crop covers the entire output."""
        return (not self.enabled) or (
            abs(self.x) < 1e-6
            and abs(self.y) < 1e-6
            and abs(self.width - 1.0) < 1e-6
            and abs(self.height - 1.0) < 1e-6
        )

    def to_projector_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Convert normalized crop to pixel coordinates.

        Args:
            width: Projector output width in pixels.
            height: Projector output height in pixels.

        Returns:
            Tuple of (x, y, w, h) in pixels.
        """
        if not self.enabled:
            return (0, 0, width, height)
        return (
            round(self.x * width),
            round(self.y * height),
            round(self.width * width),
            round(self.height * height),
        )


def _array_eq(a: NDArray[np.float64] | None, b: NDArray[np.float64] | None) -> bool:
    """Compare two optional NumPy arrays with ``np.array_equal``."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return bool(np.array_equal(a, b))


@dataclass(frozen=True, eq=False)
class ProjectionMapping:
    """A projection mapping: projector -> surface -> content.

    This is the central domain object for projection mapping. It defines
    how content from a projector is warped and blended onto a physical
    projection surface.
    """

    id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    name: str = "Projection Mapping"
    enabled: bool = True

    # References (stable IDs, not embedded objects)
    projector_id: str = ""  # References ProjectorModel pose ID
    surface_id: str = ""  # References SurfaceModel surface ID
    calibration_id: str = ""  # References CalibrationData (optional)

    # Warp reference
    warp_mesh_asset_id: str = ""  # References Asset(PROJECTION) containing warp mesh

    # Blend, mask, crop
    blend: BlendConfig = field(default_factory=BlendConfig)
    mask_asset_id: str = ""  # References Asset(IMAGE/TEXTURE) for alpha mask
    crop: CropRegion = field(default_factory=CropRegion)

    # Color correction per mapping
    color_profile: str = "sRGB"
    brightness: float = 1.0
    gamma: float = 2.2

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: (
            __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()
        )
    )
    updated_at: str = field(
        default_factory=lambda: (
            __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()
        )
    )

    def __post_init__(self) -> None:
        _validate_positive("brightness", self.brightness)
        _validate_positive("gamma", self.gamma)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProjectionMapping):
            return NotImplemented
        return (
            self.id == other.id
            and self.name == other.name
            and self.enabled == other.enabled
            and self.projector_id == other.projector_id
            and self.surface_id == other.surface_id
            and self.calibration_id == other.calibration_id
            and self.warp_mesh_asset_id == other.warp_mesh_asset_id
            and self.blend == other.blend
            and self.mask_asset_id == other.mask_asset_id
            and self.crop == other.crop
            and self.color_profile == other.color_profile
            and abs(self.brightness - other.brightness) < 1e-6
            and abs(self.gamma - other.gamma) < 1e-6
            and self.metadata == other.metadata
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "projector_id": self.projector_id,
            "surface_id": self.surface_id,
            "calibration_id": self.calibration_id,
            "warp_mesh_asset_id": self.warp_mesh_asset_id,
            "blend": {
                "left": self.blend.left,
                "right": self.blend.right,
                "top": self.blend.top,
                "bottom": self.blend.bottom,
                "mode": self.blend.mode.value,
                "gamma": self.blend.gamma,
            },
            "mask_asset_id": self.mask_asset_id,
            "crop": {
                "x": self.crop.x,
                "y": self.crop.y,
                "width": self.crop.width,
                "height": self.crop.height,
                "enabled": self.crop.enabled,
            },
            "color_profile": self.color_profile,
            "brightness": self.brightness,
            "gamma": self.gamma,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ProjectionMapping:
        """Deserialize from a dict."""
        blend_data = data.get("blend", {})
        crop_data = data.get("crop", {})

        kwargs: dict[str, Any] = dict(
            name=data.get("name", "Projection Mapping"),
            enabled=data.get("enabled", True),
            projector_id=data.get("projector_id", ""),
            surface_id=data.get("surface_id", ""),
            calibration_id=data.get("calibration_id", ""),
            warp_mesh_asset_id=data.get("warp_mesh_asset_id", ""),
            blend=BlendConfig(
                left=blend_data.get("left", 0.0),
                right=blend_data.get("right", 0.0),
                top=blend_data.get("top", 0.0),
                bottom=blend_data.get("bottom", 0.0),
                mode=BlendMode(blend_data.get("mode", "alpha_blend")),
                gamma=blend_data.get("gamma", 2.2),
            ),
            mask_asset_id=data.get("mask_asset_id", ""),
            crop=CropRegion(
                x=crop_data.get("x", 0.0),
                y=crop_data.get("y", 0.0),
                width=crop_data.get("width", 1.0),
                height=crop_data.get("height", 1.0),
                enabled=crop_data.get("enabled", True),
            ),
            color_profile=data.get("color_profile", "sRGB"),
            brightness=data.get("brightness", 1.0),
            gamma=data.get("gamma", 2.2),
            metadata=data.get("metadata", {}),
        )
        if "id" in data:
            kwargs["id"] = data["id"]
        if "created_at" in data:
            kwargs["created_at"] = data["created_at"]
        if "updated_at" in data:
            kwargs["updated_at"] = data["updated_at"]
        return ProjectionMapping(**kwargs)
