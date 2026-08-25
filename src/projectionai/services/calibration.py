"""Calibration abstraction.

Calibration aligns the virtual 3D model with the physical object so
that projected content lands on the correct surfaces.

Also provides ``calibration_to_warp_mesh`` — a pure-function adapter that
converts a ``CalibrationResult`` + surface dimensions into a ``WarpMesh``
without importing any infrastructure-layer code.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np

from projectionai.domain.calibration import (
    CalibrationPoint,
    CalibrationResult,
    ProjectorCalibration,
)
from projectionai.domain.calibration_session import (
    CalibrationResult as DomainCalibrationResult,
)
from projectionai.domain.geometry import Mesh, Vec3
from projectionai.domain.projection import ProjectionMapping
from projectionai.domain.transforms import (
    ProjectorIntrinsics,
    Transform,
)
from projectionai.domain.warp_mesh import (
    WarpMesh,
    WarpMeshGeneration,
    create_planar_grid_warp_mesh,
)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationGuide:
    """Visual guide rendered during manual calibration."""

    points: tuple[CalibrationPoint, ...]
    instructions: str = ""
    step: int = 0
    total_steps: int = 0


# ---------------------------------------------------------------------------
# Calibrator — abstract interface
# ---------------------------------------------------------------------------


class Calibrator(ABC):
    """Abstract calibrator.

    Subclasses implement specific calibration strategies:
    - Manual: user clicks corresponding points.
    - Automatic: structured light / ICP-based registration.
    - Hybrid: automatic first, manual refinement.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Set up calibration resources."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Release resources."""

    @abstractmethod
    async def start_calibration(
        self,
        reference_mesh: Mesh | None = None,
    ) -> CalibrationGuide:
        """Begin the calibration process.

        Returns a *CalibrationGuide* with initial instructions
        and guide points for the user.
        """

    @abstractmethod
    async def add_correspondence(
        self,
        image_point: tuple[float, float],
        model_point: tuple[float, float, float],
        confidence: float = 1.0,
    ) -> CalibrationGuide:
        """Add a 2D-3D correspondence point for manual calibration.

        Returns an updated guide (next point to click, or completion).
        """

    @abstractmethod
    async def compute_calibration(self) -> CalibrationResult:
        """Compute the final calibration from collected correspondences."""

    @abstractmethod
    async def auto_calibrate(
        self,
        source_mesh: Mesh,
        target_mesh: Mesh,
        max_iterations: int = 100,
    ) -> CalibrationResult:
        """Run automatic (ICP / feature-based) calibration.

        Returns the computed transform.
        """

    @abstractmethod
    async def refine_calibration(
        self,
        current: CalibrationResult,
        observations: tuple[CalibrationPoint, ...],
    ) -> CalibrationResult:
        """Refine an existing calibration with new observations."""


# ---------------------------------------------------------------------------
# Planar calibration → WarpMesh adapter
# ---------------------------------------------------------------------------


class CalibrationToWarpMeshError(Exception):
    """Raised when calibration data cannot produce a valid WarpMesh."""


