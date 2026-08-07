"""DisplayManager — single source of truth for the display topology.

Owns the current set of connected displays (fresh from a
:class:`DisplayProvider`), detects changes between scans, emits typed
events for every topology change, and tracks which display is the live
(program) output and which is the preview output.

Window operations (move / fullscreen / restore) are provided here as
pure geometry drivers through the structural :class:`OutputWindow`
protocol, keeping the layer Qt-free.
"""

from __future__ import annotations

import asyncio
import logging
from typing import override

from projectionai.core.events import EventBus
from projectionai.hardware.errors import DisplayNotFoundError
from projectionai.hardware.events import (
    DisplayConnected,
    DisplayDisconnected,
    DisplayLiveOutputChanged,
    DisplayOrientationChanged,
    DisplayPreviewOutputChanged,
    DisplayPrimaryChanged,
    DisplayRefreshRateChanged,
    DisplayResolutionChanged,
    DisplaysRefreshed,
)
from projectionai.hardware.models import (
    DisplayInfo,
    DisplayKind,
    DisplayMode,
    OutputWindow,
)
from projectionai.managers import Manager
from projectionai.services.display import (
    DisplayProvider,
    DisplayProviderFactory,
)

_logger = logging.getLogger(__name__)


class DisplayManager(Manager):
    """Tracks connected displays and the live/preview output routing."""

    def __init__(
        self,
        event_bus: EventBus,
        provider: DisplayProvider | None = None,
    ) -> None:
        super().__init__(event_bus)
        self._provider: DisplayProvider = provider or DisplayProviderFactory.create(
            "mock"
        )
        self._displays: dict[str, DisplayInfo] = {}
        self._live_output_id: str | None = None
        self._preview_output_id: str | None = None
        self._refresh_lock = asyncio.Lock()

    # -- Lifecycle ---------------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        """Perform the first topology scan."""
        await self.refresh()

    @override
    async def _on_shutdown(self) -> None:
        """Release topology state."""
        self._displays.clear()
        self._live_output_id = None
        self._preview_output_id = None

    # -- Topology ----------------------------------------------------------

    @property
    def provider(self) -> DisplayProvider:
        """Return the underlying display provider."""
        return self._provider

    @property
    def displays(self) -> tuple[DisplayInfo, ...]:
        """All currently connected displays, in index order."""
        return tuple(sorted(self._displays.values(), key=lambda d: d.index))

    @property
    def display_count(self) -> int:
        """Number of connected displays."""
        return len(self._displays)

    @property
    def projectors(self) -> tuple[DisplayInfo, ...]:
        """Displays classified as projectors."""
        return tuple(d for d in self.displays if d.kind is DisplayKind.PROJECTOR)

    @property
    def primary(self) -> DisplayInfo | None:
        """The primary display, if any."""
        return next((d for d in self.displays if d.is_primary), None)

    def get(self, display_id: str) -> DisplayInfo:
        """Return *display_id* or raise :class:`DisplayNotFoundError`."""
        info = self._displays.get(display_id)
        if info is None:
            raise DisplayNotFoundError(f"Display not connected: {display_id!r}")
        return info

    def has(self, display_id: str) -> bool:
        """True when *display_id* is currently connected."""
        return display_id in self._displays

    async def refresh(self) -> tuple[DisplayInfo, ...]:
        """Re-scan the topology and emit change events.

        Detects connects, disconnects, and mode/refresh/orientation/
        primary changes, emitting one typed event per change. If the
        live or preview output disappeared, they are cleared (and an
        event emitted) rather than left dangling. Concurrent scans are
        serialized so each diff runs against the previous scan's state.
        """
        self._require_initialized()
        async with self._refresh_lock:
            return await self._refresh_locked()

    async def _refresh_locked(self) -> tuple[DisplayInfo, ...]:
        """Scan, diff, update, and emit — callers must hold the lock."""
        current = await self._provider.list_displays()
        fresh = {info.display_id: info for info in current}
        previous = self._displays

        for display_id, info in fresh.items():
            if display_id not in previous:
                self._emit_nowait(DisplayConnected(display_id, info))
                _logger.info("Display connected: %s (%s)", display_id, info.name)

        for display_id, old in previous.items():
            if display_id not in fresh:
                self._emit_nowait(DisplayDisconnected(display_id, old.name))
                _logger.info("Display disconnected: %s (%s)", display_id, old.name)

        for display_id, new in fresh.items():
            old_info = previous.get(display_id)
            if old_info is None:
                continue
            if old_info.current_mode.resolution != new.current_mode.resolution:
                self._emit_nowait(
                    DisplayResolutionChanged(
                        display_id, old_info.current_mode, new.current_mode
                    )
                )
            elif old_info.current_mode.refresh_rate != new.current_mode.refresh_rate:
                self._emit_nowait(
                    DisplayRefreshRateChanged(
                        display_id,
                        old_info.current_mode.refresh_rate,
                        new.current_mode.refresh_rate,
                    )
                )
            if old_info.orientation != new.orientation:
                self._emit_nowait(
                    DisplayOrientationChanged(
                        display_id, old_info.orientation, new.orientation
                    )
                )
            if old_info.is_primary != new.is_primary:
                self._emit_nowait(DisplayPrimaryChanged(display_id))

        self._displays = fresh

        # Clear dangling output routes.
        if self._live_output_id is not None and not self.has(self._live_output_id):
            self._live_output_id = None
            self._emit_nowait(DisplayLiveOutputChanged(None))
        if self._preview_output_id is not None and not self.has(
            self._preview_output_id
        ):
            self._preview_output_id = None
            self._emit_nowait(DisplayPreviewOutputChanged(None))

        self._emit_nowait(DisplaysRefreshed(len(fresh)))
        return self.displays

    # -- Output routing ----------------------------------------------------

    @property
    def live_output(self) -> DisplayInfo | None:
        """The display receiving program (live) output."""
        if self._live_output_id is None:
            return None
        return self._displays.get(self._live_output_id)

    @property
    def preview_output(self) -> DisplayInfo | None:
        """The display receiving preview output."""
        if self._preview_output_id is None:
            return None
        return self._displays.get(self._preview_output_id)

    def set_live_output(self, display_id: str | None) -> None:
        """Route live output to *display_id* (``None`` = unroute)."""
        self._require_initialized()
        if display_id is not None:
            self.get(display_id)  # raises when unknown
        if self._live_output_id != display_id:
            self._live_output_id = display_id
            self._emit_nowait(DisplayLiveOutputChanged(display_id))

    def set_preview_output(self, display_id: str | None) -> None:
        """Route preview output to *display_id* (``None`` = unroute)."""
        self._require_initialized()
        if display_id is not None:
            self.get(display_id)  # raises when unknown
        if self._preview_output_id != display_id:
            self._preview_output_id = display_id
            self._emit_nowait(DisplayPreviewOutputChanged(display_id))

    # -- Display operations ------------------------------------------------

    async def identify(self, display_id: str) -> None:
        """Flash/identify *display_id* on the physical hardware."""
        self.get(display_id)  # raises when unknown
        await self._provider.identify(display_id)

    async def get_modes(self, display_id: str) -> tuple[DisplayMode, ...]:
        """Return the selectable modes for *display_id*."""
        self.get(display_id)  # raises when unknown
        return await self._provider.get_modes(display_id)

    # -- Window operations -------------------------------------------------

    def move_window_to(self, display_id: str, window: OutputWindow) -> None:
        """Move *window* onto *display_id* (windowed, its native size)."""
        info = self.get(display_id)
        width, height = info.current_mode.width, info.current_mode.height
        window.setGeometry(info.position[0], info.position[1], width, height)

    def set_fullscreen(self, display_id: str, window: OutputWindow) -> None:
        """Move *window* onto *display_id* and enter fullscreen."""
        self.move_window_to(display_id, window)
        window.showFullScreen()

    def restore_window(self, window: OutputWindow) -> None:
        """Exit fullscreen on *window*."""
        window.showNormal()
