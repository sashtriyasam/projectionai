"""Tests for calibration_to_warp_mesh adapter (Phase 5.10).

Covers:
- Task 5: Planar calibration → WarpMesh adapter
- Task 6: Dependency ownership (no infrastructure imports in adapter)
- Task 9: Failure cases (missing projectors, bad dimensions, etc.)
"""

from __future__ import annotations

import ast

import pytest

from projectionai.domain.calibration import CalibrationResult, ProjectorCalibration
from projectionai.domain.geometry import Pose, Vec3
from projectionai.domain.warp_mesh import WarpMeshGeneration
from projectionai.services.calibration import (
    CalibrationToWarpMeshError,
    calibration_to_warp_mesh,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cal(
    *,
    fov: float = 60.0,
    res_x: int = 1920,
    res_y: int = 1080,
    position: tuple[float, float, float] = (0.0, 0.0, 2.0),
    rotation: tuple[float, float, float, float] = (0.0, 1.0, 0.0, 0.0),
    projector_id: str = "proj_0",
    confidence: float = 1.0,
    num_projectors: int = 1,
    has_object_pose: bool = False,
    object_translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    object_rotation: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
) -> CalibrationResult:
    """Build a minimal CalibrationResult for testing."""
    pose = Pose(
        position=Vec3(*position),
        rotation=rotation,
    )
    projectors = tuple(
        ProjectorCalibration(
            projector_id=f"{projector_id}_{i}" if num_projectors > 1 else projector_id,
            pose=pose,
            fov_degrees=fov,
            resolution_width=res_x,
            resolution_height=res_y,
            confidence=confidence,
        )
        for i in range(num_projectors)
    )
    if has_object_pose:
        object_pose = Pose(
            position=Vec3(*object_translation),
            rotation=object_rotation,
        )
    else:
        object_pose = None
    return CalibrationResult(
        projectors=projectors,
        confidence=confidence,
        object_pose=object_pose,
    )


# ===========================================================================
# Task 5: Adapter correctness
# ===========================================================================


class TestCalibrationToWarpMesh:
    """Core adapter functionality."""

    def test_basic_output_shape(self):
        """2x2 grid → 9 vertices, 8 faces."""
        cal = _make_cal()
        mesh = calibration_to_warp_mesh(cal, 1.0, 1.0, grid_rows=2, grid_cols=2)
        assert mesh.num_vertices == 9
        assert mesh.num_faces == 8
        assert mesh.grid_rows == 2
        assert mesh.grid_cols == 2

    def test_grid_subdivisions(self):
        """4x4 grid → 25 vertices, 32 faces."""
        cal = _make_cal()
        mesh = calibration_to_warp_mesh(cal, 1.0, 1.0, grid_rows=4, grid_cols=4)
        assert mesh.num_vertices == 25
        assert mesh.num_faces == 32

    def test_generation_method_is_calibration(self):
        cal = _make_cal()
        mesh = calibration_to_warp_mesh(cal, 1.0, 1.0)
        assert mesh.generation_method == WarpMeshGeneration.CALIBRATION

    def test_metadata_populated(self):
        cal = _make_cal(confidence=0.87)
        mesh = calibration_to_warp_mesh(cal, 1.0, 1.0)
        assert mesh.metadata["source"] == "calibration_to_warp_mesh"
        assert mesh.metadata["calibration_confidence"] == 0.87

    def test_projector_uv_range(self):
        """For a centered projector, UVs should be within [0,1]."""
        cal = _make_cal()
        mesh = calibration_to_warp_mesh(cal, 1.0, 1.0)
        assert float(mesh.projector_uvs.min()) >= -1e-6
        assert float(mesh.projector_uvs.max()) <= 1.0 + 1e-6

    def test_content_uv_range(self):
        """Content UVs should span [0,1]."""
        cal = _make_cal()
        mesh = calibration_to_warp_mesh(cal, 1.0, 1.0)
        assert float(mesh.content_uvs.min()) >= -1e-6
        assert float(mesh.content_uvs.max()) <= 1.0 + 1e-6

    def test_validate_passes(self):
        cal = _make_cal()
        mesh = calibration_to_warp_mesh(cal, 1.0, 1.0)
        assert mesh.validate() == []

    def test_surface_dimensions_propagated(self):
        """Width/height in metres should match vertex extent."""
        cal = _make_cal()
        w, h = 0.5, 0.4
        mesh = calibration_to_warp_mesh(cal, w, h)
        xs = mesh.vertices[:, 0]
        ys = mesh.vertices[:, 1]
        assert abs(xs.max() - xs.min() - w) < 1e-10
        assert abs(ys.max() - ys.min() - h) < 1e-10

    def test_with_object_pose(self):
        """Translated object pose should shift projector UVs vs. no pose."""
        cal_no_pose = _make_cal(has_object_pose=False)
        cal_with_pose = _make_cal(
            has_object_pose=True,
            object_translation=(0.2, 0.1, -0.1),
        )
        mesh1 = calibration_to_warp_mesh(cal_no_pose, 1.0, 1.0)
        mesh2 = calibration_to_warp_mesh(cal_with_pose, 1.0, 1.0)
        # Both should be valid
        assert mesh1.validate() == []
        assert mesh2.validate() == []
        # Projector UVs must differ due to the translated object pose
        import numpy as np

        assert not np.allclose(mesh1.projector_uvs, mesh2.projector_uvs, atol=1e-6), (
            "object pose did not shift projector UVs"
        )

    def test_with_rotation_and_translation(self):
        """Rotation + translation should differ from translation-only and
        from bilinear corner interpolation at an interior mesh vertex."""
        # 45° rotation around Y-axis + translation
        import math

        import numpy as np


        half = math.radians(22.5)
        # Quaternion for 45° around Y: (cos(22.5°), 0, sin(22.5°), 0)
        quat = (math.cos(half), 0.0, math.sin(half), 0.0)
        cal_rotated = _make_cal(
            has_object_pose=True,
            object_translation=(0.1, 0.05, -0.05),
            object_rotation=quat,
        )
        cal_identity = _make_cal(has_object_pose=False)

        mesh_rot = calibration_to_warp_mesh(
            cal_rotated, 1.0, 1.0, grid_rows=4, grid_cols=4
        )
        mesh_id = calibration_to_warp_mesh(
            cal_identity, 1.0, 1.0, grid_rows=4, grid_cols=4
        )
        assert mesh_rot.validate() == []
        assert mesh_id.validate() == []

        # Rotated UVs must differ from identity
        assert not np.allclose(
            mesh_rot.projector_uvs, mesh_id.projector_uvs, atol=1e-6
        ), "rotation did not shift projector UVs"

        # Pick an interior vertex (not a corner) and verify projector UV
        # differs from bilinear interpolation of the four corner UVs.
        # Row-major corners: BL=0, BR=cols, TR=(rows+1)*(cols+1)-1, TL=rows*(cols+1)
        rows, cols = mesh_rot.grid_rows, mesh_rot.grid_cols
        corners = [
            mesh_rot.projector_uvs[0],  # BL
            mesh_rot.projector_uvs[cols],  # BR
            mesh_rot.projector_uvs[(rows + 1) * (cols + 1) - 1],  # TR
            mesh_rot.projector_uvs[rows * (cols + 1)],  # TL
        ]
        # Strictly interior: row 1, col 1
        interior_idx = 1 * (cols + 1) + 1
        interior_uv = mesh_rot.projector_uvs[interior_idx]
        s = 1.0 / cols
        t = 1.0 / rows
        bilinear = (
            (1 - s) * (1 - t) * np.array(corners[0])
            + s * (1 - t) * np.array(corners[1])
            + s * t * np.array(corners[2])
            + (1 - s) * t * np.array(corners[3])
        )
        assert not np.allclose(interior_uv, bilinear, atol=1e-6), (
            "rotated interior UV should differ from bilinear corner interpolation"
        )

    def test_projector_index_selection(self):
        """Selecting projector_index=1 should use the second projector."""
        cal = _make_cal(num_projectors=3)
        mesh0 = calibration_to_warp_mesh(cal, 1.0, 1.0, projector_index=0)
        mesh2 = calibration_to_warp_mesh(cal, 1.0, 1.0, projector_index=2)
        # Different projector IDs
        assert mesh0.projector_id != mesh2.projector_id

    def test_custom_surface_id(self):
        cal = _make_cal()
        mesh = calibration_to_warp_mesh(cal, 1.0, 1.0, surface_id="my_surface")
        assert mesh.surface_id == "my_surface"

    def test_rectangular_surface(self):
        """Non-square surface should produce non-square UV pattern."""
        cal = _make_cal()
        mesh = calibration_to_warp_mesh(cal, 2.0, 1.0, grid_rows=2, grid_cols=4)
        xs = mesh.vertices[:, 0]
        ys = mesh.vertices[:, 1]
        assert abs(xs.max() - xs.min() - 2.0) < 1e-10
        assert abs(ys.max() - ys.min() - 1.0) < 1e-10


# ===========================================================================
# Task 9: Failure cases
# ===========================================================================


class TestCalibrationToWarpMeshFailures:
    """Error handling for invalid inputs."""

    def test_no_projectors_raises(self):
        cal = CalibrationResult(projectors=())
        with pytest.raises(CalibrationToWarpMeshError, match="no projector data"):
            calibration_to_warp_mesh(cal, 1.0, 1.0)

    def test_projector_index_out_of_range(self):
        cal = _make_cal()
        with pytest.raises(CalibrationToWarpMeshError, match="out of range"):
            calibration_to_warp_mesh(cal, 1.0, 1.0, projector_index=5)

    def test_zero_surface_width(self):
        cal = _make_cal()
        with pytest.raises(CalibrationToWarpMeshError, match="positive"):
            calibration_to_warp_mesh(cal, 0.0, 1.0)

    def test_negative_surface_height(self):
        cal = _make_cal()
        with pytest.raises(CalibrationToWarpMeshError, match="positive"):
            calibration_to_warp_mesh(cal, 1.0, -1.0)

    def test_zero_fov(self):
        """Zero FOV → invalid intrinsics."""
        cal = _make_cal(fov=0.0)
        with pytest.raises(CalibrationToWarpMeshError):
            calibration_to_warp_mesh(cal, 1.0, 1.0)

    def test_extremely_narrow_fov(self):
        """Very narrow FOV with wide surface → corners outside [0,1]."""
        cal = _make_cal(fov=1.0)  # 1-degree FOV
        with pytest.raises(CalibrationToWarpMeshError, match="invalid"):
            calibration_to_warp_mesh(cal, 10.0, 10.0)

    def test_projector_behind_surface(self):
        """Projector at negative Z looking away from surface."""
        pose = Pose(
            position=Vec3(0.0, 0.0, -2.0),
            rotation=(0.0, 1.0, 0.0, 0.0),  # Still looking -Z, away from surface
        )
        pc = ProjectorCalibration(
            projector_id="behind",
            pose=pose,
            fov_degrees=60.0,
        )
        cal = CalibrationResult(projectors=(pc,))
        with pytest.raises(CalibrationToWarpMeshError):
            calibration_to_warp_mesh(cal, 1.0, 1.0)


# ===========================================================================
# Task 6: Dependency ownership — adapter has no infrastructure imports
# ===========================================================================


class TestAdapterOwnership:
    """Verify calibration_to_warp_mesh stays in domain/service layer."""

    def test_no_infrastructure_imports_in_module(self):
        """The calibration service module must not import infrastructure."""
        import projectionai.services.calibration as mod

        source = mod.__file__
        assert source is not None
        with open(source) as f:
            tree = ast.parse(f.read())

        bad = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom)
            and n.module
            and "infrastructure" in n.module
        ]
        assert not bad, "calibration.py imports infrastructure: %s" % [
            n.module for n in bad
        ]

    def test_adapter_module_isolation(self):
        """calibration_to_warp_mesh only imports from domain + services."""
        import projectionai.services.calibration as mod

        source = mod.__file__
        assert source is not None
        with open(source) as f:
            tree = ast.parse(f.read())

        # Find the calibration_to_warp_mesh function and check its imports
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "calibration_to_warp_mesh"
            ):
                # Check all ImportFrom nodes inside the function body
                for child in ast.walk(node):
                    if isinstance(child, ast.ImportFrom) and child.module:
                        assert "infrastructure" not in child.module, (
                            f"adapter imports from infrastructure: {child.module}"
                        )
                break
        else:
            pytest.fail("calibration_to_warp_mesh function not found")
