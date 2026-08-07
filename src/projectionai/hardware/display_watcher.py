"""DisplayWatcher — continuous topology monitoring.

Polls :class:`DisplayManager.refresh` on an interval; the manager
emits the typed change and heartbeat events (:class:`DisplayConnected`,
:class:`DisplayResolutionChanged`, :class:`DisplaysRefreshed`, ...).
The watcher itself only triggers the scan and reports scan failures.

Runs as a background asyncio task; cancellation is clean on shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import override

from projectionai.core.events import EventBus
from projectionai.hardware.display_manager import DisplayManager
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)


class DisplayWatcher(Manager):
    """Periodically rescans the display topology."""

    def __init__(
        self,
        event_bus: EventBus,
        display_manager: DisplayManager,
        poll_interval_s: float = 1.0,
    ) -> None:
        super().__init__(event_bus)
        self._display_manager = display_manager
        self._poll_interval_s = max(0.05, poll_interval_s)
        self._task: asyncio.Task[None] | None = None

    @property
    def poll_interval_s(self) -> float:
        """Seconds between topology scans."""
        return self._poll_interval_s

    @property
    def is_running(self) -> bool:
        """True while the background loop is active."""
        return self._task is not None and not self._task.done()

    # -- Lifecycle ---------------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        self._task = asyncio.create_task(self._run(), name="display-watcher")

    @override
    async def _on_shutdown(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # -- Loop --------------------------------------------------------------

    async def _run(self) -> None:
        """Scan loop: refresh with failure backoff, sleep, repeat."""
        consecutive_failures = 0
        max_backoff_s = self._poll_interval_s * 16
        while True:
            try:
                await self._display_manager.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                consecutive_failures += 1
                _logger.exception("Display topology scan failed")
            else:
                consecutive_failures = 0
            if consecutive_failures:
                delay = min(
                    self._poll_interval_s * 2 ** (consecutive_failures - 1),
                    max_backoff_s,
                )
            else:
                delay = self._poll_interval_s
            await asyncio.sleep(delay)
