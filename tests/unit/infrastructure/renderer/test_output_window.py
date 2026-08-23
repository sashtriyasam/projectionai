"""Tests for GLOutputWindow (offscreen Qt; no real GL required).

The window never assumes a working GPU: GL failures degrade to a black
window, so every assertion here targets non-GL behaviour (content model,
window flags, cursor, ESC signal, ``OutputWindow`` protocol methods).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any, cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from projectionai.hardware.patterns import PatternKind
from projectionai.infrastructure.renderer.output_content import (
    OutputContent,
    OutputContentKind,
)
from projectionai.infrastructure.renderer.output_window import GLOutputWindow
from projectionai.infrastructure.renderer.passes.pattern import PatternPass
from projectionai.infrastructure.renderer.passes.projection import ProjectionPass
from projectionai.infrastructure.renderer.texture import Texture


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Return the process-wide QApplication (created once)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app  # type: ignore[return-value]


@pytest.fixture
def window(qapp: QApplication) -> Iterator[GLOutputWindow]:
    win = GLOutputWindow()
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


class _FakeContext:
    """Minimal stand-in exposing ``.ctx`` for the window's GL setup."""

    def __init__(self) -> None:
        self.ctx: Any = object()


class _FakePass:
    def __init__(self) -> None:
        self.texture: Texture | None = None

    def set_texture(self, texture: Texture) -> None:
        self.texture = texture


class _FakeTexture:
    def __init__(self) -> None:
        self.releases = 0

    def release(self) -> None:
        self.releases += 1


class _FakeTarget:
    """Minimal stand-in for a RenderTarget."""

    def __init__(self) -> None:
        self.width = 1920
        self.height = 1080
        self.binds = 0
        self.clears: list[tuple[float, float, float, float]] = []
        self._fbo_id = 0
        self.resize_calls: list[tuple[int, int]] = []

    def bind(self) -> None:
        self.binds += 1

    def unbind(self) -> None:
        pass

    def clear(
        self,
        r: float = 0.0,
        g: float = 0.0,
        b: float = 0.0,
        a: float = 1.0,
        depth: float = 1.0,
    ) -> None:
        self.clears.append((r, g, b, a))

    def set_fbo_id(self, fbo_id: int) -> None:
        self._fbo_id = fbo_id

    def resize(self, w: int, h: int) -> None:
        self.resize_calls.append((w, h))


class _FakeProjectionPass:
    """Stand-in for ProjectionPass recording set_* and render calls."""

    def __init__(self) -> None:
        self.source_texture: Any = None
        self.warp_mesh: Any = None
        self.output_size: tuple[int, int] = (0, 0)
        self.rendered: list[tuple[Any, Any, Any]] = []
        self.resize_calls: list[tuple[Any, int, int]] = []
        self.target: Any = None

    def set_source_texture(self, texture: Any) -> None:
        self.source_texture = texture

    def set_warp_mesh(self, mesh: Any) -> None:
        self.warp_mesh = mesh

    def set_output_size(self, w: int, h: int) -> None:
        self.output_size = (w, h)

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        self.rendered.append((ctx, scene, camera))

    def setup(self, ctx: Any, w: int, h: int) -> None:
        pass

    def resize(self, ctx: Any, w: int, h: int) -> None:
        self.resize_calls.append((ctx, w, h))

    def release(self) -> None:
        pass


class _FakePatternPass:
    """Stand-in for PatternPass recording render calls."""

    def __init__(self) -> None:
        self.rendered: list[tuple[Any, Any, Any]] = []
        self.texture: Any = None
        self.resize_calls: list[tuple[Any, int, int]] = []
        self.target: Any = None

    def set_texture(self, texture: Any) -> None:
        self.texture = texture

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        self.rendered.append((ctx, scene, camera))

    def setup(self, ctx: Any, w: int, h: int) -> None:
        pass

    def resize(self, ctx: Any, w: int, h: int) -> None:
        self.resize_calls.append((ctx, w, h))

    def release(self) -> None:
        pass


def _make_fake_mesh() -> Any:
    """Minimal fake WarpMesh with id() for change detection."""
    mesh = _FakeWarpMesh()
    return mesh


class _FakeWarpMesh:
    """Minimal fake satisfying ProjectionPass mesh requirements."""

    def __init__(self) -> None:
        self.vertices = np.zeros((4, 2), dtype=np.float64)
        self.content_uvs = np.zeros((4, 2), dtype=np.float64)


