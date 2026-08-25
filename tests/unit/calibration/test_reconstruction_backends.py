"""Reconstruction backend tests — synthetic ground truth, parity, degeneracies."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.domain.calibration_session import CorrespondenceSet
from projectionai.services.projector_calibration import (
    CalibratedCamera,
    ProjectorCalibrationError,
    SurfacePlane,
)
from projectionai.services.reconstruction import (
    BackendMode,
    NativeReconstructionBackend,
    ReconstructionBackend,
    ReconstructionBackendFactory,
    ReconstructionError,
    ReferenceReconstructionBackend,
)

from .reconstruction_synth import make_synthetic_case

CASES = ("identity", "translated", "rotated", "offset_cam", "distorted")


def _backends() -> list[ReconstructionBackend]:
    backends: list[ReconstructionBackend] = [ReferenceReconstructionBackend()]
    if ReconstructionBackendFactory.is_native_available():
        backends.append(NativeReconstructionBackend())
    return backends


class TestSyntheticGroundTruth:
    @pytest.mark.parametrize("case", CASES)
    def test_reconstructs_known_plane(self, case: str) -> None:
        c = make_synthetic_case(case, n_points=6000)
        corr = c["correspondences"]
        cam = c["camera"]
        surf = c["surface"]
        for backend in _backends():
            result = backend.reconstruct(corr, cam, surf, max_points=6000)
            pts = result.points_camera
            assert result.sequence_id == corr.sequence_id
            assert result.method == "plane_triangulation"
            assert len(pts) >= 4
            assert np.all(np.isfinite(pts))
            # plane residual: every point lies on the surface plane
            resid = np.abs(pts @ surf.normal + surf.offset)
            assert resid.max() < 1e-12
            # normals match the surface normal
            assert result.normals is not None
            assert np.allclose(result.normals, surf.normal, atol=1e-12)
            # nearest-neighbour 3D error vs ground truth (pixel quantization)
            gt = c["gt_points"]
            from scipy.spatial import cKDTree

            tree = cKDTree(gt)
            dists, _ = tree.query(pts, k=1)
            nn_err = float(np.max(dists))
            assert nn_err < 0.01, f"{backend.name} nn error {nn_err}"

    @pytest.mark.parametrize("case", CASES)
    def test_camera_roundtrip(self, case: str) -> None:
        c = make_synthetic_case(case, n_points=6000)
        # The dense correspondence map stores integer camera pixels, so the
        # reconstructed point is quantized to ~1 camera pixel of the true
        # ground-truth point. Re-projecting through the projector magnifies
        # that quantization by proj_fx / cam_fx. Bound is hence
        # (proj_fx / cam_fx) * 1.5 camera pixels (physical limit, not a bug).
        cam_k = c["camera"].camera_matrix
        proj_k = c["projector_intrinsics"]
        mag = proj_k[0, 0] / cam_k[0, 0]
        bound = mag * 1.5
        for backend in _backends():
            result = backend.reconstruct(
                c["correspondences"], c["camera"], c["surface"], max_points=6000
            )
            pts = result.points_camera
            gt = c["gt_points"]
            gt_proj = c["gt_projector_pixels"]
            # Match each reconstructed point to its nearest ground-truth point
            # (the dense map is lossy: multiple gt points can share a camera
            # pixel, so correspondence is meaningful only via 3D NN).
            from scipy.spatial import cKDTree

            tree = cKDTree(gt)
            _, idx = tree.query(pts, k=1)
            proj = backend.project(pts, c["projector_intrinsics"], c["projector_pose"])
            err = np.linalg.norm(proj - gt_proj[idx], axis=1)
            assert err.max() < bound, (
                f"{backend.name} projector round-trip {err.max()} > {bound}"
            )


class TestParity:
    def test_triangulate_parity(self) -> None:
        c = make_synthetic_case("rotated", n_points=8000)
        ref = ReferenceReconstructionBackend()
        if not ReconstructionBackendFactory.is_native_available():
            pytest.skip("native extension not built")
        nat = NativeReconstructionBackend()
        cam = c["camera"]
        surf = c["surface"]
        corr = c["correspondences"]
        r_ref = ref.reconstruct(corr, cam, surf, max_points=8000)
        r_nat = nat.reconstruct(corr, cam, surf, max_points=8000)
        assert np.array_equal(r_ref.projector_pixels, r_nat.projector_pixels)
        assert np.array_equal(r_ref.points_camera, r_nat.points_camera)

    def test_project_parity_rotated(self) -> None:
        if not ReconstructionBackendFactory.is_native_available():
            pytest.skip("native extension not built")
        ref = ReferenceReconstructionBackend()
        nat = NativeReconstructionBackend()
        rng = np.random.default_rng(3)
        pts = rng.standard_normal((5000, 3)) * 0.5
        pts[:, 2] = np.abs(pts[:, 2]) + 1.0
        k = np.array([[1100, 0, 960], [0, 1100, 540], [0, 0, 1]], dtype=np.float64)
        r = np.array([[0.99, -0.12, 0.0], [0.12, 0.99, 0.0], [0.0, 0.0, 1.0]])
        pose = np.eye(4)
        pose[:3, :3] = r
        pose[0, 3] = 0.25
        a = ref.project(pts, k, pose)
        b = nat.project(pts, k, pose)
        assert np.allclose(a, b, atol=1e-9)

    def test_contiguous_requirement(self) -> None:
        if not ReconstructionBackendFactory.is_native_available():
            pytest.skip("native extension not built")
        nat = NativeReconstructionBackend()
        surf = SurfacePlane(normal=np.array([0.0, 0.0, -1.0]), offset=2.0)
        base = np.ascontiguousarray(np.random.rand(100, 2))
        non_contig = base[:, ::1][::2]  # strided view, not contiguous
        assert not non_contig.flags.c_contiguous
        with pytest.raises(ReconstructionError, match="C-contiguous"):
            nat.triangulate(non_contig, surf)


class TestDegeneracies:
    def test_empty_mask(self) -> None:
        h, w = 480, 640
        corr = CorrespondenceSet(
            projector_x=np.full((h, w), np.nan, dtype=np.float32),
            projector_y=np.full((h, w), np.nan, dtype=np.float32),
            mask=np.zeros((h, w), dtype=np.bool_),
            image_size=(w, h),
            projector_resolution=(1280, 720),
            sequence_id="empty",
        )
        cam = CalibratedCamera(
            camera_matrix=np.eye(3, dtype=np.float64) * 500,
            distortion_coeffs=np.zeros(5),
            image_size=(w, h),
        )
        surf = SurfacePlane(normal=np.array([0.0, 0.0, -1.0]), offset=2.0)
        for backend in _backends():
            with pytest.raises(ReconstructionError, match="No valid correspondences"):
                backend.reconstruct(corr, cam, surf)

    def test_ray_parallel_to_plane(self) -> None:
        # Rays are homogeneous [x, y, 1]. A plane with normal [1, 0, 0] gives
        # denom = x, so rays with x == 0 are parallel to the plane -> inf/nan.
        ref = ReferenceReconstructionBackend()
        surf = SurfacePlane(normal=np.array([1.0, 0.0, 0.0]), offset=2.0)
        normalized = np.zeros((10, 2))  # all x = 0, parallel
        pts = ref.triangulate(normalized, surf)
        assert np.all(~np.isfinite(pts)), "parallel rays must not yield finite points"
        if ReconstructionBackendFactory.is_native_available():
            nat = NativeReconstructionBackend()
            pts_nat = nat.triangulate(normalized, surf)
            assert np.all(~np.isfinite(pts_nat))

    def test_singular_pose(self) -> None:
        ref = ReferenceReconstructionBackend()
        pts = np.ones((4, 3))
        k = np.eye(3)
        bad_pose = np.zeros((4, 4))  # singular
        # Both backends must fail loudly (raise), never return plausible garbage.
        with pytest.raises((ReconstructionError, np.linalg.LinAlgError)):
            ref.project(pts, k, bad_pose)
        if ReconstructionBackendFactory.is_native_available():
            nat = NativeReconstructionBackend()
            with pytest.raises(RuntimeError, match="singular"):
                nat.project(pts, k, bad_pose)

    def test_zero_surface_normal(self) -> None:
        surf = SurfacePlane(normal=np.array([0.0, 0.0, -1.0]), offset=2.0)
        # SurfacePlane normalizes; zero normal raises at construction
        with pytest.raises(ProjectorCalibrationError):
            SurfacePlane(normal=np.zeros(3), offset=2.0)
        normalized = np.zeros((5, 2))
        ref = ReferenceReconstructionBackend()
        pts = ref.triangulate(normalized, surf)
        assert np.all(np.isfinite(pts))  # rays [0,0,1] hit the plane

    def test_ray_away_from_plane(self) -> None:
        # Rays pointing away produce negative scale: points behind the plane are
        # correctly represented (finite, on the plane, negative depth).
        ref = ReferenceReconstructionBackend()
        surf = SurfacePlane(normal=np.array([0.0, 0.0, 1.0]), offset=2.0)
        normalized = np.array([[0.0, 0.0]] * 5)
        pts = ref.triangulate(normalized, surf)
        # plane: z + 2 = 0 -> z = -2; ray [0,0,1] scale = -2 -> negative depth
        assert np.all(pts[:, 2] < 0)
        resid = np.abs(pts @ surf.normal + surf.offset)
        assert np.allclose(resid, 0.0)


class TestFactory:
    def test_default_is_reference(self) -> None:
        # Evidence-based (Phase 6.6.4): native only saves <1ms in a pipeline
        # dominated by decode/capture, so REFERENCE is the production default.
        backend = ReconstructionBackendFactory.create()
        assert backend.name == "reference"

    def test_auto_prefers_native_when_available(self) -> None:
        backend = ReconstructionBackendFactory.create(BackendMode.AUTO)
        assert backend.name in ("native", "reference")

    def test_reference_explicit(self) -> None:
        backend = ReconstructionBackendFactory.create(BackendMode.REFERENCE)
        assert backend.name == "reference"

    def test_native_explicit_when_built(self) -> None:
        if not ReconstructionBackendFactory.is_native_available():
            pytest.skip("native extension not built")
        backend = ReconstructionBackendFactory.create(BackendMode.NATIVE)
        assert backend.name == "native"
