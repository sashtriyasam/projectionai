"""Tests for PatternPass (state only, no GL).

Follows the repository convention for render-pass tests
(see test_overlay_pass_calibration.py): GPU resources are replaced by
small fakes so behaviour is verified without a GL context.
"""

from __future__ import annotations

from typing import Any

import pytest

from projectionai.infrastructure.renderer.passes.pattern import PatternPass


class FakeShader:
    """Stand-in for ``Shader`` recording use/uniform/release calls."""

    def __init__(self) -> None:
        self.used = 0
        self.ints: dict[str, int] = {}
        self.released = False

    def use(self) -> None:
        self.used += 1

    def set_int(self, name: str, value: int) -> None:
        self.ints[name] = value

    def release(self) -> None:
        self.released = True


class FakeVao:
    """Stand-in for a ModernGL VAO recording render/release calls."""

    def __init__(self) -> None:
        self.rendered = 0
        self.released = False

    def render(self) -> None:
        self.rendered += 1

    def release(self) -> None:
        self.released = True


class FakeTexture:
    """Stand-in for ``Texture`` recording bind/unbind calls."""

    def __init__(self, name: str = "tex") -> None:
        self.name = name
        self.bound_units: list[int] = []
        self.unbound = 0

    def bind(self, unit: int = 0) -> None:
        self.bound_units.append(unit)

    def unbind(self) -> None:
        self.unbound += 1


class FakeTarget:
    """Stand-in for a ``RenderTarget`` recording bind/clear calls."""

    def __init__(self) -> None:
        self.width = 1920
        self.height = 1080
        self.binds = 0
        self.unbinds = 0
        self.clears: list[tuple[float, float, float, float]] = []

    def bind(self) -> None:
        self.binds += 1

    def unbind(self) -> None:
        self.unbinds += 1

    def clear(
        self,
        r: float = 0.0,
        g: float = 0.0,
        b: float = 0.0,
        a: float = 1.0,
        depth: float = 1.0,
    ) -> None:
        self.clears.append((r, g, b, a))


def _seeded_pass(
    *,
    shader: bool = True,
    vao: bool = True,
    target: bool = True,
    texture: FakeTexture | None = None,
) -> tuple[PatternPass, FakeShader, FakeVao, FakeTarget]:
    pattern_pass = PatternPass()
    fake_shader = FakeShader()
    fake_vao = FakeVao()
    fake_target = FakeTarget()
    if shader:
        pattern_pass._shader = fake_shader
    if vao:
        pattern_pass._vao = fake_vao
    if target:
        pattern_pass._target = fake_target
    pattern_pass._texture = texture
    return pattern_pass, fake_shader, fake_vao, fake_target


def test_initial_state() -> None:
    pattern_pass = PatternPass()
    assert pattern_pass.name == "pattern"
    assert pattern_pass._shader is None
    assert pattern_pass._vao is None
    assert pattern_pass._texture is None
    assert pattern_pass.target is None
    assert pattern_pass.enabled
    assert pattern_pass.visible


def test_set_texture_stores_and_clears() -> None:
    pattern_pass = PatternPass()
    texture = FakeTexture()
    pattern_pass.set_texture(texture)
    assert pattern_pass._texture is texture
    pattern_pass.set_texture(None)
    assert pattern_pass._texture is None


def test_render_without_resources_is_noop() -> None:
    PatternPass().render(None, None, None)  # must not raise


def test_render_without_target_is_noop() -> None:
    pattern_pass, fake_shader, fake_vao, _ = _seeded_pass(
        target=False, texture=FakeTexture()
    )
    pattern_pass.render(None, None, None)
    assert fake_shader.used == 0
    assert fake_vao.rendered == 0


def test_render_without_texture_clears_black() -> None:
    pattern_pass, fake_shader, fake_vao, fake_target = _seeded_pass(texture=None)
    pattern_pass.render(None, None, None)
    assert fake_target.binds == 1
    assert fake_target.clears == [(0.0, 0.0, 0.0, 1.0)]
    assert fake_shader.used == 1
    assert fake_vao.rendered == 0


def test_render_with_texture_binds_and_draws() -> None:
    texture = FakeTexture()
    pattern_pass, fake_shader, fake_vao, fake_target = _seeded_pass(texture=texture)
    pattern_pass.render(None, None, None)
    assert fake_target.binds == 1
    assert fake_target.clears == [(0.0, 0.0, 0.0, 1.0)]
    assert fake_shader.used == 1
    assert fake_shader.ints == {"u_texture": 0}
    assert texture.bound_units == [0]
    assert texture.unbound == 1
    assert fake_vao.rendered == 1


def test_release_releases_gpu_resources() -> None:
    pattern_pass, fake_shader, fake_vao, _ = _seeded_pass(texture=FakeTexture())
    pattern_pass.release()
    assert fake_shader.released
    assert fake_vao.released
    assert pattern_pass._shader is None
    assert pattern_pass._vao is None
    assert pattern_pass._texture is None


def test_release_is_idempotent() -> None:
    pattern_pass, fake_shader, fake_vao, _ = _seeded_pass()
    pattern_pass.release()
    pattern_pass.release()
    assert fake_shader.released
    assert fake_vao.released


class _FakeVbo:
    pass


class _FakeCtx:
    def __init__(self) -> None:
        self.buffers: list[bytes] = []
        self.vbo: _FakeVbo | None = None
        self.vao_args: tuple[Any, ...] | None = None

    def buffer(self, data: bytes) -> _FakeVbo:
        self.buffers.append(data)
        self.vbo = _FakeVbo()
        return self.vbo

    def vertex_array(self, *args: Any) -> object:
        self.vao_args = args
        return object()


class _FakeShader:
    def __init__(self) -> None:
        self.program = object()


def test_setup_passes_shader_program_to_vertex_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_shader = _FakeShader()

    def _fake_shader_factory(_ctx: Any, _name: str) -> _FakeShader:
        return fake_shader

    monkeypatch.setattr(
        "projectionai.infrastructure.renderer.shader.Shader",
        _fake_shader_factory,
    )
    ctx = _FakeCtx()
    pattern_pass = PatternPass()
    pattern_pass.setup(ctx, 1920, 1080)

    assert ctx.vao_args is not None
    program, content = ctx.vao_args
    assert program is fake_shader.program
    assert len(ctx.buffers) == 1
    assert len(ctx.buffers[0]) == 6 * 4 * 4
    assert content == [(ctx.vbo, "2f 2f", "in_position", "in_uv")]