def _make_fake_tex() -> _FakeProjTexture:
    """Minimal fake texture satisfying ProjectionTexture protocol."""
    return _FakeProjTexture()


class _FakeProjTexture:
    """Fake texture for ProjectionPass tests."""

    def __init__(self) -> None:
        self.bound_units: list[int] = []
        self.unbound = 0

    def bind(self, unit: int = 0) -> None:
        self.bound_units.append(unit)

    def unbind(self) -> None:
        self.unbound += 1


# ---------------------------------------------------------------------------
# Existing tests
# ---------------------------------------------------------------------------


def test_initial_content_is_black(window: GLOutputWindow) -> None:
    assert window.content == OutputContent.black()


def test_window_is_frameless(window: GLOutputWindow) -> None:
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint


def test_blank_cursor(window: GLOutputWindow) -> None:
    assert window.cursor().shape() == Qt.CursorShape.BlankCursor


def test_set_pattern_updates_content(window: GLOutputWindow) -> None:
    window.set_pattern(PatternKind.RED)
    content = window.content
    assert content.kind is OutputContentKind.PATTERN
    assert content.pattern_kind is PatternKind.RED


def test_set_blackout_updates_content(window: GLOutputWindow) -> None:
    window.set_pattern(PatternKind.RED)
    window.set_blackout()
    assert window.content == OutputContent.black()


def test_set_freeze_updates_content(window: GLOutputWindow) -> None:
    window.set_pattern(PatternKind.RED)
    window.set_freeze()
    assert window.content == OutputContent.freeze()


def test_set_content_same_is_noop(window: GLOutputWindow) -> None:
    window.set_content(OutputContent.pattern(PatternKind.BLUE))
    first = window.content
    window.set_content(OutputContent.pattern(PatternKind.BLUE))
    assert window.content is first  # unchanged instance, no repaint request


def test_set_content_different_replaces(window: GLOutputWindow) -> None:
    window.set_content(OutputContent.pattern(PatternKind.BLUE))
    window.set_content(OutputContent.pattern(PatternKind.GREEN))
    assert window.content == OutputContent.pattern(PatternKind.GREEN)


def test_escape_emits_output_escape_requested(window: GLOutputWindow) -> None:
    spy = QSignalSpy(window.output_escape_requested)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert spy.count() == 1


def test_other_keys_do_not_emit(window: GLOutputWindow) -> None:
    spy = QSignalSpy(window.output_escape_requested)
    QTest.keyClick(window, Qt.Key.Key_A)
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert spy.count() == 0


def test_satisfies_output_window_protocol(window: GLOutputWindow) -> None:
    """Hardware ``OutputWindow`` protocol methods must be available."""
    window.setGeometry(0, 0, 320, 240)
    assert window.width() == 320
    assert window.height() == 240
    window.showNormal()  # must not raise offscreen
    window.showFullScreen()  # must not raise offscreen
    window.showNormal()


def test_show_never_crashes_without_gl(
    window: GLOutputWindow, qapp: QApplication
) -> None:
    """Showing the window must not crash even when GL init fails."""
    window.show()
    qapp.processEvents()
    assert window.content == OutputContent.black()


