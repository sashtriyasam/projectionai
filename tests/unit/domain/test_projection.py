"""Tests for projection domain model."""

from __future__ import annotations

import pytest

from projectionai.domain.projection import (
    BlendConfig,
    BlendMode,
    CropRegion,
    ProjectionMapping,
)


class TestBlendConfig:
    """Tests for BlendConfig value object."""

    def test_default_values(self) -> None:
        blend = BlendConfig()
        assert blend.left == 0.0
        assert blend.right == 0.0
        assert blend.top == 0.0
        assert blend.bottom == 0.0
        assert blend.mode == BlendMode.ALPHA_BLEND
        assert blend.gamma == 2.2
        assert not blend.has_any_blend

    def test_custom_values(self) -> None:
        blend = BlendConfig(
            left=0.1,
            right=0.2,
            top=0.15,
            bottom=0.05,
            mode=BlendMode.LINEAR,
            gamma=1.8,
        )
        assert blend.left == 0.1
        assert blend.right == 0.2
        assert blend.top == 0.15
        assert blend.bottom == 0.05
        assert blend.mode == BlendMode.LINEAR
        assert blend.gamma == 1.8
        assert blend.has_any_blend

    def test_validation_left_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="left must be in"):
            BlendConfig(left=1.5)
        with pytest.raises(ValueError, match="left must be in"):
            BlendConfig(left=-0.1)

    def test_validation_right_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="right must be in"):
            BlendConfig(right=1.5)

    def test_validation_top_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="top must be in"):
            BlendConfig(top=1.5)

    def test_validation_bottom_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="bottom must be in"):
            BlendConfig(bottom=1.5)

    def test_validation_gamma_positive(self) -> None:
        with pytest.raises(ValueError, match="gamma must be positive"):
            BlendConfig(gamma=0.0)
        with pytest.raises(ValueError, match="gamma must be positive"):
            BlendConfig(gamma=-1.0)

    def test_validation_gamma_type(self) -> None:
        with pytest.raises(TypeError, match="gamma must be a number"):
            BlendConfig(gamma="invalid")  # type: ignore[arg-type]

    def test_edge_blend_values_at_boundaries(self) -> None:
        # Test exact boundaries
        blend = BlendConfig(left=0.0, right=1.0, top=0.0, bottom=1.0)
        assert blend.left == 0.0
        assert blend.right == 1.0
        assert blend.top == 0.0
        assert blend.bottom == 1.0


class TestCropRegion:
    """Tests for CropRegion value object."""

    def test_default_values(self) -> None:
        crop = CropRegion()
        assert crop.x == 0.0
        assert crop.y == 0.0
        assert crop.width == 1.0
        assert crop.height == 1.0
        assert crop.enabled is True
        assert crop.is_full

    def test_custom_values(self) -> None:
        crop = CropRegion(x=0.1, y=0.2, width=0.5, height=0.5, enabled=True)
        assert crop.x == 0.1
        assert crop.y == 0.2
        assert crop.width == 0.5
        assert crop.height == 0.5
        assert crop.enabled is True
        assert not crop.is_full

    def test_disabled_crop_is_full(self) -> None:
        crop = CropRegion(enabled=False)
        assert crop.is_full

    def test_validation_x_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="x must be in"):
            CropRegion(x=1.5)
        with pytest.raises(ValueError, match="x must be in"):
            CropRegion(x=-0.1)

    def test_validation_y_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="y must be in"):
            CropRegion(y=1.5)

    def test_validation_width_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="width must be in"):
            CropRegion(width=1.5)
        with pytest.raises(ValueError, match="width must be in"):
            CropRegion(width=-0.1)

    def test_validation_height_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="height must be in"):
            CropRegion(height=1.5)

    def test_validation_x_plus_width_exceeds_one(self) -> None:
        with pytest.raises(ValueError, match=r"x \+ width must be"):
            CropRegion(x=0.6, width=0.5)

    def test_validation_y_plus_height_exceeds_one(self) -> None:
        with pytest.raises(ValueError, match=r"y \+ height must be"):
            CropRegion(y=0.6, height=0.5)

    def test_to_projector_pixels(self) -> None:
        crop = CropRegion(x=0.1, y=0.2, width=0.5, height=0.5, enabled=True)
        x, y, w, h = crop.to_projector_pixels(1920, 1080)
        assert x == round(0.1 * 1920)
        assert y == round(0.2 * 1080)
        assert w == round(0.5 * 1920)
        assert h == round(0.5 * 1080)

    def test_to_projector_pixels_disabled(self) -> None:
        crop = CropRegion(enabled=False)
        x, y, w, h = crop.to_projector_pixels(1920, 1080)
        assert (x, y, w, h) == (0, 0, 1920, 1080)

    def test_boundary_values(self) -> None:
        # Exact boundaries should work
        crop = CropRegion(x=0.0, y=0.0, width=1.0, height=1.0)
        assert crop.is_full


