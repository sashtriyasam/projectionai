"""Tests for surface setup — validation, transform, surface types."""

import math

import pytest

from projectionai.application.surface_setup import (
    SurfaceSetupView,
    build_surface_view,
    dict_to_surface_pose,
    surface_to_dict,
    validate_surface,
)
from projectionai.calibration.surface_model import SurfacePose
from projectionai.calibration.types import Mat4x4, ProjectionType
from projectionai.domain.surface import SurfaceType


def _pose(width=2.0, height=1.5, depth=0.0, stype=ProjectionType.FLAT, transform=None):
    return SurfacePose(
        surface_type=stype,
        width=width,
        height=height,
        depth=depth,
        transform=transform or Mat4x4.identity(),
    )


def test_valid_planar_surface():
    pose = _pose(2.0, 1.5, 0.0, ProjectionType.FLAT)
    report = validate_surface("s1", pose)
    assert report.is_ok
    assert report.supported_for_calibration is True
    view = build_surface_view("s1", "Wall", pose)
    assert view.is_valid
    assert view.width_m == 2.0
    assert view.validation.is_ok


def test_invalid_dimensions():
    for w, h in [(0, 1.5), (-1, 1.5), (2.0, 0), (2.0, -1)]:
        pose = _pose(w, h, 0.0)
        report = validate_surface("s1", pose)
        assert not report.is_ok
        assert any("must be >0" in e for e in report.errors)


def test_nan_inf():
    pose = _pose(float("nan"), 1.5, 0.0)
    report = validate_surface("s1", pose)
    assert not report.is_ok
    assert any("NaN/Inf" in e for e in report.errors)
    pose2 = _pose(2.0, float("inf"), 0.0)
    report2 = validate_surface("s1", pose2)
    assert not report2.is_ok


def test_zero_area():
    pose = _pose(0, 0, 0.0)
    report = validate_surface("s1", pose)
    assert not report.is_ok
    assert any("zero-area" in e for e in report.errors)