def test_paint_clears_black_when_gl_not_ready(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The framebuffer must be explicitly blacked before GL is ready."""
    window._gl_ready = False
    cleared: list[bool] = []
    monkeypatch.setattr(window, "_clear_black", lambda: cleared.append(True))
    window.paintGL()
    assert cleared == [True]


def test_initialize_uses_widget_context_factory(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GL setup must attach to the widget's context, never a standalone one."""
    from projectionai.infrastructure.renderer.context import RenderContext
    from projectionai.infrastructure.renderer.render_target import ScreenTarget

    attached: list[object] = []
    created: list[_FakeContext] = []
    target_calls: list[tuple[Any, Any, int]] = []
    setup_calls: list[tuple[Any, Any]] = []

    def fake_from_widget(widget: object) -> _FakeContext:
        attached.append(widget)
        fake = _FakeContext()
        created.append(fake)
        return fake

    def fake_screen_target(
        _self: Any, ctx: Any, _width: int, _height: int, fbo_id: int = 0
    ) -> None:
        target_calls.append((_self, ctx, fbo_id))

    def fake_setup(_self: Any, ctx: Any, _width: int, _height: int) -> None:
        setup_calls.append((_self, ctx))

    monkeypatch.setattr(RenderContext, "from_widget", fake_from_widget)
    monkeypatch.setattr(ScreenTarget, "__init__", fake_screen_target)
    monkeypatch.setattr(PatternPass, "setup", fake_setup)
    monkeypatch.setattr(ProjectionPass, "setup", fake_setup)

    window.initializeGL()

    # The widget context (and its framebuffer) drives every GL consumer.
    assert attached == [window]
    assert created[0].ctx is window._ctx
    assert target_calls == [
        (window._target, window._ctx, window.defaultFramebufferObject())
    ]
    assert window._pass is not None
    assert window._pass.target is window._target
    assert window._projection_pass is not None
    assert window._projection_pass.target is window._target
    assert window._gl_ready


def test_clear_black_without_context_is_noop(window: GLOutputWindow) -> None:
    """The clear helper must never crash offscreen (no GL context)."""
    window._clear_black()


def test_focus_policy_allows_keyboard(window: GLOutputWindow) -> None:
    """Strong focus lets key events (ESC) reach the window."""
    assert window.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_show_full_screen_activates_and_focuses(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fullscreen must activate and focus the window so ESC is received."""
    activated: list[bool] = []
    focused: list[Qt.FocusReason] = []
    monkeypatch.setattr(window, "activateWindow", lambda: activated.append(True))
    monkeypatch.setattr(window, "setFocus", lambda reason: focused.append(reason))

    window.showFullScreen()

    assert activated == [True]
    assert focused == [Qt.FocusReason.ActiveWindowFocusReason]


def test_pattern_texture_rows_are_flipped(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asymmetric patterns must reach the GPU upright, not inverted.

    Image row 0 is the top of the pattern but texture v=0 maps to the
    bottom of the quad; the upload path flips rows so the projector
    shows the pattern the way it was generated.
    """
    source = np.zeros((4, 2, 4), dtype=np.uint8)
    source[0, :, :] = (255, 0, 0, 255)  # image top: red
    source[-1, :, :] = (0, 0, 255, 255)  # image bottom: blue
    uploaded: list[Any] = []

    def fake_from_array(
        ctx: object, array: object, components: int, filter: str
    ) -> Texture:
        uploaded.append(array)
        return cast(Texture, _FakeTexture())

    monkeypatch.setattr(
        "projectionai.hardware.patterns.pattern_to_rgba", lambda *_: source
    )
    monkeypatch.setattr(Texture, "from_array", fake_from_array)
    window._pass = cast(PatternPass, _FakePass())
    window._ctx = object()
    window.set_pattern(PatternKind.COLOUR_BARS)

    window._ensure_texture()

    assert len(uploaded) == 1
    array = uploaded[0]
    assert array.shape == (4, 2, 4)
    assert tuple(array[0, 0]) == (0, 0, 255, 255)  # image bottom -> v=0 (quad bottom)
    assert tuple(array[-1, 0]) == (255, 0, 0, 255)  # image top -> v=1 (quad top)


def test_black_texture_cache_survives_pattern_replacement(
    window: GLOutputWindow,
) -> None:
    """The cached black texture must never be released by replacements."""
    window._pass = cast(PatternPass, _FakePass())
    black_fake = _FakeTexture()
    pattern_fake = _FakeTexture()
    black = cast(Texture, black_fake)
    pattern = cast(Texture, pattern_fake)
    window._black_texture = black

    window._replace_texture(("black",), black)
    window._replace_texture(("pattern",), pattern)
    window._replace_texture(("black",), black)

    assert black_fake.releases == 0
    assert pattern_fake.releases == 1
    assert window._texture is black
    assert window._texture_key == ("black",)


# ---------------------------------------------------------------------------
# PROJECTION routing (Section 4)
# ---------------------------------------------------------------------------


def test_paint_routes_projection_to_projection_pass(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PROJECTION content must go through ProjectionPass.render(), not PatternPass."""
    fake_pp = _FakeProjectionPass()
    fake_pat = _FakePatternPass()
    fake_target = _FakeTarget()
    fake_mesh = _make_fake_mesh()
    fake_tex = _make_fake_tex()

    window._gl_ready = True
    window._ctx = object()
    window._projection_pass = cast(ProjectionPass, fake_pp)
    window._pass = cast(PatternPass, fake_pat)
    window._target = fake_target  # type: ignore[assignment]  # type: ignore[assignment]
    content = OutputContent.projection(warp_mesh=fake_mesh, source_texture=fake_tex)
    window.set_content(content)
    monkeypatch.setattr(window, "defaultFramebufferObject", lambda: 42)
    window.paintGL()

    # ProjectionPass must have been called
    assert len(fake_pp.rendered) == 1
    assert fake_pp.source_texture is fake_tex
    assert fake_pp.warp_mesh is fake_mesh
    # PatternPass must NOT have been called
    assert len(fake_pat.rendered) == 0


def test_paint_routes_pattern_to_pattern_pass(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PATTERN content must go through PatternPass.render(), not ProjectionPass."""
    fake_pp = _FakeProjectionPass()
    fake_pat = _FakePatternPass()
    fake_target = _FakeTarget()

    window._gl_ready = True
    window._ctx = object()
    window._projection_pass = cast(ProjectionPass, fake_pp)
    window._pass = cast(PatternPass, fake_pat)
    window._target = fake_target  # type: ignore[assignment]  # type: ignore[assignment]

    window.set_content(OutputContent.pattern(PatternKind.RED))
    monkeypatch.setattr(window, "defaultFramebufferObject", lambda: 42)
    # _ensure_texture needs a real ctx for texture creation; monkeypatch it
    monkeypatch.setattr(window, "_ensure_texture", lambda: None)
    window.paintGL()

    assert len(fake_pat.rendered) == 1
    assert len(fake_pp.rendered) == 0


def test_paint_routes_black_to_pattern_pass(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BLACK content must go through PatternPass (blackout path)."""
    fake_pp = _FakeProjectionPass()
    fake_pat = _FakePatternPass()
    fake_target = _FakeTarget()

    window._gl_ready = True
    window._ctx = object()
    window._projection_pass = cast(ProjectionPass, fake_pp)
    window._pass = cast(PatternPass, fake_pat)
    window._target = fake_target  # type: ignore[assignment]

    window.set_content(OutputContent.black())
    monkeypatch.setattr(window, "defaultFramebufferObject", lambda: 42)
    monkeypatch.setattr(window, "_ensure_texture", lambda: None)
    window.paintGL()

    assert len(fake_pat.rendered) == 1
    assert len(fake_pp.rendered) == 0


def test_paint_routes_freeze_to_pattern_pass(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FREEZE content must go through PatternPass (freeze path)."""
    fake_pp = _FakeProjectionPass()
    fake_pat = _FakePatternPass()
    fake_target = _FakeTarget()

    window._gl_ready = True
    window._ctx = object()
    window._projection_pass = cast(ProjectionPass, fake_pp)
    window._pass = cast(PatternPass, fake_pat)
    window._target = fake_target  # type: ignore[assignment]  # type: ignore[assignment]

    window.set_content(OutputContent.freeze())
    monkeypatch.setattr(window, "defaultFramebufferObject", lambda: 42)
    monkeypatch.setattr(window, "_ensure_texture", lambda: None)
    window.paintGL()

    assert len(fake_pat.rendered) == 1
    assert len(fake_pp.rendered) == 0


def test_paint_projection_without_texture_falls_back_to_black(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PROJECTION with missing texture → clear black (not crash)."""
    fake_pp = _FakeProjectionPass()
    fake_pat = _FakePatternPass()
    fake_target = _FakeTarget()

    window._gl_ready = True
    window._ctx = object()
    window._projection_pass = cast(ProjectionPass, fake_pp)
    window._pass = cast(PatternPass, fake_pat)
    window._target = fake_target  # type: ignore[assignment]  # type: ignore[assignment]

    # source_texture is None → black fallback
    content = OutputContent.projection(warp_mesh=_make_fake_mesh(), source_texture=None)
    window.set_content(content)
    monkeypatch.setattr(window, "defaultFramebufferObject", lambda: 42)
    monkeypatch.setattr(window, "_clear_black", lambda: None)
    window.paintGL()

    # ProjectionPass.render() NOT called (missing texture)
    assert len(fake_pp.rendered) == 0


def test_paint_refreshes_fbo_id_before_render(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """paintGL must refresh the target's FBO id from the current widget FBO."""
    fake_pp = _FakeProjectionPass()
    fake_pat = _FakePatternPass()
    fake_target = _FakeTarget()
    fbo_ids: list[int] = []

    original_set_fbo_id = _FakeTarget.set_fbo_id

    def tracking_set_fbo_id(self: Any, fbo_id: int) -> None:
        fbo_ids.append(fbo_id)
        original_set_fbo_id(self, fbo_id)

    _FakeTarget.set_fbo_id = tracking_set_fbo_id  # type: ignore[method-assign]

    try:
        window._gl_ready = True
        window._ctx = object()
        window._projection_pass = cast(ProjectionPass, fake_pp)
        window._pass = cast(PatternPass, fake_pat)
        window._target = fake_target  # type: ignore[assignment]

        window.set_content(OutputContent.black())
        monkeypatch.setattr(window, "defaultFramebufferObject", lambda: 99)
        monkeypatch.setattr(window, "_ensure_texture", lambda: None)
        window.paintGL()

        assert 99 in fbo_ids
    finally:
        _FakeTarget.set_fbo_id = original_set_fbo_id  # type: ignore[method-assign]


def test_resize_updates_projection_pass(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """resizeGL must resize both PatternPass and ProjectionPass."""
    fake_pp = _FakeProjectionPass()
    fake_pat = _FakePatternPass()
    fake_target = _FakeTarget()

    window._gl_ready = True
    window._ctx = object()
    window._projection_pass = cast(ProjectionPass, fake_pp)
    window._pass = cast(PatternPass, fake_pat)
    window._target = fake_target  # type: ignore[assignment]

    window.resizeGL(800, 600)

    assert len(fake_pat.resize_calls) == 1
    assert fake_pat.resize_calls[0] == (window._ctx, 800, 600)
    assert len(fake_pp.resize_calls) == 1
    assert fake_pp.resize_calls[0] == (window._ctx, 800, 600)
    assert len(fake_target.resize_calls) == 1
    assert fake_target.resize_calls[0] == (800, 600)


# ---------------------------------------------------------------------------
# FBO validation (Section 6)
# ---------------------------------------------------------------------------


def test_initialize_gl_uses_widget_default_fbo(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ScreenTarget must be created with widget's defaultFramebufferObject(), not FBO 0."""
    from projectionai.infrastructure.renderer.context import RenderContext
    from projectionai.infrastructure.renderer.render_target import ScreenTarget

    fbo_ids: list[int] = []

    def fake_from_widget(widget: object) -> _FakeContext:
        return _FakeContext()

    def fake_screen_target(
        _self: Any, ctx: Any, _width: int, _height: int, fbo_id: int = 0
    ) -> None:
        fbo_ids.append(fbo_id)

    def fake_setup(_self: Any, ctx: Any, _width: int, _height: int) -> None:
        pass

    monkeypatch.setattr(RenderContext, "from_widget", fake_from_widget)
    monkeypatch.setattr(ScreenTarget, "__init__", fake_screen_target)
    monkeypatch.setattr(PatternPass, "setup", fake_setup)
    monkeypatch.setattr(ProjectionPass, "setup", fake_setup)

    window.initializeGL()

    # ScreenTarget must receive the widget FBO (not a hardcoded 0)
    assert len(fbo_ids) == 1
    assert fbo_ids[0] == window.defaultFramebufferObject()
    # In offscreen mode defaultFramebufferObject() may be 0 — that's fine.
    # The contract is: ScreenTarget gets whatever the widget reports, not a
    # hardcoded constant.


def test_paint_always_refreshes_fbo_before_rendering(
    window: GLOutputWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """paintGL must call set_fbo_id with the current widget FBO every frame."""
    fake_pp = _FakeProjectionPass()
    fake_pat = _FakePatternPass()
    fake_target = _FakeTarget()
    set_fbo_calls: list[int] = []

    original_set_fbo_id = _FakeTarget.set_fbo_id

    def tracking_set_fbo_id(self: Any, fbo_id: int) -> None:
        set_fbo_calls.append(fbo_id)

    _FakeTarget.set_fbo_id = tracking_set_fbo_id  # type: ignore[method-assign]

    try:
        window._gl_ready = True
        window._ctx = object()
        window._projection_pass = cast(ProjectionPass, fake_pp)
        window._pass = cast(PatternPass, fake_pat)
        window._target = fake_target  # type: ignore[assignment]

        window.set_content(OutputContent.black())
        monkeypatch.setattr(window, "defaultFramebufferObject", lambda: 77)
        monkeypatch.setattr(window, "_ensure_texture", lambda: None)
        window.paintGL()

        assert set_fbo_calls == [77]
    finally:
        _FakeTarget.set_fbo_id = original_set_fbo_id  # type: ignore[method-assign]
