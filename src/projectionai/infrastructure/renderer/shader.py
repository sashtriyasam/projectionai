"""Shader — ModernGL shader compilation and uniform management.

Compiles vertex + fragment shader pairs and exposes a clean API for
setting uniforms. All GLSL source lives in ``shaders/`` with a fallback
embedded module ``_glsl.py``.

Compatible with ModernGL 5.12+ where Program.use() is removed and
VAO.render() automatically uses the program stored in the VAO.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

import moderngl
import numpy as np
from numpy.typing import NDArray

_logger = logging.getLogger(__name__)

_SHADER_DIR = Path(__file__).resolve().parent / "shaders"


class ShaderError(RuntimeError):
    """Raised when shader compilation fails."""


class Shader:
    """A compiled ModernGL shader program.

    Usage::

        shader = Shader(ctx, "mesh")
        shader["model_matrix"].write(model)
        shader.render(mesh_vao)
    """

    def __init__(
        self,
        ctx: Any,
        name: str,
        *,
        vert_path: str | None = None,
        frag_path: str | None = None,
    ) -> None:
        """Compile a shader program.

        Args:
            ctx: ModernGL context.
            name: Shader name (used to find ``shaders/{name}.vert`` and ``shaders/{name}.frag``).
            vert_path: Override vertex shader path.
            frag_path: Override fragment shader path.
        """
        self._ctx = ctx
        self._name = name
        self._program: Any = None
        self._uniforms: dict[str, Any] = {}
        self._attributes: dict[str, Any] = {}

        vert_source = self._load_source(vert_path or f"{name}.vert")
        frag_source = self._load_source(frag_path or f"{name}.frag")

        try:
            self._program = ctx.program(
                vertex_shader=vert_source, fragment_shader=frag_source
            )
        except Exception as exc:
            raise ShaderError(f"Failed to compile shader '{name}': {exc}") from exc

        # Cache only actual Uniform objects (ModernGL 5.12+ iterates both
        # uniforms and attributes; filter by type).
        for name in self._program:
            item = self._program[name]
            if isinstance(item, moderngl.Uniform):
                self._uniforms[name] = item

        # Cache attribute locations for known vertex attributes
        for attr_name in ("in_position", "in_normal", "in_uv", "in_color"):
            with contextlib.suppress(Exception):
                item = self._program[attr_name]
                if isinstance(item, moderngl.Attribute):
                    self._attributes[attr_name] = item

        _logger.debug(
            "Compiled shader '%s' (%d uniforms, %d attributes)",
            name,
            len(self._uniforms),
            len(self._attributes),
        )

    # -- Uniform access ----------------------------------------------------

    def __getitem__(self, name: str) -> Any:
        """Access a uniform by name (returns the ModernGL uniform object)."""
        try:
            return self._uniforms[name]
        except KeyError:
            raise ShaderError(
                f"Uniform '{name}' not found in shader '{self._name}'"
            ) from None

    def __setitem__(self, name: str, value: Any) -> None:
        """Set a uniform value directly."""
        self._uniforms[name].write(value)

    def __contains__(self, name: str) -> bool:
        return name in self._uniforms

    def set_uniform(self, name: str, value: Any) -> None:
        """Set a uniform by name with automatic type dispatch."""
        if name not in self._uniforms:
            return  # silently ignore — shader may not use it
        uniform = self._uniforms[name]
        try:
            uniform.value = value
        except Exception:
            uniform.write(bytes(value))

    def set_vec3(self, name: str, x: float, y: float, z: float) -> None:
        """Set a vec3 uniform."""
        if name in self._uniforms:
            self._uniforms[name].value = (x, y, z)

    def set_vec4(self, name: str, x: float, y: float, z: float, w: float) -> None:
        """Set a vec4 uniform."""
        if name in self._uniforms:
            self._uniforms[name].value = (x, y, z, w)

    def set_mat4(self, name: str, matrix: NDArray[np.float32]) -> None:
        """Set a mat4 uniform from a 4x4 numpy array."""
        if name in self._uniforms:
            self._uniforms[name].write(matrix.tobytes())

    def set_int(self, name: str, value: int) -> None:
        """Set an int/sampler uniform."""
        if name in self._uniforms:
            self._uniforms[name].value = value

    def set_float(self, name: str, value: float) -> None:
        """Set a float uniform."""
        if name in self._uniforms:
            self._uniforms[name].value = value

    def set_vec2(self, name: str, x: float, y: float) -> None:
        """Set a vec2 uniform."""
        if name in self._uniforms:
            self._uniforms[name].value = (x, y)

    # -- Render ------------------------------------------------------------

    def use(self) -> None:
        """Bind the shader program for rendering.

        No-op in ModernGL 5.12+. VAO.render() automatically uses the
        program stored in the VAO. Kept for API compatibility.
        """
        # ModernGL 5.12+: Program.use() removed; VAO stores program reference.
        pass

    def render(
        self, vao: Any, mode: int | None = None, vertices: int | None = None
    ) -> None:
        """Render a VAO with this shader.

        ModernGL 5.12+: VAO stores the program; explicit program.use()
        is not needed. VAO.render() uses the program it was created with.
        """
        if mode is not None:
            vao.render(mode, vertices=vertices or vao.vertices)
        else:
            vao.render()

    # -- Properties --------------------------------------------------------

    @property
    def program(self) -> Any:
        """ModernGL program object."""
        return self._program

    @property
    def name(self) -> str:
        return self._name

    @property
    def uniforms(self) -> dict[str, Any]:
        return dict(self._uniforms)

    # -- Lifecycle ---------------------------------------------------------

    def release(self) -> None:
        """Release GPU resources."""
        if self._program:
            self._program.release()
            self._program = None

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.release()

    # -- Internal ----------------------------------------------------------

    def _load_source(self, path: str) -> str:
        """Load GLSL source from file, falling back to embedded module."""
        file_path = _SHADER_DIR / path
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")

        # Fallback to embedded sources
        try:
            from projectionai.infrastructure.renderer._glsl import (
                EMBEDDED_SHADERS,
            )

            return EMBEDDED_SHADERS[path]
        except (ImportError, KeyError):
            raise ShaderError(f"Shader source not found: {path}") from None
