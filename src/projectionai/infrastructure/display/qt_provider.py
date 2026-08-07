"""Qt display provider — real hardware enumeration via QScreen.

Reads the platform's screen topology through ``QGuiApplication``
(Qt abstracts Windows / X11 / Wayland / macOS). Best-effort fields:

- name / manufacturer / model / serial: exposed by ``QScreen`` on most
  platforms (may be empty).
- connection type: not exposed by Qt — reported ``UNKNOWN``.
- supported modes: Qt only reports the current mode, so the current
  mode is the sole entry (mode switching is unsupported).

``identify`` flashes a fullscreen white window on the target screen for
a short moment — works on every platform Qt runs on.

Widget operations require a ``QGuiApplication``; when none exists (e.g.
headless bootstrap before the Qt app is created) the provider reports
no displays instead of crashing.
"""

from __future__ import annotations

import logging
from typing import ClassVar, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QApplication, QWidget

from projectionai.hardware.classifier import DEFAULT_CLASSIFIER
from projectionai.hardware.errors import DisplayNotFoundError
from projectionai.hardware.models import (
    DisplayCapabilities,
    DisplayConnection,
    DisplayInfo,
    DisplayMode,
    DisplayOrientation,
)
from projectionai.services.display import DisplayProvider

_logger = logging.getLogger(__name__)

_IDENTIFY_FLASH_MS = 350


class QtDisplayProvider(DisplayProvider):
    """Enumerates physical displays through Qt's ``QScreen`` API."""

    name: ClassVar[str] = "qt"

    def __init__(self) -> None:
        self._flash_windows: list[QWidget] = []

    # -- Provider API ------------------------------------------------------

    async def list_displays(self) -> list[DisplayInfo]:
        """Return the current screen topology (empty when no Qt app).

        Display ids are stable screen keys (serial, name, or index
        fallback), so ids survive screen reordering and hot-plug.
        """
        instance = QGuiApplication.instance()
        if instance is None:
            _logger.debug("No QGuiApplication — no displays reported")
            return []
        qapp = cast(QGuiApplication, instance)
        primary = qapp.primaryScreen()
        screens = qapp.screens()
        infos: list[DisplayInfo] = []
        for index, key in self._resolve_ids(qapp):
            infos.append(
                self._to_info(key, index, screens[index], screens[index] is primary)
            )
        return infos

    async def identify(self, display_id: str) -> None:
        """Flash a fullscreen white window on *display_id*.

        Widgets need a ``QApplication``; when the live instance is absent
        or only a ``QGuiApplication`` the operation is unsupported and
        skipped (no widget is created).
        """
        instance = QGuiApplication.instance()
        if not isinstance(instance, QApplication):
            _logger.debug("No QApplication — identify unsupported, skipped")
            return
        screen = self._screen_for(display_id)
        if screen is None:
            raise DisplayNotFoundError(f"Display not connected: {display_id!r}")
        flash = QWidget()
        flash.setStyleSheet("background-color: #FFFFFF;")
        flash.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        flash.setGeometry(screen.geometry())
        flash.showFullScreen()
        flash.raise_()
        self._flash_windows.append(flash)
        QTimer.singleShot(_IDENTIFY_FLASH_MS, flash.close)
        QTimer.singleShot(_IDENTIFY_FLASH_MS + 50, self._prune_flashes)
        _logger.info("Identifying display %s (%s)", display_id, screen.name())

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _to_info(
        display_id: str, index: int, screen: QScreen, is_primary: bool
    ) -> DisplayInfo:
        geometry = screen.geometry()
        current = DisplayMode(
            width=geometry.width(),
            height=geometry.height(),
            refresh_rate=float(screen.refreshRate()),
            color_depth=int(screen.depth()),
            scaling=float(screen.devicePixelRatio()),
        )
        info = DisplayInfo(
            display_id=display_id,
            index=index,
            name=screen.name() or f"Screen {index + 1}",
            manufacturer=screen.manufacturer() or "",
            model=screen.model() or "",
            serial_number=screen.serialNumber() or "",
            connection=DisplayConnection.UNKNOWN,
            is_primary=is_primary,
            orientation=QtDisplayProvider._orientation(screen),
            position=(geometry.x(), geometry.y()),
            current_mode=current,
            supported_modes=(current,),
            capabilities=DisplayCapabilities(
                supports_fullscreen=True,
                supports_identification=True,
                supports_mode_switching=False,
            ),
        )
        return DEFAULT_CLASSIFIER.reclassify(info)

    @staticmethod
    def _orientation(screen: QScreen) -> DisplayOrientation:
        orientation = screen.orientation()
        mapping = {
            Qt.ScreenOrientation.LandscapeOrientation: DisplayOrientation.LANDSCAPE,
            Qt.ScreenOrientation.PortraitOrientation: DisplayOrientation.PORTRAIT,
            Qt.ScreenOrientation.InvertedLandscapeOrientation: (
                DisplayOrientation.LANDSCAPE_FLIPPED
            ),
            Qt.ScreenOrientation.InvertedPortraitOrientation: (
                DisplayOrientation.PORTRAIT_FLIPPED
            ),
        }
        return mapping.get(orientation, DisplayOrientation.UNKNOWN)

    @staticmethod
    def _screen_key(screen: QScreen, index: int) -> str:
        """Stable key for a screen: serial, name, then index fallback."""
        serial = screen.serialNumber().strip()
        if serial:
            return f"qt-serial-{serial}"
        name = (screen.name() or "").strip()
        if name:
            return f"qt-name-{name}"
        return f"qt-index-{index}"

    def _resolve_ids(self, qapp: QGuiApplication) -> list[tuple[int, str]]:
        """Collision-free display ids for every screen, in enumerate order.

        The first screen claiming a serial/name key keeps it; later
        duplicates fall back to ``qt-index-{index}``. Enumeration
        (``list_displays``) and lookup (``_screen_for``) share this same
        mapping so every emitted id resolves back to its screen.
        """
        used: set[str] = set()
        resolved: list[tuple[int, str]] = []
        for index, screen in enumerate(qapp.screens()):
            key = self._screen_key(screen, index)
            if key in used:
                key = f"qt-index-{index}"
            used.add(key)
            resolved.append((index, key))
        return resolved

    def _screen_for(self, display_id: str) -> QScreen | None:
        """Resolve a provider display id to the live QScreen."""
        instance = QGuiApplication.instance()
        if instance is None:
            return None
        qapp = cast(QGuiApplication, instance)
        screens = qapp.screens()
        for index, key in self._resolve_ids(qapp):
            if key == display_id:
                return screens[index]
        return None

    def _require(self, display_id: str) -> DisplayInfo:
        """Return fresh metadata for the live QScreen behind *display_id*."""
        screen = self._screen_for(display_id)
        if screen is None:
            raise DisplayNotFoundError(f"Display not connected: {display_id!r}")
        qapp = cast(QGuiApplication, QGuiApplication.instance())
        return self._to_info(
            display_id,
            qapp.screens().index(screen),
            screen,
            screen is qapp.primaryScreen(),
        )

    def _prune_flashes(self) -> None:
        """Drop references to closed flash windows."""
        self._flash_windows = [w for w in self._flash_windows if w.isVisible()]
