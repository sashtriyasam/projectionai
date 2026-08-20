"""Tests for non-GPU renderer modules.

All tests in this file operate without a ModernGL context — they verify
math, data structures, and invariants.
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from projectionai.infrastructure.renderer.camera import (
    MouseButton,
    OrbitCamera,
    OrthographicCamera,
    PerspectiveCamera,
)
from projectionai.infrastructure.renderer.mesh import Mesh
from projectionai.infrastructure.renderer.pipeline import RenderPipeline
from projectionai.infrastructure.renderer.pipeline_pass import RenderPass
from projectionai.infrastructure.renderer.render_target import ScreenTarget
from projectionai.infrastructure.renderer.settings import RendererSettings
from projectionai.infrastructure.renderer.statistics import (
    FrameMetrics,
    RenderStatistics,
)

# ---------------------------------------------------------------------------
# Helper: concrete RenderPass stub for testing
# ---------------------------------------------------------------------------


class _StubPass(RenderPass):
    """Concrete pass that tracks lifecycle calls."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.setup_called = False
        self.render_called = False
        self.release_called = False
        self.resize_called = False
        self.last_ctx: Any = None
        self.last_width = 0
        self.last_height = 0

    def setup(self, ctx: Any, width: int, height: int) -> None:
        self.setup_called = True
        self.last_ctx = ctx
        self.last_width = width
        self.last_height = height

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        self.render_called = True
        self.last_ctx = ctx

    def release(self) -> None:
        super().release()
        self.release_called = True

    def resize(self, ctx: Any, width: int, height: int) -> None:
        super().resize(ctx, width, height)
        self.resize_called = True


# ===========================================================================
# Settings
# ===========================================================================


class TestRendererSettings:
    def test_defaults(self) -> None:
        s = RendererSettings()
        assert s.width == 1280
        assert s.height == 720
        assert s.near_plane == 0.01
        assert s.far_plane == 1000.0
        assert s.vsync is True

    def test_custom_values(self) -> None:
        s = RendererSettings(width=800, height=600, near_plane=0.1, far_plane=500.0)
        assert s.width == 800
        assert s.height == 600
        assert s.near_plane == 0.1
        assert s.far_plane == 500.0

    def test_mutable(self) -> None:
        s = RendererSettings()
        s.width = 1024
        assert s.width == 1024

    def test_effective_width_scaling(self) -> None:
        s = RendererSettings(width=1920, height=1080, resolution_scale=0.5)
        assert s.effective_width == 960
        assert s.effective_height == 540

    def test_msaa_validation(self) -> None:
        s = RendererSettings(msaa_samples=3)  # invalid — should clamp to 4
        assert s.msaa_samples == 4


# ===========================================================================
# Statistics
# ===========================================================================


class TestRenderStatistics:
    def test_initial_state(self) -> None:
        stats = RenderStatistics()
        assert stats.fps == 0.0
        assert stats.frame_time_ms == 0.0
        assert stats.total_frames == 0
        assert stats.average_frame_time_ms() == 0.0

    def test_begin_end_frame(self) -> None:
        stats = RenderStatistics()
        stats.begin_frame()
        stats.end_frame()
        assert stats.total_frames == 1

    def test_multiple_frames(self) -> None:
        stats = RenderStatistics()
        for _ in range(10):
            stats.begin_frame()
            stats.end_frame()
        assert stats.total_frames == 10

    def test_frame_time_recorded(self) -> None:
        stats = RenderStatistics()
        stats.begin_frame()
        stats.end_frame()
        assert stats.frame_time_ms >= 0

    def test_frame_metrics_defaults(self) -> None:
        m = FrameMetrics()
        assert m.frame_time_ms == 0.0
        assert m.gpu_time_ms == 0.0
        assert m.draw_calls == 0
        assert m.triangles == 0
        assert m.vertices == 0
        assert m.passes_executed == 0

    def test_average_frame_time(self) -> None:
        stats = RenderStatistics()
        for _ in range(3):
            stats.begin_frame()
            stats.end_frame()
        avg = stats.average_frame_time_ms()
        assert avg >= 0

    def test_peak_frame_time(self) -> None:
        stats = RenderStatistics()
        for _ in range(3):
            stats.begin_frame()
            stats.end_frame()
        peak = stats.peak_frame_time_ms()
        assert peak >= 0

    def test_collect_returns_current_metrics(self) -> None:
        stats = RenderStatistics()
        stats.begin_frame()
        metrics = stats.collect()
        assert isinstance(metrics, FrameMetrics)

    def test_gpu_memory_estimate_is_string(self) -> None:
        result = RenderStatistics.estimate_gpu_memory()
        assert isinstance(result, str)


