"""OverlayPass — 2D overlays (text, HUD, statistics, axis gizmo)."""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from projectionai.infrastructure.renderer.pipeline_pass import RenderPass

# Colour (RGBA, 0..1) for the calibration board-corner overlay lines.
# Mirrors ``CalibrationOverlay.CORNER_COLOR`` in the editor layer.
_CALIBRATION_COLOR: NDArray[np.float32] = np.array(
    [0.2, 1.0, 0.4, 1.0], dtype=np.float32
)


class OverlayPass(RenderPass):
    """Renders 2D overlay elements on top of the scene.

    Supports axis gizmo, FPS counter, and statistics overlay.
    Text rendering uses simple debug rect geometry (full text rendering
    will use a bitmap font in a future pass).
    """

    def __init__(self, name: str = "overlay") -> None:
        super().__init__(name)
        self._shader: Any = None
        self._axis_shader: Any = None
        self._axis_vao: Any = None
        self._quad_vao: Any = None

        # Calibration corner overlay (pixel-space line vertices)
        self._corner_lines: NDArray[np.float32] | None = None
        self._corner_vao: Any = None
        self._corner_vbo: Any = None
        self._corner_dirty: bool = False

        # Statistics
        self._show_fps: bool = True
        self._show_statistics: bool = False
        self._fps: float = 0.0
        self._frame_time: float = 0.0
        self._draw_calls: int = 0
        self._triangles: int = 0

        # Axis gizmo
        self._show_gizmo: bool = True
        self._gizmo_size: int = 60

    @property
    def show_fps(self) -> bool:
        return self._show_fps

    @show_fps.setter
    def show_fps(self, value: bool) -> None:
        self._show_fps = value

    @property
    def show_statistics(self) -> bool:
        return self._show_statistics

    @show_statistics.setter
    def show_statistics(self, value: bool) -> None:
        self._show_statistics = value

    @property
    def show_gizmo(self) -> bool:
        return self._show_gizmo

    @show_gizmo.setter
    def show_gizmo(self, value: bool) -> None:
        self._show_gizmo = value

    def update_stats(
        self, fps: float, frame_time: float, draw_calls: int, triangles: int
    ) -> None:
        """Update the statistics displayed by this pass."""
        self._fps = fps
        self._frame_time = frame_time
        self._draw_calls = draw_calls
        self._triangles = triangles

    # -- Calibration corner overlay ------------------------------------------

    def set_corner_lines(self, corners: NDArray[np.float32] | None) -> None:
        """Set the calibration board-corner line vertices (pixel space).

        Args:
            corners: Line vertices with shape ``(M, 2)`` in viewport pixel
                coordinates, or ``None`` to clear the corner overlay.
                Consecutive pairs of vertices form one line segment.
        """
        if corners is None:
            self._corner_lines = None
        else:
            corners = np.asarray(corners, dtype=np.float32)
            if corners.ndim != 2 or corners.shape[1] != 2:
                raise ValueError(f"corners must have shape (M, 2), got {corners.shape}")
            self._corner_lines = corners.copy()
        self._corner_dirty = True

    def _rebuild_corner_vao(self, ctx: Any) -> None:
        """(Re)build the corner-line VAO from the current vertex data."""
        if self._corner_vao is not None:
            self._corner_vao.release()
            self._corner_vao = None
        if self._corner_vbo is not None:
            self._corner_vbo.release()
            self._corner_vbo = None
        self._corner_dirty = False

        if self._corner_lines is None or self._corner_lines.shape[0] == 0:
            return
        if self._shader is None:
            return

        # Interleave position (2f) + colour (4f) for the overlay shader.
        n = self._corner_lines.shape[0]
        colors = np.tile(_CALIBRATION_COLOR, (n, 1))
        data = np.hstack([self._corner_lines, colors]).astype(np.float32)
        self._corner_vbo = ctx.buffer(data.tobytes())
        self._corner_vao = ctx.vertex_array(
            self._shader.program,
            [(self._corner_vbo, "2f 4f", "in_position", "in_color")],
        )

    def setup(self, ctx: Any, width: int, height: int) -> None:
        from projectionai.infrastructure.renderer.shader import Shader

        self._shader = Shader(ctx, "overlay")
        self._axis_shader = Shader(ctx, "axis_gizmo")

        # Full-screen quad for 2D rendering
        verts = np.array(
            [
                [-1, -1, 0, 1],
                [1, -1, 1, 1],
                [1, 1, 1, 0],
                [-1, -1, 0, 1],
                [1, 1, 1, 0],
                [-1, 1, 0, 0],
            ],
            dtype=np.float32,
        )
        vbo = ctx.buffer(verts.tobytes())
        self._quad_vao = ctx.vertex_array(
            self._shader.program, [(vbo, "2f 2f", "in_position", "in_uv")]
        )

        # Axis gizmo geometry (3 coloured lines)
        axis_verts = np.array(
            [
                # X axis (red)
                [0, 0, 0, 1, 0, 0, 1],
                [1, 0, 0, 1, 0, 0, 1],
                # Y axis (green)
                [0, 0, 0, 0, 1, 0, 1],
                [0, 1, 0, 0, 1, 0, 1],
                # Z axis (blue)
                [0, 0, 0, 0, 0, 1, 1],
                [0, 0, 1, 0, 0, 1, 1],
            ],
            dtype=np.float32,
        )
        axis_vbo = ctx.buffer(axis_verts.tobytes())
        self._axis_vao = ctx.vertex_array(
            self._axis_shader.program,
            [(axis_vbo, "3f 4f", "in_position", "in_color")],
        )

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        if self._shader is None:
            return
        target = self._target
        if target is None:
            return
        target.bind()

        import moderngl

        ctx.disable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)

        viewport_size = (float(target.width), float(target.height))
        self._shader.use()
        self._shader["u_viewport_size"] = viewport_size

        if self._show_gizmo and self._axis_vao and self._axis_shader:
            self._axis_shader.use()
            view = camera.view_matrix
            proj = camera.projection_matrix
            self._axis_shader.set_mat4("u_view", view)
            self._axis_shader.set_mat4("u_projection", proj)
            self._axis_shader.set_float("u_scale", 0.5)
            self._axis_vao.render(moderngl.LINES)

        # Calibration corner overlay (2D screen-space lines, pixel coords)
        if self._corner_lines is not None:
            if self._corner_dirty:
                self._rebuild_corner_vao(ctx)
            if self._corner_vao is not None:
                self._shader.use()
                self._shader["u_viewport_size"] = viewport_size
                self._corner_vao.render(moderngl.LINES)

        ctx.disable(moderngl.BLEND)
        ctx.enable(moderngl.DEPTH_TEST)

    def release(self) -> None:
        if self._shader:
            self._shader.release()
            self._shader = None
        if self._axis_shader:
            self._axis_shader.release()
            self._axis_shader = None
        if self._axis_vao:
            self._axis_vao.release()
            self._axis_vao = None
        if self._quad_vao:
            self._quad_vao.release()
            self._quad_vao = None
        if self._corner_vao:
            self._corner_vao.release()
            self._corner_vao = None
        if self._corner_vbo:
            self._corner_vbo.release()
            self._corner_vbo = None
        self._corner_lines = None
        self._corner_dirty = False
