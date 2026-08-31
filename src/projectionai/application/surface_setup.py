"""Surface setup — thin application layer over canonical Surface contracts."""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from projectionai.calibration.surface_model import SurfacePose
from projectionai.calibration.types import Mat4x4, ProjectionType
from projectionai.domain.geometry import BoundingBox, Vec3
from projectionai.domain.surface import SurfaceType


@dataclass(frozen=True)
class SurfaceValidationReport:
    is_ok: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    surface_id: str = ""
    supported_for_calibration: bool = False


@dataclass(frozen=True)
class SurfaceSetupView:
    surface_id: str
    name: str
    surface_type: SurfaceType
    width_m: float
    height_m: float
    depth_m: float
    transform: Mat4x4
    position: Vec3
    orientation: tuple[float, float, float, float]  # quat w,x,y,z
    bounding_box: BoundingBox
    is_planar_supported: bool
    validation: SurfaceValidationReport

    @property
    def is_valid(self) -> bool:
        return self.validation.is_ok

    @property
    def supported_for_calibration(self) -> bool:
        return self.validation.supported_for_calibration


def _mat4x4_to_numpy(m: Mat4x4) -> np.ndarray:
    """Convert Mat4x4 (16 floats column-major) to 4x4 ndarray."""
    return np.array(m.data, dtype=np.float64).reshape(4, 4, order="F")


def _pose_to_vec3_quat(
    transform: Mat4x4,
) -> tuple[Vec3, tuple[float, float, float, float]]:
    """Extract position + quat from Mat4x4 — reuse geometry Pose logic."""
    from projectionai.domain.geometry import Pose

    pose = Pose.from_matrix(_mat4x4_to_numpy(transform))
    return pose.position, pose.rotation


def validate_surface(
    surface_id: str,
    pose: SurfacePose | None,
    *,
    allow_non_planar: bool = False,
) -> SurfaceValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    if pose is None:
        return SurfaceValidationReport(
            is_ok=False,
            errors=("missing surface",),
            surface_id=surface_id,
            supported_for_calibration=False,
        )

    # Type check
    try:
        st = (
            SurfaceType(pose.surface_type.value)
            if hasattr(pose.surface_type, "value")
            else SurfaceType(str(pose.surface_type))
        )
    except ValueError:
        errors.append(f"unsupported surface type {pose.surface_type!r}")
        return SurfaceValidationReport(
            is_ok=False,
            errors=tuple(errors),
            surface_id=surface_id,
            supported_for_calibration=False,
        )

    is_planar = st == SurfaceType.FLAT and pose.curvature_radius == 0.0
    supported = is_planar or allow_non_planar
    if not is_planar and not allow_non_planar:
        warnings.append(
            "Non-planar calibration not yet supported — planar calibration supported, non-planar will use planar approximation"
        )
        # Do not silently convert — mark as not supported but still valid if dimensions ok
        supported = False

    # Dimensions
    for name, val in [("width", pose.width), ("height", pose.height)]:
        if not math.isfinite(val):
            errors.append(f"{name} is NaN/Inf")
        elif val <= 0:
            errors.append(f"{name} must be >0, got {val}")
    if pose.depth != 0.0:
        if not math.isfinite(pose.depth):
            errors.append("depth is NaN/Inf")
        elif pose.depth < 0:
            errors.append(f"depth must be >=0, got {pose.depth}")

    if pose.width * pose.height == 0:
        errors.append("zero-area surface")

    # Transform
    try:
        np_mat = _mat4x4_to_numpy(pose.transform)
        if np_mat.shape != (4, 4):
            errors.append(f"transform must be 4x4, got {np_mat.shape}")
        elif not np.all(np.isfinite(np_mat)):
            errors.append("transform contains NaN/Inf")
        else:
            det = float(np.linalg.det(np_mat))
            if not math.isfinite(det) or abs(det) < 1e-9:
                errors.append("transform singular or non-invertible")
            # Check sane orientation via det >0
            if det < 0:
                warnings.append(
                    "transform has negative determinant — mirrored orientation"
                )
    except Exception as exc:
        errors.append(f"transform invalid: {exc}")

    is_ok = len(errors) == 0
    return SurfaceValidationReport(
        is_ok=is_ok,
        errors=tuple(errors),
        warnings=tuple(warnings),
        surface_id=surface_id,
        supported_for_calibration=supported and is_ok,
    )