# ===========================================================================
# Camera — PerspectiveCamera
# ===========================================================================


class TestPerspectiveCamera:
    def test_default_construction(self) -> None:
        cam = PerspectiveCamera()
        assert cam.fov_degrees == pytest.approx(60.0)
        assert cam.aspect_ratio == pytest.approx(16.0 / 9.0)
        assert cam.near == 0.01
        assert cam.far == 1000.0

    def test_custom_construction(self) -> None:
        cam = PerspectiveCamera(fov_degrees=90.0, aspect_ratio=4.0 / 3.0)
        assert cam.fov_degrees == pytest.approx(90.0)
        assert cam.aspect_ratio == pytest.approx(4.0 / 3.0)

    def test_projection_matrix_shape(self) -> None:
        cam = PerspectiveCamera()
        p = cam.projection_matrix
        assert p.shape == (4, 4)

    def test_projection_matrix_is_ndarray(self) -> None:
        cam = PerspectiveCamera()
        assert isinstance(cam.projection_matrix, np.ndarray)

    def test_aspect_ratio_setter(self) -> None:
        cam = PerspectiveCamera()
        cam.aspect_ratio = 2.0
        assert cam.aspect_ratio == pytest.approx(2.0)

    def test_fov_setter(self) -> None:
        cam = PerspectiveCamera()
        cam.fov_degrees = 120.0
        assert cam.fov_degrees == pytest.approx(120.0)


# ===========================================================================
# Camera — OrthographicCamera
# ===========================================================================


class TestOrthographicCamera:
    def test_default_construction(self) -> None:
        cam = OrthographicCamera()
        assert cam.near == 0.01
        assert cam.far == 1000.0

    def test_custom_construction(self) -> None:
        cam = OrthographicCamera(left=-5, right=5, bottom=-5, top=5)
        p = cam.projection_matrix
        assert p.shape == (4, 4)
        assert isinstance(p, np.ndarray)

    def test_projection_matrix_shape(self) -> None:
        cam = OrthographicCamera()
        assert cam.projection_matrix.shape == (4, 4)

    def test_left_right_bottom_top_setters(self) -> None:
        cam = OrthographicCamera()
        cam.left = -10
        cam.right = 10
        cam.bottom = -10
        cam.top = 10
        assert cam.left == -10
        assert cam.right == 10


# ===========================================================================
# Camera — base Camera
# ===========================================================================


class TestCameraBase:
    def test_position_default(self) -> None:
        cam = PerspectiveCamera()
        pos = cam.position
        assert pos.shape == (3,)

    def test_target_default(self) -> None:
        cam = PerspectiveCamera()
        target = cam.target
        assert target.shape == (3,)

    def test_view_matrix_shape(self) -> None:
        cam = PerspectiveCamera()
        v = cam.view_matrix
        assert v.shape == (4, 4)

    def test_view_projection_matrix_shape(self) -> None:
        cam = PerspectiveCamera()
        vp = cam.view_projection_matrix
        assert vp.shape == (4, 4)

    def test_forward_vector(self) -> None:
        """Forward should point from position toward target."""
        cam = PerspectiveCamera()
        cam.position = (0, 0, 5)
        cam.target = (0, 0, 0)
        fwd = cam.forward()
        assert fwd[2] < 0
        assert abs(np.linalg.norm(fwd) - 5.0) < 1e-6

    def test_up_vector_default(self) -> None:
        cam = PerspectiveCamera()
        assert cam.up.shape == (3,)

    def test_look_at(self) -> None:
        cam = PerspectiveCamera()
        cam.look_at(eye=(0, 5, 10), target=(0, 0, 0))
        pos = cam.position
        assert abs(np.linalg.norm(pos - np.array([0, 5, 10]))) < 1e-10

    def test_mark_dirty(self) -> None:
        cam = PerspectiveCamera()
        cam.mark_dirty()
        # Access view matrix to trigger recalculation
        v = cam.view_matrix
        assert v.shape == (4, 4)


