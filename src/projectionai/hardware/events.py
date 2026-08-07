"""Typed hardware events — display topology and output state changes.

All events are frozen dataclasses deriving from :class:`Event` so they
flow through the shared :class:`EventBus` alongside application events.
Consumers (UI view models, validators, future multi-projector
coordination) subscribe by event type.
"""

from __future__ import annotations

from dataclasses import dataclass

from projectionai.core.events import Event
from projectionai.hardware.models import (
    DisplayInfo,
    DisplayMode,
    DisplayOrientation,
)

# ---------------------------------------------------------------------------
# Display topology events (emitted by DisplayManager / DisplayWatcher)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DisplaysRefreshed(Event):
    """Emitted after every topology scan, changed or not."""

    count: int


@dataclass(frozen=True)
class DisplayConnected(Event):
    """A display was detected for the first time."""

    display_id: str
    info: DisplayInfo


@dataclass(frozen=True)
class DisplayDisconnected(Event):
    """A previously known display disappeared."""

    display_id: str
    name: str


@dataclass(frozen=True)
class DisplayResolutionChanged(Event):
    """A display's current mode changed."""

    display_id: str
    old_mode: DisplayMode
    new_mode: DisplayMode


@dataclass(frozen=True)
class DisplayRefreshRateChanged(Event):
    """A display's refresh rate changed (same resolution)."""

    display_id: str
    old_rate: float
    new_rate: float


@dataclass(frozen=True)
class DisplayOrientationChanged(Event):
    """A display's orientation changed."""

    display_id: str
    old_orientation: DisplayOrientation
    new_orientation: DisplayOrientation


@dataclass(frozen=True)
class DisplayPrimaryChanged(Event):
    """The primary display changed."""

    display_id: str


# ---------------------------------------------------------------------------
# Output routing events (emitted by DisplayManager / OutputManager)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DisplayLiveOutputChanged(Event):
    """The live (program) output display changed."""

    display_id: str | None


@dataclass(frozen=True)
class DisplayPreviewOutputChanged(Event):
    """The preview output display changed."""

    display_id: str | None


# ---------------------------------------------------------------------------
# Output session events (emitted by OutputManager)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutputSessionStarted(Event):
    """A new output session began."""

    session_id: str
    preview_display_id: str | None = None


@dataclass(frozen=True)
class OutputSessionEnded(Event):
    """The active output session ended."""

    session_id: str


@dataclass(frozen=True)
class OutputPreviewChanged(Event):
    """The session's preview target changed."""

    session_id: str
    display_id: str | None


@dataclass(frozen=True)
class OutputArmed(Event):
    """The session was armed for live output (validated)."""

    session_id: str
    display_id: str | None


@dataclass(frozen=True)
class OutputLiveStarted(Event):
    """Program output went live on a display."""

    session_id: str
    display_id: str


@dataclass(frozen=True)
class OutputBlackout(Event):
    """Program output was blacked out (live cut off)."""

    session_id: str


# ---------------------------------------------------------------------------
# User-intent events (UI -> hardware)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentifyDisplayRequested(Event):
    """UI asked to flash/identify a display."""

    display_id: str