def calibration_to_warp_mesh(
    calibration: DomainCalibrationResult | CalibrationResult,
    surface_width_m: float,
    surface_height_m: float,
    projector_index: int = 0,
    grid_rows: int = 4,
    grid_cols: int = 4,
    surface_id: str = "",
) -> WarpMesh:
    """Convert a CalibrationResult into a WarpMesh for a planar surface.

    Pure function — no infrastructure imports, no I/O.  Uses the transform
    chain from ``domain/transforms.py`` to project the four surface corners
    into projector UV space, then builds a grid warp mesh via
    ``create_planar_grid_warp_mesh``.

    Parameters
    ----------
    calibration : CalibrationResult
        Complete calibration with at least one projector entry.
    surface_width_m, surface_height_m : float
        Physical surface dimensions in metres.
    projector_index : int
        Which projector in ``calibration.projectors`` to use (default 0).
    grid_rows, grid_cols : int
        Grid subdivisions for the warp mesh.
    surface_id : str
        Optional stable surface reference.

    Returns
    -------
    WarpMesh
        Grid warp mesh mapping surface-local positions to projector UVs.

    Raises
    ------
    CalibrationToWarpMeshError
        If the calibration data is incomplete or the projection is invalid.
    """
    if isinstance(calibration, DomainCalibrationResult):
        return _canonical_to_warp_mesh(
            calibration,
            surface_width_m,
            surface_height_m,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            surface_id=surface_id,
        )
    # Legacy CalibrationResult path
    if not calibration.projectors:
        raise CalibrationToWarpMeshError("Calibration contains no projector data")
    if projector_index >= len(calibration.projectors):
        raise CalibrationToWarpMeshError(
            f"projector_index {projector_index} out of range "
            f"(calibration has {len(calibration.projectors)} projectors)"
        )
    if surface_width_m <= 0 or surface_height_m <= 0:
        raise CalibrationToWarpMeshError(
            f"Surface dimensions must be positive, got "
            f"{surface_width_m}x{surface_height_m}"
        )
    if grid_rows <= 0 or grid_cols <= 0:
        raise CalibrationToWarpMeshError(
            f"Grid subdivisions must be positive, got "
            f"grid_rows={grid_rows}, grid_cols={grid_cols}"
        )

    pc = calibration.projectors[projector_index]

    # --- Build projector intrinsics from FOV + resolution --------------------
    try:
        intrinsics = _projector_intrinsics_from_calibration(pc)
    except ValueError as exc:
        raise CalibrationToWarpMeshError(
            f"Cannot derive projector intrinsics: {exc}"
        ) from exc

    # --- Build the world → projector transform ------------------------------
    # ProjectorCalibration.pose: projector pose in world coordinates.
    # pose.as_matrix() is projector_local → world; inverse is world → projector_local.
    projector_world_matrix = pc.pose.as_matrix()
    try:
        world_to_projector = Transform.from_numpy(np.linalg.inv(projector_world_matrix))
    except (np.linalg.LinAlgError, ValueError) as exc:
        raise CalibrationToWarpMeshError(
            f"Projector pose matrix is invalid or singular: {exc}"
        ) from exc

    # If calibration has object_pose, apply it (surface-local → world).
    # Otherwise assume identity (surface is already in world frame).
    if calibration.object_pose is not None:
        surface_to_world = Transform.from_numpy(calibration.object_pose.as_matrix())
    else:
        surface_to_world = Transform()  # identity

    projector_uv_corners, projector_uvs_full = _compute_warp_uvs(
        intrinsics,
        world_to_projector,
        surface_to_world,
        surface_width_m,
        surface_height_m,
        grid_rows,
        grid_cols,
    )

    # --- Build the warp mesh -------------------------------------------------
    proj_id = pc.projector_id or f"projector_{projector_index}"
    sid = surface_id or "calibration_surface"

    mesh = create_planar_grid_warp_mesh(
        surface_id=sid,
        projector_id=proj_id,
        width_m=surface_width_m,
        height_m=surface_height_m,
        grid_rows=grid_rows,
        grid_cols=grid_cols,
        projector_uv_corners=(
            projector_uv_corners[0],  # BL
            projector_uv_corners[1],  # BR
            projector_uv_corners[2],  # TR
            projector_uv_corners[3],  # TL
        ),
        generation_method=WarpMeshGeneration.CALIBRATION,
        metadata={
            "source": "calibration_to_warp_mesh",
            "projector_index": projector_index,
            "reprojection_error": calibration.reprojection_error,
            "calibration_confidence": calibration.confidence,
        },
        projector_uvs_full=projector_uvs_full,
    )

    # --- Validate the result -------------------------------------------------
    errors = mesh.validate()
    if errors:
        raise CalibrationToWarpMeshError(
            f"Generated warp mesh is invalid: {'; '.join(errors)}"
        )

    return mesh


