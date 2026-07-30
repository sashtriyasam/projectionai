"""Shared fixtures for manager tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from projectionai.core.events import Event, EventBus, EventHandler


class FakeEventBus(EventBus):
    """A minimal event bus for testing.

    Records every emitted event in ``self.emitted`` for later
    assertion.  ``emit`` is a real async function so it works
    correctly with ``asyncio.run_coroutine_threadsafe`` from
    background threads.
    """

    def __init__(self) -> None:
        self.emitted: list[Any] = []
        self._clear_mock = AsyncMock()

    async def emit(self, event: Any) -> None:
        """Record an emitted event synchronously."""
        self.emitted.append(event)

    def subscribe(self, event_type: type[Event], listener: EventHandler) -> None:
        """No-op stub — tests assert via ``emitted`` instead."""
        return None

    def unsubscribe(self, event_type: type[Event], listener: EventHandler) -> None:
        """No-op stub — tests assert via ``emitted`` instead."""
        return None

    async def clear(self) -> None:
        """Clear all emitted events."""
        self.emitted.clear()
        await self._clear_mock()

    def assert_event_emitted(self, event_type: type) -> None:
        """Assert that at least one event of *event_type* was emitted."""
        for ev in self.emitted:
            if isinstance(ev, event_type):
                return
        pytest.fail(f"Expected {event_type.__name__} to be emitted")

    def assert_events_emitted(self, *event_types: type) -> None:
        """Assert that events of the given types were emitted in order."""
        idx = 0
        for expected in event_types:
            while idx < len(self.emitted):
                if isinstance(self.emitted[idx], expected):
                    break
                idx += 1
            else:
                pytest.fail(
                    f"Expected {expected.__name__} to be emitted "
                    f"(checked {len(self.emitted)} events)"
                )
            idx += 1


@pytest.fixture
def event_bus() -> FakeEventBus:
    """Return a ``FakeEventBus`` for manager tests."""
    return FakeEventBus()