def build_surface_view(
    surface_id: str,
    name: str,
    pose: SurfacePose,
) -> SurfaceSetupView:
    validation = validate_surface(surface_id, pose)
    # Position/orientation from transform
    try:
        pos, quat = _pose_to_vec3_quat(pose.transform)
    except Exception:
        pos = Vec3(0, 0, 0)
        quat = (1.0, 0.0, 0.0, 0.0)

    # Bounding box from dimensions
    hw = pose.width * 0.5
    hh = pose.height * 0.5
    bbox = BoundingBox(
        min_x=-hw,
        min_y=-hh,
        min_z=0,
        max_x=hw,
        max_y=hh,
        max_z=pose.depth if pose.depth > 0 else 0.01,
    )

    is_planar = (
        SurfaceType(pose.surface_type.value) == SurfaceType.FLAT
        if hasattr(pose.surface_type, "value")
        else str(pose.surface_type) == "flat"
    )
    # Use pose.is_planar if available
    with contextlib.suppress(Exception):
        is_planar = pose.is_planar

    return SurfaceSetupView(
        surface_id=surface_id,
        name=name,
        surface_type=SurfaceType(pose.surface_type.value)
        if hasattr(pose.surface_type, "value")
        else SurfaceType(str(pose.surface_type)),
        width_m=pose.width,
        height_m=pose.height,
        depth_m=pose.depth,
        transform=pose.transform,
        position=pos,
        orientation=quat,
        bounding_box=bbox,
        is_planar_supported=is_planar,
        validation=validation,
    )


def surface_to_dict(surface_id: str, pose: SurfacePose) -> dict[str, Any]:
    """Reuse existing serialization — pose is already serializable via project_format."""
    return {
        "surface_id": surface_id,
        "surface_type": pose.surface_type.value
        if hasattr(pose.surface_type, "value")
        else str(pose.surface_type),
        "width": pose.width,
        "height": pose.height,
        "depth": pose.depth,
        "transform": list(pose.transform.data),
    }


def dict_to_surface_pose(data: dict[str, Any]) -> SurfacePose:
    """Reuse existing deserialization — identity only for genuinely missing, not corrupt."""
    if "surface_type" not in data or data["surface_type"] is None:
        st = ProjectionType.FLAT
    else:
        st = ProjectionType(data["surface_type"])
    raw_mat = data.get("transform")
    if raw_mat is None:
        # Genuinely missing — legacy field, fallback to identity is valid
        transform = Mat4x4.identity()
    elif isinstance(raw_mat, list) and len(raw_mat) == 16:
        # Flat 16 — keep even if non-finite, let validate_surface catch it
        flat = tuple(float(x) for x in raw_mat)
        transform = Mat4x4(data=flat)
    elif (
        isinstance(raw_mat, list)
        and len(raw_mat) == 4
        and all(isinstance(r, list) for r in raw_mat)
    ):
        for idx, row in enumerate(raw_mat):
            if len(row) != 4:
                raise ValueError(
                    f"Invalid transform row {idx} size, expected 4 got {len(row)}"
                )
        # Convert row-major nested input to column-major ordering expected by Mat4x4
        flat = tuple(float(raw_mat[r][c]) for c in range(4) for r in range(4))
        transform = Mat4x4(data=flat)
    else:
        # Malformed/corrupt present value — do not silently become identity
        raise ValueError(f"Invalid transform format: {raw_mat!r}")
    return SurfacePose(
        surface_type=st,
        width=float(data.get("width", 0)),
        height=float(data.get("height", 0)),
        depth=float(data.get("depth", 0)),
        transform=transform,
    )
