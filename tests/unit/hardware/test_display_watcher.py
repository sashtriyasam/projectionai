"""Tests for the display watcher — background topology polling."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable

import pytest

from projectionai.hardware.display_manager import DisplayManager
from projectionai.hardware.display_watcher import DisplayWatcher
from projectionai.hardware.events import DisplaysRefreshed
from projectionai.infrastructure.display.mock_provider import MockDisplayProvider
from tests.conftest import FakeEventBus


async def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll until *predicate* returns True or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    pytest.fail("Timed out waiting for condition")


@pytest.fixture
async def watcher(
    event_bus: FakeEventBus,
) -> AsyncIterator[tuple[DisplayWatcher, DisplayManager, MockDisplayProvider]]:
    """Return a running DisplayWatcher over the mock topology."""
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    w = DisplayWatcher(event_bus, display_manager=dm, poll_interval_s=0.05)
    await w.initialize()
    yield w, dm, provider
    await w.shutdown()
    await dm.shutdown()


async def test_poll_interval_floor(watcher: object) -> None:
    w, _dm, _provider = watcher  # type: ignore[misc]
    assert w.poll_interval_s == 0.05


async def test_watcher_is_running_after_initialize(watcher: object) -> None:
    w, _dm, _provider = watcher  # type: ignore[misc]
    assert w.is_running


async def test_watcher_polls_topology(watcher: object) -> None:
    _w, _dm, provider = watcher  # type: ignore[misc]
    calls_before = provider.list_calls
    await _wait_for(lambda: provider.list_calls > calls_before)
    assert provider.list_calls > calls_before


async def test_watcher_emits_refreshed_heartbeats(watcher: object) -> None:
    w, _dm, _provider = watcher  # type: ignore[misc]
    event_bus = w.event_bus
    assert isinstance(event_bus, FakeEventBus)
    await _wait_for(
        lambda: any(isinstance(e, DisplaysRefreshed) for e in event_bus.emitted)
    )


async def test_shutdown_stops_loop(watcher: object) -> None:
    w, _dm, _provider = watcher  # type: ignore[misc]
    await w.shutdown()
    assert not w.is_running