@pytest.mark.parametrize("camera_cls", [PerspectiveCamera, OrthographicCamera])
def test_near_far_setters(camera_cls: type) -> None:
    """Near and far setters work identically for both camera types."""
    cam = camera_cls()
    cam.near = 0.1
    cam.far = 500.0
    assert cam.near == 0.1
    assert cam.far == 500.0


# ===========================================================================
# Camera — OrbitCamera
# ===========================================================================


class TestOrbitCamera:
    def test_construction(self) -> None:
        """OrbitCamera should be constructable with a perspective camera."""
        inner = PerspectiveCamera()
        orbit = OrbitCamera(camera=inner)
        assert orbit.inner is inner
        assert orbit.distance == 10.0

    def test_default_construction(self) -> None:
        """OrbitCamera creates its own PerspectiveCamera by default."""
        orbit = OrbitCamera()
        assert isinstance(orbit.inner, PerspectiveCamera)

    def test_initial_view_matrix(self) -> None:
        """After update(), the view matrix should be a valid 4x4."""
        orbit = OrbitCamera()
        orbit.distance = 10.0
        orbit.update(dt=0.016)
        v = orbit.view_matrix
        assert v.shape == (4, 4)
        assert isinstance(v, np.ndarray)

    def test_orbit_changes_view(self) -> None:
        """Orbiting should change the position."""
        inner = PerspectiveCamera()
        orbit = OrbitCamera(camera=inner)
        orbit.distance = 10.0
        orbit.update(dt=0.016)
        pos_before = inner.position.copy()

        orbit.orbit(delta_x=90, delta_y=0)
        orbit.update(dt=0.016)
        pos_after = inner.position

        assert not np.allclose(pos_before, pos_after)

    def test_zoom_changes_distance(self) -> None:
        """Negative delta zooms in (decreases distance)."""
        orbit = OrbitCamera()
        orbit.distance = 10.0
        orbit.update()  # dt=0 → instant settle
        orbit.zoom(-0.5)
        orbit.update()
        assert orbit.distance < 10.0

    def test_zoom_out_increases_distance(self) -> None:
        orbit = OrbitCamera()
        orbit.distance = 10.0
        orbit.update(dt=0.016)
        orbit.zoom(1.5)
        orbit.update(dt=0.016)
        assert orbit.distance > 10.0

    def test_pan_changes_target(self) -> None:
        inner = PerspectiveCamera()
        orbit = OrbitCamera(camera=inner)
        orbit.distance = 10.0
        orbit.update(dt=0.016)
        target_before = inner.target.copy()

        orbit.pan(delta_x=1.0, delta_y=0.0)
        orbit.update(dt=0.016)
        target_after = inner.target

        assert not np.allclose(target_before, target_after)

    def test_view_projection_pass_through(self) -> None:
        orbit = OrbitCamera()
        orbit.update(dt=0.016)
        vp = orbit.view_projection_matrix
        assert vp.shape == (4, 4)

    def test_projection_matrix_pass_through(self) -> None:
        orbit = OrbitCamera()
        orbit.update(dt=0.016)
        p = orbit.projection_matrix
        assert p.shape == (4, 4)

    def test_constraints_default(self) -> None:
        orbit = OrbitCamera()
        c = orbit.constraints
        assert c.min_distance == 0.1
        assert c.max_distance == 500.0

    def test_azimuth_polar_properties(self) -> None:
        orbit = OrbitCamera()
        orbit.update()
        orbit.azimuth = 1.0
        orbit.polar = 1.0
        orbit.update()  # dt=0 → instant settle
        assert orbit.azimuth == pytest.approx(1.0, abs=1e-3)
        assert orbit.polar == pytest.approx(1.0, abs=1e-3)

    def test_enabled_toggle(self) -> None:
        orbit = OrbitCamera()
        assert orbit.enabled is True
        orbit.enabled = False
        assert orbit.enabled is False

    def test_disabled_orbit_does_nothing(self) -> None:
        inner = PerspectiveCamera()
        orbit = OrbitCamera(camera=inner)
        orbit.distance = 10.0
        orbit.update(dt=0.016)
        pos_before = inner.position.copy()
        orbit.enabled = False
        orbit.orbit(delta_x=90, delta_y=0)
        orbit.update(dt=0.016)
        assert np.allclose(pos_before, inner.position)

    def test_frame_scene(self) -> None:
        orbit = OrbitCamera()
        orbit.frame_scene(center=(0, 0, 0), radius=5.0)
        assert orbit.distance == pytest.approx(12.5)  # radius * 2.5

    def test_reset_view(self) -> None:
        orbit = OrbitCamera()
        orbit.orbit(delta_x=45, delta_y=30)
        orbit.reset_view()
        orbit.update(dt=0.016)
        assert orbit.azimuth == pytest.approx(math.pi * 0.25, abs=1e-3)
        assert orbit.polar == pytest.approx(math.pi * 0.35, abs=1e-3)
        assert orbit.distance == 10.0

    def test_zoom_absolute(self) -> None:
        orbit = OrbitCamera()
        orbit.zoom_absolute(25.0)
        orbit.update()  # dt=0 → instant settle
        assert orbit.distance == 25.0


