"""ProjectionPass — GPU-accelerated warp mesh rendering for projector output.

Renders content texture warped through a WarpMesh using vertex-shader-driven
distortion. Source texture is bound, warped mesh VBO is uploaded, and GPU
interpolates content UVs per-vertex.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import numpy as np

from projectionai.domain.warp_mesh import WarpMesh
from projectionai.infrastructure.renderer.pipeline_pass import RenderPass

_logger = logging.getLogger(__name__)


class ProjectionTexture(Protocol):
    """Minimal texture surface ProjectionPass needs."""

    def bind(self, unit: int = 0) -> None: ...
    def unbind(self) -> None: ...


class ProjectionPass(RenderPass):
    """Renders content texture warped through a WarpMesh.

    GPU does the warp per-frame: vertex shader applies mesh distortion,
    fragment shader handles blend/mask/crop.
    """

    def __init__(self, name: str = "projection") -> None:
        super().__init__(name)
        self._shader: Any = None
        self._ctx: Any = None
        self._vao: Any = None
        self._vbo: Any = None
        self._ibo: Any = None
        self._source_texture: ProjectionTexture | None = None
        self._warp_mesh: WarpMesh | None = None
        self._mesh_id: int = -1
        self._index_count: int = 0
        self._blend: float = 1.0
        self._crop: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
        self._mask_enabled: bool = False
        self._mask_center: tuple[float, float] = (0.5, 0.5)
        self._mask_radius: float = 0.5

    # -- Public API --------------------------------------------------------

    def set_source_texture(self, texture: ProjectionTexture | None) -> None:
        """Set the content texture to warp."""
        self._source_texture = texture

    def set_warp_mesh(self, mesh: WarpMesh | None) -> None:
        """Set the warp mesh (triggers VBO re-upload if changed)."""
        self._warp_mesh = mesh
        if mesh is None:
            self._mesh_id = -1

    def set_blend(self, blend: float) -> None:
        """Set blend opacity (0.0 = transparent, 1.0 = opaque)."""
        self._blend = blend

    def set_crop(self, x: float, y: float, width: float, height: float) -> None:
        """Set crop region (normalized 0-1)."""
        self._crop = (x, y, width, height)

    def set_mask(
        self, enabled: bool, center: tuple[float, float], radius: float
    ) -> None:
        """Set circular mask parameters."""
        self._mask_enabled = enabled
        self._mask_center = center
        self._mask_radius = radius

    # -- RenderPass interface ----------------------------------------------

    def setup(self, ctx: Any, width: int, height: int) -> None:
        """Compile projection shader. VBO/IBO/VAO created on first mesh upload."""
        from projectionai.infrastructure.renderer.shader import Shader

        self._ctx = ctx
        self._shader = Shader(ctx, "projection")

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        """Upload mesh if changed, bind texture, set uniforms, draw."""
        target = self._target
        if self._shader is None or self._vao is None or target is None:
            return

        # Upload mesh to VBO if changed
        self._ensure_mesh_uploaded()

        target.bind()
        target.clear(0.0, 0.0, 0.0, 1.0)

        if self._source_texture is not None and self._warp_mesh is not None:
            # Bind source texture
            self._source_texture.bind(0)
            self._shader.set_int("u_texture", 0)

            # Set blend/mask/crop uniforms
            self._shader.set_float("u_blend", self._blend)
            self._shader.set_vec4("u_crop", *self._crop)
            self._shader.set_int("u_mask_enabled", 1 if self._mask_enabled else 0)
            self._shader.set_vec2("u_mask_center", *self._mask_center)
            self._shader.set_float("u_mask_radius", self._mask_radius)

            # Enable OpenGL blending so fragment alpha (u_blend + mask
            # feathering) participates in compositing against the cleared
            # background.  Disabled afterward to avoid leaking state.
            import moderngl

            self._ctx.enable(moderngl.BLEND)
            self._ctx.blend_func = (
                moderngl.SRC_ALPHA,
                moderngl.ONE_MINUS_SRC_ALPHA,
            )

            # Draw warped mesh
            if self._index_count > 0:
                self._vao.render(moderngl.TRIANGLES)

            self._ctx.disable(moderngl.BLEND)

            self._source_texture.unbind()

    def release(self) -> None:
        """Release GPU resources."""
        self._source_texture = None
        self._warp_mesh = None
        self._mesh_id = -1
        self._index_count = 0
        if self._shader is not None:
            self._shader.release()
            self._shader = None
        if self._vao is not None:
            self._vao.release()
            self._vao = None
        if self._vbo is not None:
            self._vbo.release()
            self._vbo = None
        if self._ibo is not None:
            self._ibo.release()
            self._ibo = None

    # -- Internal ----------------------------------------------------------

    def _ensure_mesh_uploaded(self) -> None:
        """Upload mesh VBO/IBO and rebuild VAO if mesh changed."""
        if self._warp_mesh is None or self._ctx is None or self._shader is None:
            return

        # Check if mesh object changed
        current_id = id(self._warp_mesh)
        if self._mesh_id == current_id:
            return

        # Build interleaved vertex data: [x, y, u, v] per vertex
        # projector_uvs → clip-space positions (in_position)
        # content_uvs → texture coordinates (in_uv)
        projector_uvs = self._warp_mesh.projector_uvs  # (V, 2) float64, [0,1]
        content_uvs = self._warp_mesh.content_uvs  # (V, 2) float64
        indices = self._warp_mesh.indices  # (F, 3) int32

        # Convert projector UV [0,1] to NDC [-1,1].
        # Projector UV is V-down (origin top-left); NDC is Y-up.
        v_count = len(projector_uvs)
        interleaved = np.empty((v_count, 4), dtype=np.float32)
        interleaved[:, 0] = (projector_uvs[:, 0] * 2.0 - 1.0).astype(np.float32)
        interleaved[:, 1] = (1.0 - projector_uvs[:, 1] * 2.0).astype(np.float32)
        interleaved[:, 2] = content_uvs[:, 0].astype(np.float32)  # u
        interleaved[:, 3] = content_uvs[:, 1].astype(np.float32)  # v

        # Release previous GPU resources
        if self._vao is not None:
            self._vao.release()
            self._vao = None
        if self._vbo is not None:
            self._vbo.release()
            self._vbo = None
        if self._ibo is not None:
            self._ibo.release()
            self._ibo = None

        # Create VBO
        self._vbo = self._ctx.buffer(interleaved.tobytes())

        # Create index buffer and rebuild VAO
        if indices is not None and len(indices) > 0:
            self._ibo = self._ctx.buffer(indices.astype(np.int32).tobytes())
            self._index_count = len(indices) * 3
            self._vao = self._ctx.vertex_array(
                self._shader.program,
                [(self._vbo, "2f 2f", "in_position", "in_uv"), self._ibo],
            )
        else:
            self._index_count = v_count
            self._vao = self._ctx.vertex_array(
                self._shader.program,
                [(self._vbo, "2f 2f", "in_position", "in_uv")],
            )

        self._mesh_id = current_id

        _logger.debug(
            "ProjectionPass: uploaded %d vertices, %d indices (mesh_id %d)",
            v_count,
            self._index_count,
            self._mesh_id,
        )
