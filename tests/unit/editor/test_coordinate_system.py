"""Tests for CoordinateSystem — world/local space management."""

from __future__ import annotations

import numpy as np

from projectionai.domain.geometry import Pose, Vec3
from projectionai.editor.coordinate_system import CoordinateSystem
from projectionai.editor.types import TransformSpace


def test_default_is_world() -> None:
    cs = CoordinateSystem()
    assert cs.space == TransformSpace.WORLD
    assert cs.is_world
    assert not cs.is_local


def test_set_local() -> None:
    cs = CoordinateSystem()
    cs.space = TransformSpace.LOCAL
    assert cs.is_local
    assert not cs.is_world


def test_toggle() -> None:
    cs = CoordinateSystem()
    cs.toggle()
    assert cs.is_local
    cs.toggle()
    assert cs.is_world


def test_world_orientation() -> None:
    cs = CoordinateSystem()
    pose = Pose()
    orient = cs.get_orientation(pose)
    assert orient.shape == (3, 3)
    np.testing.assert_array_almost_equal(orient, np.eye(3))


def test_local_orientation() -> None:
    cs = CoordinateSystem()
    cs.space = TransformSpace.LOCAL
    # Identity pose — local rotation is identity
    pose = Pose()
    orient = cs.get_orientation(pose)
    assert orient.shape == (3, 3)
    np.testing.assert_array_almost_equal(orient, np.eye(3))


def test_local_orientation_with_rotation() -> None:
    cs = CoordinateSystem()
    cs.space = TransformSpace.LOCAL
    # 90-degree rotation around Y
    rot = (0.7071068, 0.0, 0.7071068, 0.0)  # w, x, y, z
    pose = Pose(rotation=rot)
    orient = cs.get_orientation(pose)
    assert orient.shape == (3, 3)
    # 90-degree rotation around Y → rotated basis
    expected = np.array(
        [
            [0.0, 0.0, 1.0],
            [0.0, 1.0, 0.0],
            [-1.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    np.testing.assert_array_almost_equal(orient, expected, decimal=5)


def test_world_orientation_ignores_pose() -> None:
    cs = CoordinateSystem()
    pose = Pose(rotation=(0.7071068, 0.0, 0.7071068, 0.0))
    orient = cs.get_orientation(pose)
    np.testing.assert_array_almost_equal(orient, np.eye(3))


def test_world_to_local() -> None:
    cs = CoordinateSystem()
    # Identity pose — world and local are the same
    pose = Pose()
    world = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    local = cs.world_to_local(world, pose)
    np.testing.assert_array_almost_equal(local, world)


def test_local_to_world_roundtrip() -> None:
    cs = CoordinateSystem()
    # 90-degree rotation around Y + non-zero translation
    rot = (0.7071068, 0.0, 0.7071068, 0.0)  # w, x, y, z
    pose = Pose(rotation=rot, position=Vec3(x=10.0, y=20.0, z=30.0))
    local = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    world = cs.local_to_world(local, pose)
    # Apply the 90-degree Y rotation: R @ [1, 2, 3] = [3, 2, -1]
    expected_world = np.array([3.0, 2.0, -1.0], dtype=np.float64)
    np.testing.assert_array_almost_equal(world, expected_world)
    restored = cs.world_to_local(world, pose)
    # Round-trip should return the original local vector
    np.testing.assert_array_almost_equal(restored, local)


def test_repr() -> None:
    cs = CoordinateSystem()
    assert "WORLD" in repr(cs)
    cs.toggle()
    assert "LOCAL" in repr(cs)
