"""PatternPass — fullscreen textured pass for projector output.

Draws a single texture over the whole target using the existing
``fullscreen`` shader. With no texture assigned the target is cleared
to black, which is exactly what blackout requires.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from projectionai.infrastructure.renderer.pipeline_pass import RenderPass


class PatternTexture(Protocol):
    """Minimal texture surface PatternPass needs.

    ``Texture`` satisfies this protocol structurally; keeping a protocol
    here lets the pass be tested with lightweight fakes.
    """

    def bind(self, unit: int = 0) -> None: ...

    def unbind(self) -> None: ...


class PatternPass(RenderPass):
    """Renders a fullscreen texture (test patterns / solid colours)."""

    def __init__(self, name: str = "pattern") -> None:
        super().__init__(name)
        self._shader: Any = None
        self._vao: Any = None
        self._texture: PatternTexture | None = None

    # -- Public API --------------------------------------------------------

    def set_texture(self, texture: PatternTexture | None) -> None:
        """Set the texture drawn fullscreen; ``None`` renders black."""
        self._texture = texture

    # -- RenderPass interface ----------------------------------------------

    def setup(self, ctx: Any, width: int, height: int) -> None:
        """Compile the fullscreen shader and build the quad VAO."""
        from projectionai.infrastructure.renderer.shader import Shader

        self._shader = Shader(ctx, "fullscreen")

        # Two triangles covering clip space; each vertex is (x, y, u, v).
        vertices = np.array(
            [
                [-1.0, -1.0, 0.0, 0.0],
                [1.0, -1.0, 1.0, 0.0],
                [1.0, 1.0, 1.0, 1.0],
                [-1.0, -1.0, 0.0, 0.0],
                [1.0, 1.0, 1.0, 1.0],
                [-1.0, 1.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
        vbo = ctx.buffer(vertices.tobytes())
        self._vao = ctx.vertex_array(
            self._shader.program, [(vbo, "2f 2f", "in_position", "in_uv")]
        )

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        """Clear the target, then draw the current texture fullscreen."""
        target = self._target
        if self._shader is None or self._vao is None or target is None:
            return
        target.bind()
        target.clear(0.0, 0.0, 0.0, 1.0)
        self._shader.use()
        if self._texture is not None:
            self._texture.bind(0)
            self._shader.set_int("u_texture", 0)
            self._vao.render()
            self._texture.unbind()

    def release(self) -> None:
        """Release GPU resources (the texture is owned by the window)."""
        self._texture = None
        if self._shader is not None:
            self._shader.release()
            self._shader = None
        if self._vao is not None:
            self._vao.release()
            self._vao = None