# ===========================================================================
# Mesh — data structures
# ===========================================================================


class TestMeshConstruction:
    def test_plane_mesh(self) -> None:
        mesh = Mesh.plane(size=2.0)
        assert mesh.vertex_count > 0
        assert mesh.triangle_count > 0
        assert mesh.vertices is not None
        assert mesh.indices is not None

    def test_cube_mesh(self) -> None:
        mesh = Mesh.cube(size=1.0)
        assert mesh.vertex_count > 0
        assert mesh.triangle_count > 0

    def test_sphere_mesh(self) -> None:
        mesh = Mesh.sphere(radius=1.0, segments=32)
        assert mesh.vertex_count > 0
        assert mesh.triangle_count > 0

    def test_plane_vertices_are_float32(self) -> None:
        mesh = Mesh.plane(2.0)
        assert mesh.vertices.dtype == np.float32

    def test_plane_indices_are_uint32(self) -> None:
        mesh = Mesh.plane(2.0)
        assert mesh.indices is not None
        assert mesh.indices.dtype == np.uint32

    def test_vertex_count_matches_data(self) -> None:
        mesh = Mesh.plane(2.0)
        assert mesh.vertex_count == len(mesh.vertices)

    def test_triangle_count_consistency(self) -> None:
        mesh = Mesh.cube(1.0)
        assert mesh.indices is not None
        expected = len(mesh.indices) // 3
        assert mesh.triangle_count == expected


class TestMeshComputedProperties:
    def test_bounding_box_plane(self) -> None:
        mesh = Mesh.plane(2.0)
        vmin, vmax = mesh.bounding_box
        assert (vmin <= vmax).all()

    def test_bounding_center_plane(self) -> None:
        mesh = Mesh.plane(2.0)
        center = mesh.bounding_center
        assert abs(center[0]) < 0.01
        assert abs(center[1]) < 0.01
        assert abs(center[2]) < 0.01

    def test_bounding_radius_positive(self) -> None:
        mesh = Mesh.sphere(radius=2.0, segments=32)
        assert mesh.bounding_radius > 0

    def test_bounding_radius_plane(self) -> None:
        mesh = Mesh.plane(2.0)
        assert mesh.bounding_radius > 0


class TestMeshNormals:
    def test_normals_exist_after_construction(self) -> None:
        """Normals should be auto-computed when missing."""
        mesh = Mesh.cube(1.0)
        assert mesh.normals is not None
        assert mesh.normals.shape[0] == mesh.vertex_count
        assert mesh.normals.shape[1] == 3

    def test_plane_normals_point_up(self) -> None:
        """Plane normals should point along Y."""
        mesh = Mesh.plane(2.0)
        assert mesh.normals is not None
        # All normals should have Y ~ 1
        assert np.allclose(mesh.normals[:, 1], 1.0)

    def test_normals_are_unit_length(self) -> None:
        mesh = Mesh.sphere(radius=1.0, segments=32)
        assert mesh.normals is not None
        lengths = np.linalg.norm(mesh.normals, axis=1)
        assert np.allclose(lengths, 1.0, atol=1e-5)

    def test_custom_normals_preserved(self) -> None:
        """If normals are passed, they should not be overwritten."""
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        custom_normals = np.array([[0, 0, 1], [0, 0, 1], [0, 0, 1]], dtype=np.float32)
        mesh = Mesh(vertices=verts, normals=custom_normals)
        assert mesh.normals is custom_normals


