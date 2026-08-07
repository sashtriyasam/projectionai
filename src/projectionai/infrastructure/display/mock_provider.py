"""Mock display provider — simulated hardware for tests and demos.

Simulates three displays: a primary monitor, a projector, and a virtual
display. Callers can mutate the simulated topology (connect /
disconnect / change modes) to exercise change-detection and watcher
paths without physical hardware.
"""

from __future__ import annotations

from typing import ClassVar

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


def make_display(
    display_id: str,
    index: int,
    name: str,
    *,
    manufacturer: str = "Acme",
    model: str = "Display",
    connection: DisplayConnection = DisplayConnection.HDMI,
    is_primary: bool = False,
    width: int = 1920,
    height: int = 1080,
    refresh_rate: float = 60.0,
    color_depth: int = 24,
    scaling: float = 1.0,
    position: tuple[int, int] = (0, 0),
    supported_modes: tuple[DisplayMode, ...] = (),
    orientation: DisplayOrientation = DisplayOrientation.LANDSCAPE,
) -> DisplayInfo:
    """Build a :class:`DisplayInfo` with the default classifier applied."""
    current = DisplayMode(
        width=width,
        height=height,
        refresh_rate=refresh_rate,
        color_depth=color_depth,
        scaling=scaling,
    )
    info = DisplayInfo(
        display_id=display_id,
        index=index,
        name=name,
        manufacturer=manufacturer,
        model=model,
        connection=connection,
        is_primary=is_primary,
        orientation=orientation,
        position=position,
        current_mode=current,
        supported_modes=supported_modes or (current,),
        capabilities=DisplayCapabilities(
            supports_fullscreen=True,
            supports_identification=True,
            supports_mode_switching=True,
        ),
    )
    return DEFAULT_CLASSIFIER.reclassify(info)


def default_displays() -> list[DisplayInfo]:
    """Return the canonical mock topology: monitor + projector + virtual."""
    return [
        make_display(
            "disp-1",
            0,
            "Dell U2720Q",
            manufacturer="Dell",
            model="U2720Q",
            connection=DisplayConnection.DISPLAY_PORT,
            is_primary=True,
            width=3840,
            height=2160,
            refresh_rate=60.0,
            scaling=1.5,
            position=(0, 0),
            supported_modes=(
                DisplayMode(3840, 2160, 60.0, 30, 1.5),
                DisplayMode(2560, 1440, 60.0, 24, 1.0),
                DisplayMode(1920, 1080, 60.0, 24, 1.0),
            ),
        ),
        make_display(
            "disp-2",
            1,
            "Epson EB-2250U",
            manufacturer="Epson",
            model="EB-2250U",
            connection=DisplayConnection.HDMI,
            width=1920,
            height=1200,
            refresh_rate=60.0,
            position=(3840, 0),
            supported_modes=(
                DisplayMode(1920, 1200, 60.0, 24, 1.0),
                DisplayMode(1280, 800, 60.0, 24, 1.0),
            ),
        ),
        make_display(
            "disp-3",
            2,
            "Virtual Display 1",
            manufacturer="",
            model="Virtual Display",
            connection=DisplayConnection.VIRTUAL,
            width=1920,
            height=1080,
            refresh_rate=30.0,
            position=(3840, 1200),
        ),
    ]


class MockDisplayProvider(DisplayProvider):
    """In-memory display topology that tests can mutate."""

    name: ClassVar[str] = "mock"

    def __init__(self, displays: list[DisplayInfo] | None = None) -> None:
        self._displays: dict[str, DisplayInfo] = {
            info.display_id: info
            for info in (default_displays() if displays is None else displays)
        }
        self.identify_calls: list[str] = []
        self.list_calls: int = 0

    # -- Provider API ------------------------------------------------------

    async def list_displays(self) -> list[DisplayInfo]:
        """Return the current simulated topology."""
        self.list_calls += 1
        return list(self._displays.values())

    async def get_modes(self, display_id: str) -> tuple[DisplayMode, ...]:
        self._require(display_id)
        return self._displays[display_id].supported_modes

    async def identify(self, display_id: str) -> None:
        """Record an identify request (simulated flash)."""
        self._require(display_id)
        self.identify_calls.append(display_id)

    def capabilities(self, display_id: str) -> DisplayCapabilities:
        self._require(display_id)
        return self._displays[display_id].capabilities

    # -- Topology mutation (test helpers) -----------------------------------

    def get(self, display_id: str) -> DisplayInfo:
        """Return the current info for *display_id*."""
        return self._require(display_id)

    def connect(self, info: DisplayInfo) -> None:
        """Add *info* to the simulated topology."""
        self._displays[info.display_id] = info

    def disconnect(self, display_id: str) -> None:
        """Remove *display_id* from the simulated topology."""
        self._displays.pop(display_id, None)

    def replace(self, info: DisplayInfo) -> None:
        """Replace *info.display_id* (mode changes, reconnects)."""
        self._displays[info.display_id] = info

    def _require(self, display_id: str) -> DisplayInfo:
        if display_id not in self._displays:
            raise DisplayNotFoundError(f"Display not connected: {display_id!r}")
        return self._displays[display_id]
