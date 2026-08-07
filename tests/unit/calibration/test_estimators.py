"""Tests for projector calibration estimators."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.infrastructure.projector_calibration.estimators import (
    CameraProjectorTransform,
    CameraProjectorTransformEstimator,
    ProjectorCornerEstimator,
    ProjectorExtrinsicsEstimator,
    ProjectorIntrinsicsEstimator,
    plane_basis,
    project_points,
    sample_correspondences,
    triangulate_plane,
    undistort_points,
)
from projectionai.infrastructure.projector_calibration.gray_code import (
    GrayCodeProjectorCalibration,
)
from projectionai.services.projector_calibration import (
    CorrespondenceMap,
    ProjectorCalibrationError,
    ProjectorCalibrationResult,
)
from tests.unit.calibration._synthetic_scene import (
    SYNTHETIC_CAMERA,
    SYNTHETIC_PLANE,
    SYNTHETIC_PROJECTOR_MATRIX,
    SYNTHETIC_PROJECTOR_RESOLUTION,
    projector_pose_matrix,
    synthetic_captures,
    synthetic_sequence,
)

WIDTH, HEIGHT = SYNTHETIC_PROJECTOR_RESOLUTION
CX, CY = WIDTH / 2.0, HEIGHT / 2.0


@pytest.fixture(scope="module")
def synthetic_correspondences() -> CorrespondenceMap:
    """Decode the synthetic scene once per module."""
    algorithm = GrayCodeProjectorCalibration()
    return algorithm.decode(synthetic_captures(), synthetic_sequence())


def synthetic_plane_data(
    correspondences: CorrespondenceMap,
) -> tuple[np.ndarray, np.ndarray]:
    """Triangulated plane points and observed projector pixels (N, 3)/(N, 2)."""
    camera_pixels, projector_pixels = sample_correspondences(correspondences, 20_000)
    normalized = undistort_points(camera_pixels, SYNTHETIC_CAMERA)
    plane_points = triangulate_plane(normalized, SYNTHETIC_PLANE)
    finite = np.all(np.isfinite(plane_points), axis=1)
    return plane_points[finite], projector_pixels[finite]


def synthetic_transform() -> CameraProjectorTransform:
    return CameraProjectorTransform(
        intrinsics=SYNTHETIC_PROJECTOR_MATRIX.copy(),
        resolution=SYNTHETIC_PROJECTOR_RESOLUTION,
        pose=projector_pose_matrix(),
    )


class TestProjectPoints:
    def test_identity_camera_and_pose(self) -> None:
        intrinsics = np.eye(3, dtype=np.float64)
        pose = np.eye(4, dtype=np.float64)
        pixels = project_points(
            np.array([[2.0, 3.0, 1.0], [4.0, 6.0, 2.0]]), intrinsics, pose
        )
        np.testing.assert_allclose(pixels, [[2.0, 3.0], [2.0, 3.0]], atol=1e-12)

    def test_roundtrip_through_synthetic_transform(self) -> None:
        transform = synthetic_transform()
        pixels = np.array(
            [[0.0, 0.0], [100.0, 200.0], [CX, CY], [WIDTH - 1.0, HEIGHT - 1.0]],
            dtype=np.float64,
        )
        # Rays originate at the projector position, not the camera origin.
        origin = transform.pose[:3, 3]
        rays = transform.unproject_ray(pixels)
        scale = (1500.0 - origin[2]) / rays[:, 2:3]
        points_camera = origin[None, :] + rays * scale
        recovered = transform.project(points_camera)
        np.testing.assert_allclose(recovered, pixels, atol=1e-6)

    def test_returns_two_columns(self) -> None:
        intrinsics = np.eye(3, dtype=np.float64)
        pose = np.eye(4, dtype=np.float64)
        pixels = project_points(np.zeros((7, 3)), intrinsics, pose)
        assert pixels.shape == (7, 2)


class TestAlgorithmProjectPoints:
    """Service-level project_points must match the estimator projection."""

    def test_matches_estimator_projection(self) -> None:
        algorithm = GrayCodeProjectorCalibration()
        intrinsics = SYNTHETIC_PROJECTOR_MATRIX.copy()
        pose = projector_pose_matrix()
        result = ProjectorCalibrationResult(
            projector_intrinsics=intrinsics,
            projector_resolution=SYNTHETIC_PROJECTOR_RESOLUTION,
            projector_pose=pose,
            reprojection_error=0.0,
            num_correspondences=1,
            coverage=1.0,
            confidence=1.0,
            per_point_errors=(),
            camera_matrix=SYNTHETIC_CAMERA.camera_matrix.copy(),
            distortion_coeffs=SYNTHETIC_CAMERA.distortion_coeffs.copy(),
            image_size=SYNTHETIC_CAMERA.image_size,
        )
        points = np.array(
            [[0.0, 0.0, 1500.0], [100.0, 200.0, 1600.0], [-50.0, 30.0, 1400.0]],
            dtype=np.float64,
        )
        expected = project_points(points, intrinsics, pose)
        actual = algorithm.project_points(points, result)
        np.testing.assert_allclose(actual, expected, atol=1e-9)
        assert actual.shape == (3, 2)


class TestUndistortPoints:
    def test_center_pixel_maps_to_origin(self) -> None:
        result = undistort_points(np.array([[640.0, 360.0]]), SYNTHETIC_CAMERA)
        np.testing.assert_allclose(result, [[0.0, 0.0]], atol=1e-9)

    def test_focal_length_scaling(self) -> None:
        result = undistort_points(np.array([[640.0 + 4500.0, 360.0]]), SYNTHETIC_CAMERA)
        np.testing.assert_allclose(result, [[1.0, 0.0]], atol=1e-9)

    def test_empty_input_returns_empty(self) -> None:
        result = undistort_points(np.zeros((0, 2)), SYNTHETIC_CAMERA)
        assert result.shape == (0, 2)


class TestTriangulatePlane:
    def test_ray_through_origin_hits_plane_at_origin(self) -> None:
        points = triangulate_plane(np.array([[0.0, 0.0]]), SYNTHETIC_PLANE)
        np.testing.assert_allclose(points, [[0.0, 0.0, 1500.0]], atol=1e-9)

    def test_offset_ray_scales_with_direction(self) -> None:
        points = triangulate_plane(np.array([[1.0, 0.0]]), SYNTHETIC_PLANE)
        np.testing.assert_allclose(points, [[1500.0, 0.0, 1500.0]], atol=1e-9)

    def test_ray_parallel_to_plane_is_non_finite(self) -> None:
        from projectionai.services.projector_calibration import SurfacePlane

        side_plane = SurfacePlane(normal=np.array([1.0, 0.0, 0.0]), offset=-1000.0)
        # Ray (0, 0, 1) is parallel to the plane x = 1000 -> scale = inf.
        points = triangulate_plane(np.array([[0.0, 0.0]]), side_plane)
        assert not np.all(np.isfinite(points))
        # Ray (1, 0, 1) hits at x = 1000.
        hit = triangulate_plane(np.array([[1.0, 0.0]]), side_plane)
        np.testing.assert_allclose(hit, [[1000.0, 0.0, 1000.0]], atol=1e-9)


class TestPlaneBasis:
    def test_returns_orthonormal_basis_spanning_plane(
        self, synthetic_correspondences: CorrespondenceMap
    ) -> None:
        plane_points, _ = synthetic_plane_data(synthetic_correspondences)
        centroid, u_axis, v_axis = plane_basis(plane_points)
        np.testing.assert_allclose(centroid, plane_points.mean(axis=0))
        assert abs(float(np.dot(u_axis, v_axis))) < 1e-9
        assert abs(float(np.linalg.norm(u_axis)) - 1.0) < 1e-9
        assert abs(float(np.linalg.norm(v_axis)) - 1.0) < 1e-9

        # Points are coplanar, so (points - centroid) lie in span(u, v).
        offsets = plane_points - centroid
        residual = offsets - (offsets @ u_axis)[:, None] * u_axis
        residual -= (offsets @ v_axis)[:, None] * v_axis
        assert np.abs(residual).max() < 1e-6

        # The basis normal matches the plane normal (up to sign).
        normal = np.cross(u_axis, v_axis)
        assert abs(abs(float(np.dot(normal, SYNTHETIC_PLANE.normal))) - 1.0) < 1e-6


class TestSampleCorrespondences:
    def test_caps_at_max_points(
        self, synthetic_correspondences: CorrespondenceMap
    ) -> None:
        camera_pixels, projector_pixels = sample_correspondences(
            synthetic_correspondences, 1000
        )
        assert camera_pixels.shape == (1000, 2)
        assert projector_pixels.shape == (1000, 2)
        assert np.all(np.isfinite(camera_pixels))
        assert np.all(np.isfinite(projector_pixels))

    def test_returns_all_when_max_exceeds_count(
        self, synthetic_correspondences: CorrespondenceMap
    ) -> None:
        count = synthetic_correspondences.num_correspondences
        camera_pixels, _ = sample_correspondences(
            synthetic_correspondences, count + 100
        )
        assert len(camera_pixels) == count

    def test_pixels_are_in_bounds(
        self, synthetic_correspondences: CorrespondenceMap
    ) -> None:
        _, projector_pixels = sample_correspondences(synthetic_correspondences, 10_000)
        assert np.all(projector_pixels[:, 0] >= 0)
        assert np.all(projector_pixels[:, 0] < WIDTH)
        assert np.all(projector_pixels[:, 1] >= 0)
        assert np.all(projector_pixels[:, 1] < HEIGHT)


class TestProjectorIntrinsicsEstimator:
    def test_recovers_focal_lengths_and_center(
        self, synthetic_correspondences: CorrespondenceMap
    ) -> None:
        plane_points, projector_pixels = synthetic_plane_data(synthetic_correspondences)
        intrinsics = ProjectorIntrinsicsEstimator().estimate(
            plane_points, projector_pixels, SYNTHETIC_PROJECTOR_RESOLUTION
        )
        assert intrinsics[0, 0] == pytest.approx(2000.0, rel=0.01)
        assert intrinsics[1, 1] == pytest.approx(2000.0, rel=0.01)
        assert intrinsics[0, 2] == CX
        assert intrinsics[1, 2] == CY
        assert intrinsics[2, 2] == 1.0
        assert intrinsics[0, 1] == 0.0
        assert intrinsics[1, 0] == 0.0

    def test_rejects_too_few_points(self) -> None:
        with pytest.raises(ProjectorCalibrationError, match="at least"):
            ProjectorIntrinsicsEstimator().estimate(
                np.zeros((3, 3)), np.zeros((3, 2)), SYNTHETIC_PROJECTOR_RESOLUTION
            )


class TestProjectorExtrinsicsEstimator:
    def test_recovers_ground_truth_pose(
        self, synthetic_correspondences: CorrespondenceMap
    ) -> None:
        plane_points, projector_pixels = synthetic_plane_data(synthetic_correspondences)
        intrinsics = SYNTHETIC_PROJECTOR_MATRIX
        pose = ProjectorExtrinsicsEstimator().estimate(
            plane_points, projector_pixels, intrinsics
        )
        truth = projector_pose_matrix()
        assert np.abs(pose - truth).max() < 0.5

    def test_rejects_too_few_points(self) -> None:
        with pytest.raises(ProjectorCalibrationError, match="at least"):
            ProjectorExtrinsicsEstimator().estimate(
                np.zeros((3, 3)),
                np.zeros((3, 2)),
                SYNTHETIC_PROJECTOR_MATRIX,
            )


class TestCameraProjectorTransformEstimator:
    def test_recovers_full_transform(
        self, synthetic_correspondences: CorrespondenceMap
    ) -> None:
        transform = CameraProjectorTransformEstimator().estimate(
            synthetic_correspondences,
            SYNTHETIC_CAMERA,
            SYNTHETIC_PLANE,
            SYNTHETIC_PROJECTOR_RESOLUTION,
        )
        assert transform.resolution == SYNTHETIC_PROJECTOR_RESOLUTION
        assert transform.intrinsics[0, 0] == pytest.approx(2000.0, rel=0.01)
        assert transform.intrinsics[1, 1] == pytest.approx(2000.0, rel=0.01)
        assert np.abs(transform.pose - projector_pose_matrix()).max() < 0.5

    def test_rejects_sparse_correspondences(self) -> None:
        sparse = CorrespondenceMap(
            projector_x=np.full((720, 1280), np.nan, dtype=np.float32),
            projector_y=np.full((720, 1280), np.nan, dtype=np.float32),
            mask=np.zeros((720, 1280), dtype=np.bool_),
            image_size=(WIDTH, HEIGHT),
        )
        mask = sparse.mask
        mask[100, 100] = True
        mask[200, 200] = True
        with pytest.raises(ProjectorCalibrationError, match="after sampling"):
            CameraProjectorTransformEstimator().estimate(
                sparse,
                SYNTHETIC_CAMERA,
                SYNTHETIC_PLANE,
                SYNTHETIC_PROJECTOR_RESOLUTION,
            )


class TestCameraProjectorTransform:
    def test_transform_camera_to_projector_is_inverse_of_pose(self) -> None:
        transform = synthetic_transform()
        np.testing.assert_allclose(
            transform.transform_camera_to_projector, np.linalg.inv(transform.pose)
        )

    def test_project_delegates_to_project_points(self) -> None:
        transform = synthetic_transform()
        points = np.array([[0.0, 0.0, 1500.0], [100.0, -50.0, 1500.0]])
        np.testing.assert_allclose(
            transform.project(points),
            project_points(points, transform.intrinsics, transform.pose),
        )

    def test_unproject_ray_returns_unit_vectors(self) -> None:
        transform = synthetic_transform()
        pixels = np.array([[0.0, 0.0], [CX, CY], [WIDTH - 1.0, HEIGHT - 1.0]])
        rays = transform.unproject_ray(pixels)
        assert rays.shape == (3, 3)
        np.testing.assert_allclose(np.linalg.norm(rays, axis=1), 1.0)

    def test_center_ray_follows_pose_axis(self) -> None:
        transform = synthetic_transform()
        rays = transform.unproject_ray(np.array([[CX, CY]]))
        expected = transform.pose[:3, :3] @ np.array([0.0, 0.0, 1.0])
        np.testing.assert_allclose(rays[0], expected, atol=1e-12)


class TestProjectorCornerEstimator:
    def test_projects_plane_corners_into_bounds(self) -> None:
        transform = synthetic_transform()
        corners = np.array(
            [
                [-700.0, -350.0, 1500.0],
                [700.0, -350.0, 1500.0],
                [700.0, 350.0, 1500.0],
                [-700.0, 350.0, 1500.0],
            ]
        )
        pixels = ProjectorCornerEstimator().estimate(corners, transform)
        assert pixels.shape == (4, 2)
        assert np.all(np.isfinite(pixels))

    def test_rejects_non_point_cloud_input(self) -> None:
        transform = synthetic_transform()
        with pytest.raises(ProjectorCalibrationError, match="shape"):
            ProjectorCornerEstimator().estimate(np.array([0.0, 0.0, 1500.0]), transform)

    def test_rejects_points_on_projector_focal_plane(self) -> None:
        # Identity pose puts the projector at the camera origin: a point at
        # the projector's own position lies on its focal plane and divides
        # by zero -> non-finite pixels. (The synthetic pose would only
        # approximate this due to inv() roundoff.)
        transform = CameraProjectorTransform(
            intrinsics=SYNTHETIC_PROJECTOR_MATRIX,
            resolution=SYNTHETIC_PROJECTOR_RESOLUTION,
            pose=np.eye(4),
        )
        with pytest.raises(ProjectorCalibrationError, match="non-finite"):
            ProjectorCornerEstimator().estimate(np.array([[0.0, 0.0, 0.0]]), transform)