def _canonical_to_warp_mesh(
    calibration: Any,
    surface_width_m: float,
    surface_height_m: float,
    grid_rows: int = 4,
    grid_cols: int = 4,
    surface_id: str = "",
    apply_distortion: bool = False,
    distortion_coeffs: Any | None = None,  # noqa: ARG001 — reserved for future distortion model
) -> WarpMesh:
    if surface_width_m <= 0 or surface_height_m <= 0:
        raise CalibrationToWarpMeshError(
            f"Surface dimensions must be positive, got {surface_width_m}x{surface_height_m}"
        )
    if grid_rows <= 0 or grid_cols <= 0:
        raise CalibrationToWarpMeshError(
            f"Grid subdivisions must be positive, got grid_rows={grid_rows}, grid_cols={grid_cols}"
        )
    # ID mismatch guard
    cal_surf = getattr(calibration, "surface_id", "")
    if surface_id and cal_surf and surface_id != cal_surf:
        raise CalibrationToWarpMeshError(
            f"Surface ID mismatch: calibration {cal_surf!r} vs requested {surface_id!r}"
        )
    # Distortion is pinhole-only in this phase; interface reserved for future
    if apply_distortion:
        raise NotImplementedError(
            "Distortion correction not yet implemented — keep apply_distortion=False"
        )
    k = calibration.projector_intrinsics
    intr = ProjectorIntrinsics(
        fx=float(k[0, 0]),
        fy=float(k[1, 1]),
        cx=float(k[0, 2]),
        cy=float(k[1, 2]),
        resolution_x=int(calibration.projector_resolution[0]),
        resolution_y=int(calibration.projector_resolution[1]),
    )
    pose = calibration.projector_pose
    try:
        world_to_proj = Transform.from_numpy(np.linalg.inv(pose))
    except Exception as exc:
        raise CalibrationToWarpMeshError(f"Projector pose invalid: {exc}") from exc
    obj_pose = getattr(calibration, "object_pose", None)
    if obj_pose is not None:
        surface_to_world = Transform.from_numpy(obj_pose.as_matrix())
    else:
        surface_to_world = Transform()
    uv_corners, uvs_full = _compute_warp_uvs(
        intr,
        world_to_proj,
        surface_to_world,
        surface_width_m,
        surface_height_m,
        grid_rows,
        grid_cols,
    )
    sid = surface_id or getattr(calibration, "surface_id", "") or "calibration_surface"
    pid = getattr(calibration, "projector_id", "") or "projector_0"
    mesh = create_planar_grid_warp_mesh(
        surface_id=sid,
        projector_id=pid,
        width_m=surface_width_m,
        height_m=surface_height_m,
        grid_rows=grid_rows,
        grid_cols=grid_cols,
        projector_uv_corners=(
            uv_corners[0],
            uv_corners[1],
            uv_corners[2],
            uv_corners[3],
        ),
        generation_method=WarpMeshGeneration.CALIBRATION,
        metadata={
            "source": "canonical_to_warp_mesh",
            "reprojection_error": calibration.reprojection_error,
            "confidence": calibration.confidence,
        },
        projector_uvs_full=uvs_full,
    )
    errs = mesh.validate()
    if errs:
        raise CalibrationToWarpMeshError(
            f"Generated warp mesh invalid: {'; '.join(errs)}"
        )
    return mesh


def _projector_intrinsics_from_calibration(
    pc: ProjectorCalibration,
) -> ProjectorIntrinsics:
    """Derive ProjectorIntrinsics from a ProjectorCalibration entry.

    Uses ``fov_degrees`` and ``resolution_width/height`` to compute
    focal length (assuming symmetric FOV in both axes).
    """
    if pc.fov_degrees <= 0 or pc.fov_degrees >= 180:
        raise ValueError(f"FOV must be in (0, 180) degrees, got {pc.fov_degrees}")

    res_x = pc.resolution_width
    res_y = pc.resolution_height
    fov_rad = math.radians(pc.fov_degrees)

    # Focal length from horizontal FOV: fx = (width/2) / tan(fov/2)
    fx = (res_x * 0.5) / math.tan(fov_rad * 0.5)
    # Assume square pixels → fy = fx
    fy = fx
    cx = res_x * 0.5
    cy = res_y * 0.5

    return ProjectorIntrinsics(
        fx=fx,
        fy=fy,
        cx=cx,
        cy=cy,
        resolution_x=res_x,
        resolution_y=res_y,
    )