class TestProjectionMapping:
    """Tests for ProjectionMapping domain object."""

    def test_default_creation(self) -> None:
        mapping = ProjectionMapping()
        assert mapping.id
        assert len(mapping.id) == 12  # uuid4().hex[:12]
        assert mapping.name == "Projection Mapping"
        assert mapping.enabled is True
        assert mapping.projector_id == ""
        assert mapping.surface_id == ""
        assert mapping.calibration_id == ""
        assert mapping.warp_mesh_asset_id == ""
        assert mapping.mask_asset_id == ""
        assert mapping.color_profile == "sRGB"
        assert mapping.brightness == 1.0
        assert mapping.gamma == 2.2
        assert isinstance(mapping.blend, BlendConfig)
        assert isinstance(mapping.crop, CropRegion)

    def test_creation_with_all_fields(self) -> None:
        mapping = ProjectionMapping(
            id="test12345678",
            name="Test Mapping",
            enabled=True,
            projector_id="proj_1",
            surface_id="surf_1",
            calibration_id="calib_1",
            warp_mesh_asset_id="asset_warp_1",
            mask_asset_id="asset_mask_1",
            blend=BlendConfig(left=0.1, right=0.1),
            crop=CropRegion(x=0.0, y=0.0, width=0.8, height=0.8),
            color_profile="rec709",
            brightness=1.2,
            gamma=2.4,
            metadata={"key": "value"},
        )
        assert mapping.id == "test12345678"
        assert mapping.name == "Test Mapping"
        assert mapping.projector_id == "proj_1"
        assert mapping.surface_id == "surf_1"
        assert mapping.calibration_id == "calib_1"
        assert mapping.warp_mesh_asset_id == "asset_warp_1"
        assert mapping.mask_asset_id == "asset_mask_1"
        assert mapping.blend.left == 0.1
        assert mapping.crop.width == 0.8
        assert mapping.color_profile == "rec709"
        assert mapping.brightness == 1.2
        assert mapping.gamma == 2.4
        assert mapping.metadata == {"key": "value"}

    def test_validation_brightness_positive(self) -> None:
        with pytest.raises(ValueError, match="brightness must be positive"):
            ProjectionMapping(brightness=0.0)
        with pytest.raises(ValueError, match="brightness must be positive"):
            ProjectionMapping(brightness=-0.5)

    def test_validation_gamma_positive(self) -> None:
        with pytest.raises(ValueError, match="gamma must be positive"):
            ProjectionMapping(gamma=0.0)
        with pytest.raises(ValueError, match="gamma must be positive"):
            ProjectionMapping(gamma=-1.0)

    def test_to_dict_roundtrip(self) -> None:
        mapping = ProjectionMapping(
            id="test12345678",
            name="Test Mapping",
            enabled=True,
            projector_id="proj_1",
            surface_id="surf_1",
            calibration_id="calib_1",
            warp_mesh_asset_id="asset_warp_1",
            mask_asset_id="asset_mask_1",
            blend=BlendConfig(
                left=0.1, right=0.2, mode=BlendMode.GAMMA_CORRECT, gamma=2.0
            ),
            crop=CropRegion(x=0.1, y=0.1, width=0.8, height=0.8, enabled=True),
            color_profile="rec709",
            brightness=1.2,
            gamma=2.4,
            metadata={"custom": "data"},
        )

        data = mapping.to_dict()
        restored = ProjectionMapping.from_dict(data)

        assert restored.id == mapping.id
        assert restored.name == mapping.name
        assert restored.enabled == mapping.enabled
        assert restored.projector_id == mapping.projector_id
        assert restored.surface_id == mapping.surface_id
        assert restored.calibration_id == mapping.calibration_id
        assert restored.warp_mesh_asset_id == mapping.warp_mesh_asset_id
        assert restored.mask_asset_id == mapping.mask_asset_id
        assert restored.blend.left == mapping.blend.left
        assert restored.blend.right == mapping.blend.right
        assert restored.blend.mode == mapping.blend.mode
        assert restored.blend.gamma == mapping.blend.gamma
        assert restored.crop.x == mapping.crop.x
        assert restored.crop.y == mapping.crop.y
        assert restored.crop.width == mapping.crop.width
        assert restored.crop.height == mapping.crop.height
        assert restored.crop.enabled == mapping.crop.enabled
        assert restored.color_profile == mapping.color_profile
        assert abs(restored.brightness - mapping.brightness) < 1e-6
        assert abs(restored.gamma - mapping.gamma) < 1e-6
        assert restored.metadata == mapping.metadata

    def test_from_dict_with_missing_optional_fields(self) -> None:
        # Test that from_dict handles missing optional fields gracefully
        data = {
            "id": "test12345678",
            "name": "Minimal Mapping",
        }
        mapping = ProjectionMapping.from_dict(data)
        assert mapping.id == "test12345678"
        assert mapping.name == "Minimal Mapping"
        assert mapping.enabled is True
        assert mapping.projector_id == ""
        assert mapping.blend.left == 0.0

    def test_equality(self) -> None:
        mapping1 = ProjectionMapping(
            id="same12345678", name="Test", projector_id="p1", surface_id="s1"
        )
        mapping2 = ProjectionMapping(
            id="same12345678", name="Test", projector_id="p1", surface_id="s1"
        )
        mapping3 = ProjectionMapping(
            id="diff12345678", name="Test", projector_id="p1", surface_id="s1"
        )

        assert mapping1 == mapping2
        assert mapping1 != mapping3
        assert mapping1 != "not a mapping"

    def test_projector_surface_references(self) -> None:
        # Verify that references are stored as IDs, not embedded objects
        mapping = ProjectionMapping(
            projector_id="projector_123",
            surface_id="surface_456",
            calibration_id="calib_789",
            warp_mesh_asset_id="asset_warp",
            mask_asset_id="asset_mask",
        )
        # All references are strings
        assert isinstance(mapping.projector_id, str)
        assert isinstance(mapping.surface_id, str)
        assert isinstance(mapping.calibration_id, str)
        assert isinstance(mapping.warp_mesh_asset_id, str)
        assert isinstance(mapping.mask_asset_id, str)


