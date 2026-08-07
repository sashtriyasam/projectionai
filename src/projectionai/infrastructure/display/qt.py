"""Qt-based display enumeration and full-screen pattern projection.

Implements the display layer of the hardware validation workflow on top
of PySide6 (a hard dependency of the project):

- :func:`list_displays` enumerates connected screens via
  ``QGuiApplication.screens()``.
- :class:`QtPatternProjector` satisfies the :class:`PatternProjector`
  service contract: it shows a borderless, always-on-top window on the
  selected screen, renders a pattern image full-screen, and blanks the
  display on ``hide``.

The ``QApplication`` is created lazily on first use. On headless Linux
(no display server) the Qt ``offscreen`` platform plugin is selected so
enumeration/projection remain testable in CI.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from projectionai.core.errors import ProjectionAIError

_logger = logging.getLogger(__name__)


class DisplayError(ProjectionAIError):
    """Raised when display enumeration or pattern projection fails."""


@dataclass(frozen=True)
class DisplayInfo:
    """Metadata of a single connected display.

    Attributes:
        index: Zero-based index into the Qt screen list.
        name: Platform display name (may be an empty string).
        width: Display width in pixels.
        height: Display height in pixels.
        is_primary: Whether this is the primary display.
    """

    index: int
    name: str
    width: int
    height: int
    is_primary: bool

    def __post_init__(self) -> None:
        if self.index < 0:
            raise DisplayError(f"display index must be >= 0, got {self.index}")
        if self.width <= 0 or self.height <= 0:
            raise DisplayError(
                f"display size must be positive, got {self.width}x{self.height}"
            )

    @property
    def resolution(self) -> tuple[int, int]:
        """Return the display resolution as ``(width, height)``."""
        return (self.width, self.height)


def list_displays() -> list[DisplayInfo]:
    """Enumerate all connected displays.

    Returns:
        One :class:`DisplayInfo` per screen in Qt screen order (index 0
        is the primary display on typical setups).
    """
    qapp = _ensure_qapplication()
    screens = qapp.screens()
    primary = qapp.primaryScreen()
    displays: list[DisplayInfo] = []
    for index, screen in enumerate(screens):
        geometry = screen.geometry()
        displays.append(
            DisplayInfo(
                index=index,
                name=screen.name() or f"screen-{index}",
                width=geometry.width(),
                height=geometry.height(),
                is_primary=screen is primary,
            )
        )
    _logger.debug("Enumerated %d display(s)", len(displays))
    return displays


class QtPatternProjector:
    """Project patterns full-screen on a selected display via Qt.

    Implements the :class:`PatternProjector` service contract used by
    :class:`PatternCaptureSession`. The projection window is created
    lazily on the first ``show`` call and lives on the selected screen;
    ``hide`` blanks it with black.

    Args:
        screen_index: Index into :func:`list_displays` of the display to
            project onto. Defaults to ``0`` (the primary display).

    Raises:
        DisplayError: If *screen_index* is out of range.
    """

    def __init__(self, screen_index: int = 0) -> None:
        qapp = _ensure_qapplication()
        screens = qapp.screens()
        if not 0 <= screen_index < len(screens):
            raise DisplayError(
                f"screen_index {screen_index} out of range (0..{len(screens) - 1})"
            )
        self._screen = screens[screen_index]
        self._window: _ProjectionWindow | None = None

    @property
    def resolution(self) -> tuple[int, int]:
        """Native resolution of the target display as ``(width, height)``."""
        geometry = self._screen.geometry()
        return (geometry.width(), geometry.height())

    async def show(self, image: NDArray[np.uint8]) -> None:
        """Display *image* full-screen on the selected display.

        Args:
            image: 2D grayscale ``uint8`` pattern at the display's native
                resolution.

        Raises:
            DisplayError: If *image* is not 2D grayscale.
        """
        window = self._ensure_window()
        window.show_image(image)

    async def hide(self) -> None:
        """Blank the display (paint the projection window black)."""
        if self._window is not None:
            self._window.blank()

    def close(self) -> None:
        """Close and destroy the projection window, restoring the desktop."""
        if self._window is not None:
            self._window.close()
            self._window = None

    def _ensure_window(self) -> _ProjectionWindow:
        if self._window is None:
            self._window = _ProjectionWindow(self._screen)
        return self._window


class _ProjectionWindow:
    """Borderless, always-on-top, full-screen image display."""

    def __init__(self, screen: Any) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

        self._window = QWidget()
        self._window.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        geometry = screen.geometry()
        self._window.setGeometry(geometry)

        self._label = QLabel()
        self._label.setScaledContents(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self._window)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        self._window.show()
        handle = self._window.windowHandle()
        if handle is not None:
            handle.setScreen(screen)
        self._window.setGeometry(geometry)
        self._window.showFullScreen()

    def show_image(self, image: NDArray[np.uint8]) -> None:
        """Render *image* full-screen."""
        from PySide6.QtGui import QPixmap

        self._label.setPixmap(QPixmap.fromImage(_to_qimage(image)))
        self._window.showFullScreen()

    def blank(self) -> None:
        """Paint the window black (blank display)."""
        from PySide6.QtGui import QColor, QPixmap

        pixmap = QPixmap(1, 1)
        pixmap.fill(QColor(0, 0, 0))
        self._label.setPixmap(pixmap)

    def close(self) -> None:
        """Close the underlying window."""
        self._window.close()


def _to_qimage(image: NDArray[np.uint8]) -> Any:
    """Convert a 2D grayscale ``uint8`` image to an owned ``QImage``."""
    from PySide6.QtGui import QImage

    if image.ndim != 2:
        raise DisplayError(f"pattern image must be 2D grayscale, got {image.ndim}D")
    height, width = image.shape
    contiguous = np.ascontiguousarray(image)
    return QImage(
        contiguous.tobytes(),
        width,
        height,
        width,
        QImage.Format.Format_Grayscale8,
    )


def _ensure_qapplication() -> Any:
    """Return the process-wide ``QApplication``, creating one if needed.

    On headless Linux (no ``DISPLAY``/``WAYLAND_DISPLAY``) the Qt
    ``offscreen`` platform plugin is selected so display code remains
    runnable in CI and tests. Windows/macOS use the normal platform.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        return app

    if (
        sys.platform.startswith("linux")
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
    ):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    return QApplication([])
