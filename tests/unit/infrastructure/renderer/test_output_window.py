"""Tests for GLOutputWindow (offscreen Qt; no real GL required).

The window never assumes a working GPU: GL failures degrade to a black
window, so every assertion here targets non-GL behaviour (content model,
window flags, cursor, ESC signal, ``OutputWindow`` protocol methods).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
