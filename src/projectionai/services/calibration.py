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

import numpy as np

from projectionai.domain.calibration import (
    CalibrationPoint,
    CalibrationResult,
    ProjectorCalibration,
)
from projectionai.domain.geometry import Mesh, Vec3
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
    calibration: CalibrationResult,
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

    # --- Surface-local corner positions (Z=0 plane) -------------------------
    hw = surface_width_m * 0.5
    hh = surface_height_m * 0.5
    # Surface-local: X right, Y up, origin at centre
    corners_local = [
        Vec3(-hw, -hh, 0.0),  # bottom-left
        Vec3(hw, -hh, 0.0),  # bottom-right
        Vec3(hw, hh, 0.0),  # top-right
        Vec3(-hw, hh, 0.0),  # top-left
    ]

    # --- Transform: surface-local → world → projector_local → UV -------------
    # If calibration has object_pose, apply it (surface-local → world).
    # Otherwise assume identity (surface is already in world frame).
    if calibration.object_pose is not None:
        surface_to_world = Transform.from_numpy(calibration.object_pose.as_matrix())
    else:
        surface_to_world = Transform()  # identity

    projector_uv_corners: list[tuple[float, float]] = []
    for corner in corners_local:
        # surface-local → world
        point_world = surface_to_world.apply_point(corner)
        # world → projector_local
        point_proj = world_to_projector.apply_point(point_world)
        # projector_local → projector_pixel via pinhole
        try:
            pixel = intrinsics.project_point(point_proj)
        except ValueError as exc:
            raise CalibrationToWarpMeshError(
                f"Corner {corner} projects behind projector plane: {exc}"
            ) from exc
        # pixel → UV [0,1]
        uv = intrinsics.pixel_to_uv(pixel)
        projector_uv_corners.append(uv)

    # --- Per-vertex projector UVs (perspective-correct) ----------------------
    num_verts = (grid_rows + 1) * (grid_cols + 1)
    projector_uvs_full = np.zeros((num_verts, 2), dtype=np.float64)
    idx = 0
    for r in range(grid_rows + 1):
        for c in range(grid_cols + 1):
            s = c / grid_cols
            t = r / grid_rows
            x = -hw + s * surface_width_m
            y = -hh + t * surface_height_m
            pt_local = Vec3(x, y, 0.0)
            pt_world = surface_to_world.apply_point(pt_local)
            pt_proj = world_to_projector.apply_point(pt_world)
            try:
                pixel = intrinsics.project_point(pt_proj)
            except ValueError as exc:
                raise CalibrationToWarpMeshError(
                    f"Grid vertex ({x:.4f}, {y:.4f}) projects behind "
                    f"projector plane: {exc}"
                ) from exc
            uv = intrinsics.pixel_to_uv(pixel)
            projector_uvs_full[idx, 0] = uv[0]
            projector_uvs_full[idx, 1] = uv[1]
            idx += 1

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
