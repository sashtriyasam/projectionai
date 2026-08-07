"""Hardware domain models — displays, modes, and hardware status.

Qt-free data structures that describe physical display devices and the
projection output state. Providers (``infrastructure.display``) produce
these models; managers (``hardware``) consume them; the UI reads them
through view models.

The subsystem becomes the single source of truth for every connected
display, projector and camera. ``DisplayInfo`` here is deliberately
richer than the legacy ``infrastructure.display.DisplayInfo`` used by
the calibration workflow — that type remains untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DisplayKind(StrEnum):
    """Classification of a display device.

    Extensible: providers or classifier rules can introduce new kinds
    by subclassing :class:`hardware.classifier.DisplayClassifier`.
    """

    MONITOR = "monitor"
    PROJECTOR = "projector"
    VIRTUAL = "virtual"
    UNKNOWN = "unknown"


class DisplayConnection(StrEnum):
    """Physical/virtual connection type of a display.

    Best-effort: many platforms expose no reliable connection type
    (Qt included), in which case providers report ``UNKNOWN``.
    """

    HDMI = "hdmi"
    DISPLAY_PORT = "display_port"
    VGA = "vga"
    DVI = "dvi"
    USB_C = "usb_c"
    THUNDERBOLT = "thunderbolt"
    WIRELESS = "wireless"
    VIRTUAL = "virtual"
    UNKNOWN = "unknown"


class DisplayOrientation(StrEnum):
    """Screen orientation as reported by the platform."""

    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    LANDSCAPE_FLIPPED = "landscape_flipped"
    PORTRAIT_FLIPPED = "portrait_flipped"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Display data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DisplayMode:
    """A single video mode (resolution + timing) a display can run."""

    width: int
    height: int
    refresh_rate: float = 60.0
    color_depth: int = 24
    scaling: float = 1.0

    @property
    def label(self) -> str:
        """Human-readable mode label, e.g. ``"1920x1080 @ 60 Hz"``."""
        return f"{self.width}x{self.height} @ {self.refresh_rate:.0f} Hz"

    @property
    def resolution(self) -> tuple[int, int]:
        """Return ``(width, height)``."""
        return (self.width, self.height)


@dataclass(frozen=True)
class DisplayCapabilities:
    """Capabilities a provider reports for one display."""

    supports_fullscreen: bool = True
    supports_identification: bool = False
    supports_mode_switching: bool = False
    supports_hdr: bool = False


@dataclass(frozen=True)
class DisplayInfo:
    """Full static + current-state description of a display device.

    ``display_id`` is the opaque, provider-stable unique identifier
    used by every manager API. ``current_mode`` reflects the mode the
    display runs right now; ``supported_modes`` lists what the platform
    reports as selectable (may contain only the current mode when the
    platform cannot enumerate modes).
    """

    display_id: str
    index: int
    name: str
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    connection: DisplayConnection = DisplayConnection.UNKNOWN
    is_primary: bool = False
    kind: DisplayKind = DisplayKind.UNKNOWN
    orientation: DisplayOrientation = DisplayOrientation.UNKNOWN
    position: tuple[int, int] = (0, 0)  # screen-space origin (x, y)
    current_mode: DisplayMode = field(default_factory=lambda: DisplayMode(1920, 1080))
    supported_modes: tuple[DisplayMode, ...] = ()
    capabilities: DisplayCapabilities = field(default_factory=DisplayCapabilities)

    @property
    def mode_label(self) -> str:
        """Label of the current mode, e.g. ``"1920x1080 @ 60 Hz"``."""
        return self.current_mode.label

    @property
    def resolution(self) -> tuple[int, int]:
        """Return the current ``(width, height)``."""
        return self.current_mode.resolution

    @property
    def is_projector(self) -> bool:
        """True when classified as a projector."""
        return self.kind is DisplayKind.PROJECTOR

    @property
    def is_virtual(self) -> bool:
        """True when classified as a virtual display."""
        return self.kind is DisplayKind.VIRTUAL


# ---------------------------------------------------------------------------
# Hardware status
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HardwareStatus:
    """Aggregated hardware health snapshot (Qt-free, computed on demand)."""

    display_count: int = 0
    projector_count: int = 0
    monitor_count: int = 0
    virtual_count: int = 0
    unknown_count: int = 0
    issue_count: int = 0
    warning_count: int = 0

    @property
    def healthy(self) -> bool:
        """True when no errors are present."""
        return self.issue_count == 0

    @property
    def ready(self) -> bool:
        """True when at least one display is present and healthy."""
        return self.display_count > 0 and self.healthy

    @property
    def summary(self) -> str:
        """Short human-readable summary for status bars / panels."""

        def _counted(count: int, noun: str) -> str:
            return f"{count} {noun}{'s' if count != 1 else ''}"

        parts = [_counted(self.display_count, "display")]
        if self.projector_count:
            parts.append(_counted(self.projector_count, "projector"))
        if self.issue_count:
            parts.append(_counted(self.issue_count, "issue"))
        if self.warning_count:
            parts.append(_counted(self.warning_count, "warning"))
        return " · ".join(parts)


# ---------------------------------------------------------------------------
# Window target (structural protocol — Qt-free)
# ---------------------------------------------------------------------------


class OutputWindow(Protocol):
    """Anything a window operation can drive.

    :class:`QWidget` satisfies this protocol structurally; keeping the
    protocol here keeps the hardware layer free of Qt imports.
    """

    def setGeometry(self, x: int, y: int, w: int, h: int) -> None: ...  # noqa: N802 - Qt protocol name
    def showFullScreen(self) -> None: ...  # noqa: N802 - Qt protocol name
    def showNormal(self) -> None: ...  # noqa: N802 - Qt protocol name