def _compute_warp_uvs(
    intrinsics: ProjectorIntrinsics,
    world_to_projector: Transform,
    surface_to_world: Transform,
    surface_width_m: float,
    surface_height_m: float,
    grid_rows: int,
    grid_cols: int,
) -> tuple[list[tuple[float, float]], Any]:
    """Shared warp-mesh UV computation for both calibration paths.

    Projects the four surface corners and every grid vertex
    (surface-local → world → projector_local → pixel → UV) and returns
    the corner UVs and the full per-vertex UV array. Raises
    ``CalibrationToWarpMeshError`` when a point projects behind the
    projector plane.
    """
    hw = surface_width_m * 0.5
    hh = surface_height_m * 0.5
    corners_local = [
        Vec3(-hw, -hh, 0.0),  # bottom-left
        Vec3(hw, -hh, 0.0),  # bottom-right
        Vec3(hw, hh, 0.0),  # top-right
        Vec3(-hw, hh, 0.0),  # top-left
    ]
    uv_corners: list[tuple[float, float]] = []
    for corner in corners_local:
        pt_world = surface_to_world.apply_point(corner)
        pt_proj = world_to_projector.apply_point(pt_world)
        try:
            pix = intrinsics.project_point(pt_proj)
        except ValueError as exc:
            raise CalibrationToWarpMeshError(
                f"Corner {corner} projects behind projector plane: {exc}"
            ) from exc
        uv_corners.append(intrinsics.pixel_to_uv(pix))
    num_verts = (grid_rows + 1) * (grid_cols + 1)
    uvs_full = np.zeros((num_verts, 2), dtype=np.float64)
    idx = 0
    for r in range(grid_rows + 1):
        for c in range(grid_cols + 1):
            s = c / grid_cols
            t = r / grid_rows
            pt_local = Vec3(-hw + s * surface_width_m, -hh + t * surface_height_m, 0.0)
            pt_world = surface_to_world.apply_point(pt_local)
            pt_proj = world_to_projector.apply_point(pt_world)
            try:
                pix = intrinsics.project_point(pt_proj)
            except ValueError as exc:
                raise CalibrationToWarpMeshError(
                    f"Grid vertex projects behind plane: {exc}"
                ) from exc
            uv = intrinsics.pixel_to_uv(pix)
            uvs_full[idx, 0] = uv[0]
            uvs_full[idx, 1] = uv[1]
            idx += 1
    return uv_corners, uvs_full


def create_projection_mapping(
    calibration: Any,
    warp_mesh: WarpMesh,
    warp_mesh_asset_id: str,
    surface_id: str = "",
    projector_id: str = "",
) -> ProjectionMapping:
    """Create a ProjectionMapping that references a validated calibration and warp mesh.

    Validates ID consistency and mesh validity. WarpMesh is stored as an Asset;
    only its asset ID is embedded in the mapping.
    """
    cal_proj = getattr(calibration, "projector_id", "")
    cal_surf = getattr(calibration, "surface_id", "")
    cal_id = getattr(calibration, "calibration_id", "")
    if not cal_id:
        raise ValueError("CalibrationResult must have a calibration_id")
    pid = projector_id or cal_proj or warp_mesh.projector_id
    sid = surface_id or cal_surf or warp_mesh.surface_id
    if cal_proj and pid != cal_proj:
        raise ValueError(
            f"Projector ID mismatch: calibration {cal_proj!r} vs mapping {pid!r}"
        )
    if cal_surf and sid != cal_surf:
        raise ValueError(
            f"Surface ID mismatch: calibration {cal_surf!r} vs mapping {sid!r}"
        )
    if warp_mesh.projector_id and pid != warp_mesh.projector_id:
        raise ValueError(
            f"WarpMesh projector_id {warp_mesh.projector_id!r} != mapping {pid!r}"
        )
    if warp_mesh.surface_id and sid != warp_mesh.surface_id:
        raise ValueError(
            f"WarpMesh surface_id {warp_mesh.surface_id!r} != mapping {sid!r}"
        )
    if not warp_mesh_asset_id:
        raise ValueError("warp_mesh_asset_id must be non-empty")
    errs = warp_mesh.validate()
    if errs:
        raise ValueError(f"WarpMesh invalid: {'; '.join(errs)}")
    return ProjectionMapping(
        projector_id=pid,
        surface_id=sid,
        calibration_id=cal_id,
        warp_mesh_asset_id=warp_mesh_asset_id,
        metadata={
            "calibration_sequence_ids": list(
                getattr(calibration, "calibration_sequence_ids", ())
            ),
            "reprojection_error": getattr(calibration, "reprojection_error", 0.0),
            "coverage": getattr(calibration, "coverage", 0.0),
        },
    )
