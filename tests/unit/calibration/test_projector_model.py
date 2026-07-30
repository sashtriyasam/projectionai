"""Tests for projector model."""

from __future__ import annotations

import math

import pytest

from projectionai.calibration.projector_model import (
    ProjectorExtrinsics,
    ProjectorIntrinsics,
    ProjectorLens,
    ProjectorModel,
    ProjectorPose,
)
from projectionai.calibration.types import LensType, Mat4x4, Vec3


class TestProjectorLens:
    def test_defaults(self) -> None:
        lens = ProjectorLens()
        assert lens.lens_type == LensType.STANDARD
        assert lens.throw_ratio == 1.5
        assert lens.lens_shift_x == 0.0

    def test_ultra_short_throw(self) -> None:
        lens = ProjectorLens(lens_type=LensType.ULTRA_SHORT_THROW, throw_ratio=0.25)
        assert lens.lens_type == LensType.ULTRA_SHORT_THROW
        assert lens.throw_ratio == 0.25


class TestProjectorIntrinsics:
    def test_defaults(self) -> None:
        intr = ProjectorIntrinsics()
        assert intr.resolution_x == 1920
        assert intr.resolution_y == 1080
        assert intr.aspect_ratio == 16.0 / 9.0

    def test_vertical_fov_auto(self) -> None:
        intr = ProjectorIntrinsics(horizontal_fov=60.0, aspect_ratio=4.0 / 3.0)
        expected = 2.0 * math.degrees(
            math.atan(math.tan(math.radians(60.0 / 2.0)) / (4.0 / 3.0))
        )
        assert intr.vertical_fov == pytest.approx(expected, abs=1e-10)

    def test_vertical_fov_explicit(self) -> None:
        intr = ProjectorIntrinsics(horizontal_fov=60.0, vertical_fov=40.0)
        assert intr.vertical_fov == 40.0

    def test_matrix_shape(self) -> None:
        intr = ProjectorIntrinsics()
        assert len(intr.matrix) == 12  # 3x4

    def test_custom_resolution(self) -> None:
        intr = ProjectorIntrinsics(resolution_x=3840, resolution_y=2160)
        assert intr.aspect_ratio == 3840.0 / 2160.0


class TestProjectorExtrinsics:
    def test_default_position(self) -> None:
        ext = ProjectorExtrinsics()
        pos = ext.position
        assert pos.x == 0.0
        assert pos.y == 0.0
        assert pos.z == 0.0

    def test_position_from_transform(self) -> None:
        data = (
            1.0,
            0.0,
            0.0,
            2.0,
            0.0,
            1.0,
            0.0,
            3.0,
            0.0,
            0.0,
            1.0,
            4.0,
            0.0,
            0.0,
            0.0,
            1.0,
        )
        ext = ProjectorExtrinsics(transform=Mat4x4(data=data))
        pos = ext.position
        assert pos.x == 2.0
        assert pos.y == 3.0
        assert pos.z == 4.0


class TestProjectorPose:
    def test_defaults(self) -> None:
        pose = ProjectorPose()
        assert pose.enabled
        assert pose.brightness == 1.0

    def test_warp_config(self) -> None:
        pose = ProjectorPose(warp_rows=8, warp_cols=6)
        assert pose.warp_rows == 8
        assert pose.warp_cols == 6

    def test_blend_values(self) -> None:
        pose = ProjectorPose(blend_left=0.1, blend_right=0.1)
        assert pose.blend_left == 0.1
        assert pose.blend_right == 0.1


class TestProjectorModel:
    def test_defaults(self) -> None:
        model = ProjectorModel()
        assert model.name == "Projector"
        assert model.pose_count == 0

    def test_add_and_get_pose(self) -> None:
        model = ProjectorModel()
        pose = ProjectorPose()
        model.add_pose("screen_1", pose)
        assert model.pose_count == 1
        assert model.get_pose("screen_1") is pose

    def test_remove_pose(self) -> None:
        model = ProjectorModel()
        model.add_pose("s1", ProjectorPose())
        model.remove_pose("s1")
        assert model.pose_count == 0

    def test_all_enabled(self) -> None:
        model = ProjectorModel()
        model.add_pose("s1", ProjectorPose(enabled=True))
        model.add_pose("s2", ProjectorPose(enabled=False))
        assert len(model.all_enabled) == 1

    def test_multi_projector(self) -> None:
        model = ProjectorModel()
        model.add_pose("left", ProjectorPose())
        model.add_pose("right", ProjectorPose())
        assert model.pose_count == 2
