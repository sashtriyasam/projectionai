"""Unit tests for the Qt-based display enumeration and projection.

Covers :class:`DisplayInfo` validation, :func:`list_displays`, and the
:class:`QtPatternProjector` show/hide cycle. The Qt ``offscreen`` platform
plugin is selected before the ``QApplication`` is created so the tests run
headless on every OS, including CI.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication

from projectionai.hardware.errors import DisplayNotFoundError
from projectionai.infrastructure.display import (
    DisplayError,
    DisplayInfo,
    QtPatternProjector,
    list_displays,
)
from projectionai.infrastructure.display.qt_provider import QtDisplayProvider


class TestDisplayInfo:
    def test_fields_and_resolution_property(self) -> None:
        display = DisplayInfo(
            index=2, name="projector", width=1920, height=1080, is_primary=False
        )
        assert display.index == 2
        assert display.name == "projector"
        assert display.width == 1920
        assert display.height == 1080
        assert display.is_primary is False
        assert display.resolution == (1920, 1080)

    def test_negative_index_raises(self) -> None:
        with pytest.raises(DisplayError, match="index"):
            DisplayInfo(
                index=-1, name="screen", width=800, height=600, is_primary=False
            )

    @pytest.mark.parametrize("width,height", [(0, 600), (800, 0), (-5, 600)])
    def test_non_positive_size_raises(self, width: int, height: int) -> None:
        with pytest.raises(DisplayError, match="size"):
            DisplayInfo(
                index=0, name="screen", width=width, height=height, is_primary=False
            )


class TestListDisplays:
    def test_returns_display_infos(self) -> None:
        displays = list_displays()
        assert displays
        assert all(isinstance(display, DisplayInfo) for display in displays)

    def test_indices_are_sequential(self) -> None:
        displays = list_displays()
        assert [display.index for display in displays] == list(range(len(displays)))

    def test_entries_are_valid(self) -> None:
        for display in list_displays():
            assert display.index >= 0
            assert display.width > 0
            assert display.height > 0

    def test_exactly_one_primary(self) -> None:
        displays = list_displays()
        assert sum(1 for display in displays if display.is_primary) == 1


class TestQtPatternProjector:
    def test_constructs_with_default_screen(self) -> None:
        projector = QtPatternProjector()
        assert projector.resolution[0] > 0
        assert projector.resolution[1] > 0

    def test_out_of_range_screen_index_raises(self) -> None:
        count = len(list_displays())
        with pytest.raises(DisplayError, match="screen_index"):
            QtPatternProjector(screen_index=count + 5)

    def test_resolution_matches_listed_display(self) -> None:
        display = list_displays()[0]
        projector = QtPatternProjector(screen_index=display.index)
        assert projector.resolution == (display.width, display.height)

    async def test_show_hide_cycle(self) -> None:
        projector = QtPatternProjector()
        pattern = np.zeros((480, 640), dtype=np.uint8)
        await projector.show(pattern)  # must not raise
        await projector.hide()  # must not raise
        projector.close()

    async def test_show_rejects_3d_image(self) -> None:
        projector = QtPatternProjector()
        color = np.zeros((480, 640, 3), dtype=np.uint8)
        with pytest.raises(DisplayError, match="2D"):
            await projector.show(color)

    async def test_hide_without_show_is_noop(self) -> None:
        projector = QtPatternProjector()
        await projector.hide()  # window not yet created: must not raise

    async def test_close_then_hide_is_noop(self) -> None:
        projector = QtPatternProjector()
        await projector.show(np.zeros((64, 64), dtype=np.uint8))
        projector.close()
        await projector.hide()  # window destroyed: must not raise


class _FakeScreen:
    """Minimal QScreen-shaped stub for screen-id collision tests."""

    def __init__(self, serial: str, name: str = "") -> None:
        self._serial = serial
        self._name = name

    def serialNumber(self) -> str:  # noqa: N802 - Qt API name
        return self._serial

    def name(self) -> str:
        return self._name

    def manufacturer(self) -> str:
        return ""

    def model(self) -> str:
        return ""

    def geometry(self) -> QRect:
        return QRect(0, 0, 1920, 1080)

    def refreshRate(self) -> float:  # noqa: N802 - Qt API name
        return 60.0

    def depth(self) -> int:
        return 32

    def devicePixelRatio(self) -> float:  # noqa: N802 - Qt API name
        return 1.0

    def orientation(self) -> Qt.ScreenOrientation:
        return Qt.ScreenOrientation.LandscapeOrientation


class _FakeApp:
    """Minimal QGuiApplication-shaped object exposing a screen list."""

    def __init__(self, screens: list[_FakeScreen]) -> None:
        self._screens = screens

    def screens(self) -> list[_FakeScreen]:
        return self._screens

    def primaryScreen(self) -> _FakeScreen | None:  # noqa: N802 - Qt API name
        return self._screens[0] if self._screens else None

    def processEvents(self) -> None:  # noqa: N802 - Qt API name
        """No-op: satisfies pytest-qt's post-test event processing hook."""


class TestQtDisplayProviderIdCollisions:
    """Id enumeration and lookup agree even with duplicate serial/name keys."""

    @staticmethod
    def _provider(
        screens: list[_FakeScreen], monkeypatch: pytest.MonkeyPatch
    ) -> QtDisplayProvider:
        app = _FakeApp(screens)
        provider = QtDisplayProvider()
        monkeypatch.setattr(QGuiApplication, "instance", staticmethod(lambda: app))
        return provider

    async def test_duplicate_serials_get_index_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = self._provider(
            [_FakeScreen("SERIAL-1"), _FakeScreen("SERIAL-1")], monkeypatch
        )
        displays = await provider.list_displays()
        assert [d.display_id for d in displays] == [
            "qt-serial-SERIAL-1",
            "qt-index-1",
        ]

    async def test_duplicate_names_get_index_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = self._provider(
            [_FakeScreen("", "Screen A"), _FakeScreen("", "Screen A")],
            monkeypatch,
        )
        displays = await provider.list_displays()
        assert [d.display_id for d in displays] == [
            "qt-name-Screen A",
            "qt-index-1",
        ]

    async def test_screen_for_resolves_index_fallback_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        screens = [_FakeScreen("SERIAL-1"), _FakeScreen("SERIAL-1")]
        provider = self._provider(screens, monkeypatch)

        # The collided screen was emitted as qt-index-1 — lookup must
        # resolve that id back to the second screen.
        assert provider._screen_for("qt-index-1") is screens[1]
        assert provider._screen_for("qt-serial-SERIAL-1") is screens[0]
        assert provider._screen_for("unknown-id") is None

    async def test_require_resolves_emitted_id_and_preserves_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = self._provider(
            [_FakeScreen("SERIAL-1"), _FakeScreen("SERIAL-1")], monkeypatch
        )
        info = provider._require("qt-index-1")
        assert info.display_id == "qt-index-1"
        with pytest.raises(DisplayNotFoundError):
            provider._require("qt-index-7")
