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
from projectionai.infrastructure.renderer.texture import Texture


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Return the process-wide QApplication (created once)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def window(qapp: QApplication) -> Iterator[GLOutputWindow]:
    win = GLOutputWindow()
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


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
    from projectionai.infrastructure.renderer.passes.pattern import PatternPass
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

    window.initializeGL()

    # The widget context (and its framebuffer) drives every GL consumer.
    assert attached == [window]
    assert created[0].ctx is window._ctx
    assert target_calls == [
        (window._target, window._ctx, window.defaultFramebufferObject())
    ]
    assert setup_calls == [(window._pass, window._ctx)]
    assert window._pass is not None
    assert window._pass.target is window._target
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