class TestBlendMode:
    """Tests for BlendMode enum."""

    def test_values(self) -> None:
        assert BlendMode.ALPHA_BLEND.value == "alpha_blend"
        assert BlendMode.LINEAR.value == "linear"
        assert BlendMode.GAMMA_CORRECT.value == "gamma_correct"
        assert BlendMode.CUSTOM.value == "custom"

    def test_from_string(self) -> None:
        assert BlendMode("alpha_blend") == BlendMode.ALPHA_BLEND
        assert BlendMode("linear") == BlendMode.LINEAR


class TestProjectIntegration:
    """Tests for ProjectionMapping integration with Project."""

    def test_project_has_projections_dict(self) -> None:
        from projectionai.domain.project import Project

        project = Project(name="Test")
        assert hasattr(project, "projections")
        assert isinstance(project.projections, dict)

    def test_add_projection(self) -> None:
        from projectionai.domain.project import Project

        project = Project(name="Test")
        mapping = ProjectionMapping(
            name="Mapping 1", projector_id="p1", surface_id="s1"
        )

        project.add_projection(mapping)

        assert mapping.id in project.projections
        assert project.projection_count == 1
        assert project.get_projection(mapping.id) is mapping

    def test_remove_projection(self) -> None:
        from projectionai.domain.project import Project

        project = Project(name="Test")
        mapping = ProjectionMapping(
            name="Mapping 1", projector_id="p1", surface_id="s1"
        )
        project.add_projection(mapping)

        project.remove_projection(mapping.id)

        assert mapping.id not in project.projections
        assert project.projection_count == 0
        assert project.get_projection(mapping.id) is None

    def test_get_projection(self) -> None:
        from projectionai.domain.project import Project

        project = Project(name="Test")
        mapping = ProjectionMapping(
            name="Mapping 1", projector_id="p1", surface_id="s1"
        )
        project.add_projection(mapping)

        found = project.get_projection(mapping.id)
        assert found is mapping

        not_found = project.get_projection("nonexistent")
        assert not_found is None

    def test_projection_modified_touch(self) -> None:
        import time

        from projectionai.domain.project import Project

        project = Project(name="Test")
        mapping = ProjectionMapping(
            name="Mapping 1", projector_id="p1", surface_id="s1"
        )

        old_updated = project.updated_at
        time.sleep(0.001)  # Ensure timestamp difference
        project.add_projection(mapping)

        assert project.updated_at >= old_updated
        assert project.is_dirty


class TestBackwardCompatibility:
    """Tests for backward compatibility with projects without projections."""

    def test_project_without_projections_serializes(self) -> None:

        from projectionai.domain.project import Project

        project = Project(name="Old Project")
        # Simulate an old project without projections field

        # This should not raise
        assert project.projection_count == 0

    def test_read_old_project_format(self) -> None:
        """Test reading a project.json without projections field."""
        import json
        import tempfile
        from pathlib import Path

        from projectionai.infrastructure.persistence.project_format import read_project

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "old.projectai"
            path.mkdir()

            # Old format without projections
            manifest = {
                "id": "test12345678",
                "name": "Old Project",
                "active_scene_id": None,
                "scenes": [],
                "settings": {
                    "resolution_width": 1920,
                    "resolution_height": 1080,
                    "framerate": 30.0,
                    "color_space": "sRGB",
                },
                "metadata": {
                    "author": "",
                    "company": "",
                    "description": "",
                    "application_version": "0.1.0",
                    "project_format_version": "1.0.0",
                    "tags": [],
                },
                "history": [],
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
            (path / "project.json").write_text(json.dumps(manifest))

            project = read_project(path)
            assert project.name == "Old Project"
            assert project.projection_count == 0