class TestMeshSerialization:
    def test_cube_has_correct_face_count(self) -> None:
        mesh = Mesh.cube(1.0)
        assert mesh.triangle_count >= 12  # 6 faces x 2 triangles

    def test_sphere_has_min_vertex_count(self) -> None:
        mesh = Mesh.sphere(radius=1.0, segments=32)
        assert mesh.vertex_count > 32  # at least one ring's worth

    def test_plane_has_two_triangles(self) -> None:
        mesh = Mesh.plane(2.0)
        assert mesh.triangle_count == 2


# ===========================================================================
# MouseButton
# ===========================================================================


class TestMouseButton:
    def test_enum_values(self) -> None:
        assert MouseButton.LEFT is not None
        assert MouseButton.RIGHT is not None
        assert MouseButton.MIDDLE is not None

    def test_enum_unique(self) -> None:
        assert MouseButton.LEFT != MouseButton.RIGHT
        assert MouseButton.MIDDLE != MouseButton.LEFT


# ===========================================================================
# RenderPass
# ===========================================================================


class TestRenderPass:
    def test_construction(self) -> None:
        p = _StubPass("test_pass")
        assert p.name == "test_pass"
        assert p.enabled is True
        assert p.visible is True
        assert p.target is None

    def test_enabled_setter(self) -> None:
        p = _StubPass("p")
        p.enabled = False
        assert p.enabled is False

    def test_visible_setter(self) -> None:
        p = _StubPass("p")
        p.visible = False
        assert p.visible is False

    def test_target_setter(self) -> None:
        p = _StubPass("p")
        p.target = None  # No GPU needed to set target to None
        assert p.target is None

    def test_release_invokes_cleanup(self) -> None:
        p = _StubPass("p")
        assert p.release_called is False
        p.release()
        assert p.release_called is True

    def test_release_is_idempotent(self) -> None:
        p = _StubPass("p")
        p.release()
        p.release()
        assert p.release_called  # no crash on double release

    def test_resize_calls_setup(self) -> None:
        p = _StubPass("p")
        p.resize(None, 800, 600)
        assert p.setup_called
        assert p.last_width == 800
        assert p.last_height == 600


# ===========================================================================
# RenderPipeline
# ===========================================================================