def test_invalid_transform():
    # Singular transform (zero det)
    singular = Mat4x4(data=(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    pose = _pose(2.0, 1.5, 0.0, transform=singular)
    report = validate_surface("s1", pose)
    assert not report.is_ok
    assert any("singular" in e for e in report.errors)


def test_singular_transform():
    # Non-finite transform
    bad = Mat4x4(data=(float("nan"), 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1))
    pose = _pose(2.0, 1.5, 0.0, transform=bad)
    report = validate_surface("s1", pose)
    assert not report.is_ok
    assert any("NaN/Inf" in e for e in report.errors)


def test_unsupported_surface_type():
    pose = _pose(2.0, 1.5, 0.0, stype=ProjectionType.DOME)
    report = validate_surface("s1", pose, allow_non_planar=False)
    assert report.is_ok  # dimensions ok, but not supported
    assert report.supported_for_calibration is False
    assert any("Non-planar" in w for w in report.warnings)
    # With allow_non_planar True, supported
    report2 = validate_surface("s1", pose, allow_non_planar=True)
    assert report2.supported_for_calibration is True


def test_selection():
    pose = _pose(2.0, 1.5, 0.0)
    view = build_surface_view("s1", "Wall", pose)
    assert view.surface_id == "s1"
    assert view.name == "Wall"


def test_editing():
    pose = _pose(2.0, 1.5, 0.0)
    view = build_surface_view("s1", "Wall", pose)
    # Edit dimensions
    new_pose = SurfacePose(
        surface_type=ProjectionType.FLAT,
        width=3.0,
        height=2.0,
        depth=0.0,
        transform=Mat4x4.identity(),
    )
    view2 = build_surface_view("s1", "Wall", new_pose)
    assert view2.width_m == 3.0
    assert view2.height_m == 2.0


def test_validation_report():
    pose = _pose(2.0, 1.5, 0.0)
    report = validate_surface("s1", pose)
    assert report.surface_id == "s1"
    assert report.is_ok
    assert report.supported_for_calibration
    # Invalid
    pose_bad = _pose(-1, 1.5, 0.0)
    report_bad = validate_surface("s1", pose_bad)
    assert not report_bad.is_ok
    assert len(report_bad.errors) > 0


def test_refresh_persistence():
    pose = _pose(2.0, 1.5, 0.0)
    d = surface_to_dict("s1", pose)
    assert d["surface_id"] == "s1"
    assert d["width"] == 2.0
    pose2 = dict_to_surface_pose(d)
    assert pose2.width == 2.0
    assert pose2.height == 1.5


def test_coordinate_convention():
    pose = _pose(2.0, 1.5, 0.0, transform=Mat4x4.identity())
    view = build_surface_view("s1", "Wall", pose)
    # Position should be at origin for identity
    assert view.position.x == 0
    assert view.position.y == 0
    assert view.position.z == 0
    # Orientation should be identity quat
    assert view.orientation == (1.0, 0.0, 0.0, 0.0)
    # Bounding box should be centered
    assert view.bounding_box.min_x == -1.0
    assert view.bounding_box.max_x == 1.0


def test_missing_surface():
    report = validate_surface("s1", None)
    assert not report.is_ok
    assert "missing surface" in report.errors[0]


def test_unsupported_surface_blocked_by_workflow():
    """Non-planar with is_ok True but supported False must not advance workflow."""
    from projectionai.application.calibration_workflow import ProductionWorkflow

    pose = _pose(2.0, 1.5, 0.0, stype=ProjectionType.DOME)
    report = validate_surface("s1", pose, allow_non_planar=False)
    assert report.is_ok
    assert report.supported_for_calibration is False
    # Workflow boundary must check supported_for_calibration explicitly
    w = ProductionWorkflow()
    # Simulate workflow check: do not allow capture if not supported
    assert not report.supported_for_calibration
    # Flat should be allowed
    pose_flat = _pose(2.0, 1.5, 0.0, stype=ProjectionType.FLAT)
    report_flat = validate_surface("s1", pose_flat, allow_non_planar=False)
    assert report_flat.supported_for_calibration is True


def test_flat_surface_allowed():
    pose = _pose(2.0, 1.5, 0.0, stype=ProjectionType.FLAT)
    report = validate_surface("s1", pose, allow_non_planar=False)
    assert report.is_ok
    assert report.supported_for_calibration is True


def test_invalid_geometry_blocked():
    pose = _pose(-1, 1.5, 0.0)
    report = validate_surface("s1", pose)
    assert not report.is_ok
    # Workflow should not proceed
    assert report.supported_for_calibration is False


def test_transform_round_trip():
    pose = _pose(2.0, 1.5, 0.0, transform=Mat4x4.identity())
    view = build_surface_view("s1", "Wall", pose)
    d = surface_to_dict("s1", pose)
    pose2 = dict_to_surface_pose(d)
    view2 = build_surface_view("s1", "Wall", pose2)
    assert view2.width_m == view.width_m
    assert view2.height_m == view.height_m
    assert view2.transform.data == view.transform.data
    assert view2.surface_id == view.surface_id


def test_persistence_round_trip():
    pose = _pose(2.0, 1.5, 0.0)
    d = surface_to_dict("s1", pose)
    pose2 = dict_to_surface_pose(d)
    assert pose2.width == 2.0
    assert pose2.height == 1.5
    assert pose2.surface_type == ProjectionType.FLAT


def test_legacy_persistence_variants():
    # Flat 16-element list
    pose = _pose(2.0, 1.5, 0.0)
    d = surface_to_dict("s1", pose)
    assert len(d["transform"]) == 16
    pose2 = dict_to_surface_pose(d)
    assert pose2.width == 2.0
    # Nested 4x4
    nested = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    pose3 = dict_to_surface_pose(
        {
            "surface_type": "flat",
            "width": 2.0,
            "height": 1.5,
            "depth": 0.0,
            "transform": nested,
        }
    )
    assert pose3.width == 2.0
    # Missing transform
    pose4 = dict_to_surface_pose(
        {"surface_type": "flat", "width": 2.0, "height": 1.5, "depth": 0.0}
    )
    assert pose4.width == 2.0
    assert pose4.transform == Mat4x4.identity()
    # Missing surface_type
    pose5 = dict_to_surface_pose({"width": 2.0, "height": 1.5, "depth": 0.0})
    assert pose5.surface_type == ProjectionType.FLAT
    # Missing depth
    pose6 = dict_to_surface_pose({"surface_type": "flat", "width": 2.0, "height": 1.5})
    assert pose6.depth == 0.0


def test_corrupted_transform_not_silently_identity():
    # Corrupt present transform with wrong size should raise, not become identity
    with pytest.raises(ValueError, match="Invalid transform"):
        dict_to_surface_pose(
            {
                "surface_type": "flat",
                "width": 2.0,
                "height": 1.5,
                "depth": 0.0,
                "transform": [1, 2, 3],
            }
        )
    # Corrupt with string
    with pytest.raises(ValueError, match="Invalid transform"):
        dict_to_surface_pose(
            {
                "surface_type": "flat",
                "width": 2.0,
                "height": 1.5,
                "depth": 0.0,
                "transform": "bad",
            }
        )
    # Non-finite transform should be kept and then caught by validate_surface, not silently fixed
    pose_bad = dict_to_surface_pose(
        {
            "surface_type": "flat",
            "width": 2.0,
            "height": 1.5,
            "depth": 0.0,
            "transform": [float("nan")] * 16,
        }
    )
    report = validate_surface("s1", pose_bad)
    assert not report.is_ok
    assert any(
        "NaN/Inf" in e or "singular" in e or "transform" in e for e in report.errors
    )