class TestRenderPipelineConstruction:
    def test_empty_pipeline(self) -> None:
        pl = RenderPipeline()
        assert pl.pass_count == 0
        assert pl.passes == []
        assert pl.enabled_passes == []

    def test_add_pass(self) -> None:
        pl = RenderPipeline()
        p = _StubPass("geometry")
        returned = pl.add_pass(p)
        assert returned is p
        assert pl.pass_count == 1
        assert p in pl.passes

    def test_add_pass_duplicate_raises(self) -> None:
        pl = RenderPipeline()
        pl.add_pass(_StubPass("bg"))
        with pytest.raises(ValueError, match="already exists"):
            pl.add_pass(_StubPass("bg"))

    def test_add_pass_at_index(self) -> None:
        pl = RenderPipeline()
        p1 = pl.add_pass(_StubPass("first"))
        p2 = pl.add_pass(_StubPass("second"))
        p0 = pl.add_pass(_StubPass("inserted"), index=0)
        assert pl.passes == [p0, p1, p2]

    def test_remove_pass(self) -> None:
        pl = RenderPipeline()
        p = pl.add_pass(_StubPass("to_remove"))
        assert isinstance(p, _StubPass)
        assert pl.pass_count == 1
        pl.remove_pass("to_remove")
        assert pl.pass_count == 0
        assert p.release_called

    def test_remove_nonexistent_no_error(self) -> None:
        pl = RenderPipeline()
        pl.remove_pass("does_not_exist")  # should not raise

    def test_get_pass_by_name(self) -> None:
        pl = RenderPipeline()
        pl.add_pass(_StubPass("a"))
        pl.add_pass(_StubPass("b"))
        assert pl.get_pass("a") is not None
        assert pl.get_pass("b") is not None
        assert pl.get_pass("c") is None

    def test_get_pass_at_valid_index(self) -> None:
        pl = RenderPipeline()
        p = pl.add_pass(_StubPass("p"))
        assert pl.get_pass_at(0) is p
        assert pl.get_pass_at(0) is p  # same pass

    def test_get_pass_at_invalid_index(self) -> None:
        pl = RenderPipeline()
        assert pl.get_pass_at(0) is None
        assert pl.get_pass_at(99) is None

    def test_move_pass(self) -> None:
        pl = RenderPipeline()
        p1 = pl.add_pass(_StubPass("a"))
        p2 = pl.add_pass(_StubPass("b"))
        p3 = pl.add_pass(_StubPass("c"))
        pl.move_pass("c", 0)
        assert pl.passes == [p3, p1, p2]

    def test_move_pass_nonexistent_no_error(self) -> None:
        pl = RenderPipeline()
        pl.move_pass("ghost", 0)  # should not raise

    def test_enabled_passes(self) -> None:
        pl = RenderPipeline()
        p1 = pl.add_pass(_StubPass("a"))
        p2 = pl.add_pass(_StubPass("b"))
        p3 = pl.add_pass(_StubPass("c"))
        p2.enabled = False
        enabled = pl.enabled_passes
        assert p1 in enabled
        assert p2 not in enabled
        assert p3 in enabled

    def test_release_clears_all_passes(self) -> None:
        pl = RenderPipeline()
        pl.add_pass(_StubPass("a"))
        pl.add_pass(_StubPass("b"))
        pl.release()
        assert pl.pass_count == 0
        assert pl.passes == []
        assert pl.enabled_passes == []


# ===========================================================================
# RenderTarget — ScreenTarget depth clear
# ===========================================================================


class TestScreenTargetDepthClear:
    """Tests for ScreenTarget.clear() depth parameter propagation."""

    def test_clear_passes_depth_to_gl_when_fbo_bound(self) -> None:
        """Non-default depth value must reach glClearDepthf before glClear."""
        fake_ctx = MagicMock()
        fake_ctx.screen = MagicMock()

        with patch("projectionai.infrastructure.renderer.render_target._gl") as mock_gl:
            mock_gl_obj = MagicMock()
            mock_gl.return_value = mock_gl_obj

            target = ScreenTarget(fake_ctx, 800, 600, fbo_id=1)
            target.clear(0.0, 0.0, 0.0, 1.0, depth=0.5)

            # Verify glClearDepthf was called with the custom depth value
            mock_gl_obj.glClearDepthf.assert_called_once_with(0.5)
            # Verify glClear was called with both color and depth bits
            mock_gl_obj.glClear.assert_called_once()

    def test_clear_uses_default_depth_when_not_specified(self) -> None:
        """Default depth (1.0) must be passed when not explicitly set."""
        fake_ctx = MagicMock()
        fake_ctx.screen = MagicMock()

        with patch("projectionai.infrastructure.renderer.render_target._gl") as mock_gl:
            mock_gl_obj = MagicMock()
            mock_gl.return_value = mock_gl_obj

            target = ScreenTarget(fake_ctx, 800, 600, fbo_id=1)
            target.clear(0.0, 0.0, 0.0, 1.0)  # depth defaults to 1.0

            mock_gl_obj.glClearDepthf.assert_called_once_with(1.0)

    def test_clear_delegates_to_mgl_when_no_fbo(self) -> None:
        """Without external FBO, clear delegates to ModernGL screen.clear()."""
        fake_ctx = MagicMock()
        fake_screen = MagicMock()
        fake_ctx.screen = fake_screen

        target = ScreenTarget(fake_ctx, 800, 600, fbo_id=0)
        target.clear(0.1, 0.2, 0.3, 1.0, depth=0.75)

        fake_screen.clear.assert_called_once_with(0.1, 0.2, 0.3, 1.0, 0.75)
