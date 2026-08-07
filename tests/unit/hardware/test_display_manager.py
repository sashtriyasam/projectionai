"""Tests for the display manager — topology, events, routing, windows."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest

from projectionai.core.errors import ProjectionAIError
from projectionai.hardware.display_manager import DisplayManager
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
    DisplayKind,
    DisplayMode,
    DisplayOrientation,
)
from projectionai.infrastructure.display.mock_provider import (
    MockDisplayProvider,
    make_display,
)
from tests.conftest import FakeEventBus


async def _flush() -> None:
    """Yield control so fire-and-forget emit tasks can run."""
    await asyncio.sleep(0)


async def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll until *predicate* returns True or the timeout elapses."""
    deadline = __import__("time").monotonic() + timeout
    while __import__("time").monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    pytest.fail("Timed out waiting for condition")


@pytest.fixture
async def manager(
    event_bus: FakeEventBus,
) -> AsyncIterator[tuple[DisplayManager, MockDisplayProvider]]:
    """Return an initialized DisplayManager over the canonical mock topology."""
    provider = MockDisplayProvider()
    mgr = DisplayManager(event_bus, provider=provider)
    await mgr.initialize()
    yield mgr, provider
    await mgr.shutdown()


class FakeWindow:
    """Duck-typed OutputWindow that records geometry/fullscreen calls."""

    def __init__(self) -> None:
        self.geometry: tuple[int, int, int, int] | None = None
        self.fullscreen = False
        self.normal_calls = 0

    def setGeometry(self, x: int, y: int, w: int, h: int) -> None:  # noqa: N802 - Qt protocol name
        self.geometry = (x, y, w, h)

    def showFullScreen(self) -> None:  # noqa: N802 - Qt protocol name
        self.fullscreen = True

    def showNormal(self) -> None:  # noqa: N802 - Qt protocol name
        self.normal_calls += 1
        self.fullscreen = False


# -- Topology ---------------------------------------------------------------


async def test_initial_scan_loads_mock_topology(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    assert mgr.display_count == 3
    assert len(mgr.displays) == 3
    assert mgr.display_count == len(mgr.displays)


async def test_displays_sorted_by_index(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    indices = [d.index for d in mgr.displays]
    assert indices == sorted(indices)


async def test_projectors_filtered_by_kind(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    assert len(mgr.projectors) == 1
    assert mgr.projectors[0].display_id == "disp-2"
    assert mgr.projectors[0].kind is DisplayKind.PROJECTOR


async def test_primary_detected(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    assert mgr.primary is not None
    assert mgr.primary.display_id == "disp-1"
    assert mgr.primary.is_primary


async def test_get_and_has(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    assert mgr.has("disp-1")
    assert not mgr.has("ghost")
    info = mgr.get("disp-1")
    assert info.name == "Dell U2720Q"


async def test_get_unknown_raises(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    with pytest.raises(DisplayNotFoundError):
        mgr.get("ghost")
    with pytest.raises(ProjectionAIError):
        mgr.get("ghost")


# -- Change detection --------------------------------------------------------


async def test_refresh_emits_connect_event(manager: object) -> None:
    mgr, provider = manager  # type: ignore[misc]
    event_bus = mgr.event_bus
    assert isinstance(event_bus, FakeEventBus)
    event_bus.emitted.clear()
    provider.connect(make_display("disp-4", 3, "BenQ TH685", manufacturer="BenQ"))
    await mgr.refresh()
    await _flush()
    assert event_bus.assert_event_emitted(DisplayConnected) is None
    assert mgr.has("disp-4")


async def test_refresh_emits_disconnect_event(manager: object) -> None:
    mgr, provider = manager  # type: ignore[misc]
    event_bus = mgr.event_bus
    assert isinstance(event_bus, FakeEventBus)
    event_bus.emitted.clear()
    provider.disconnect("disp-3")
    await mgr.refresh()
    await _flush()
    assert event_bus.assert_event_emitted(DisplayDisconnected) is None
    assert not mgr.has("disp-3")


async def test_refresh_emits_resolution_change(manager: object) -> None:
    mgr, provider = manager  # type: ignore[misc]
    event_bus = mgr.event_bus
    assert isinstance(event_bus, FakeEventBus)
    event_bus.emitted.clear()
    old = provider.get("disp-1")
    changed = make_display(
        "disp-1",
        old.index,
        old.name,
        manufacturer=old.manufacturer,
        model=old.model,
        connection=old.connection,
        is_primary=old.is_primary,
        width=2560,
        height=1440,
    )
    provider.replace(changed)
    await mgr.refresh()
    await _flush()
    found = [e for e in event_bus.emitted if isinstance(e, DisplayResolutionChanged)]
    assert found
    assert found[0].old_mode.width == 3840
    assert found[0].new_mode.width == 2560


async def test_refresh_emits_refresh_rate_change(manager: object) -> None:
    mgr, provider = manager  # type: ignore[misc]
    event_bus = mgr.event_bus
    assert isinstance(event_bus, FakeEventBus)
    event_bus.emitted.clear()
    old = provider.get("disp-2")
    changed = make_display(
        "disp-2",
        old.index,
        old.name,
        manufacturer=old.manufacturer,
        model=old.model,
        connection=old.connection,
        width=1920,
        height=1200,
        refresh_rate=120.0,
    )
    provider.replace(changed)
    await mgr.refresh()
    await _flush()
    found = [e for e in event_bus.emitted if isinstance(e, DisplayRefreshRateChanged)]
    assert found
    assert found[0].old_rate == 60.0
    assert found[0].new_rate == 120.0


async def test_refresh_emits_orientation_change(manager: object) -> None:
    mgr, provider = manager  # type: ignore[misc]
    event_bus = mgr.event_bus
    assert isinstance(event_bus, FakeEventBus)
    event_bus.emitted.clear()
    old = provider.get("disp-3")
    changed = make_display(
        "disp-3",
        old.index,
        old.name,
        manufacturer=old.manufacturer,
        model=old.model,
        connection=old.connection,
        orientation=DisplayOrientation.PORTRAIT,
    )
    provider.replace(changed)
    await mgr.refresh()
    await _flush()
    found = [e for e in event_bus.emitted if isinstance(e, DisplayOrientationChanged)]
    assert found
    assert found[0].new_orientation is DisplayOrientation.PORTRAIT


async def test_refresh_emits_primary_change(manager: object) -> None:
    mgr, provider = manager  # type: ignore[misc]
    event_bus = mgr.event_bus
    assert isinstance(event_bus, FakeEventBus)
    event_bus.emitted.clear()
    # Exclusive handoff: demote disp-1 first so only disp-2 is primary after refresh.
    old_primary = provider.get("disp-1")
    demoted = make_display(
        "disp-1",
        old_primary.index,
        old_primary.name,
        manufacturer=old_primary.manufacturer,
        model=old_primary.model,
        connection=old_primary.connection,
        is_primary=False,
    )
    provider.replace(demoted)
    old = provider.get("disp-2")
    changed = make_display(
        "disp-2",
        old.index,
        old.name,
        manufacturer=old.manufacturer,
        model=old.model,
        connection=old.connection,
        is_primary=True,
    )
    provider.replace(changed)
    await mgr.refresh()
    await _flush()
    assert event_bus.assert_event_emitted(DisplayPrimaryChanged) is None
    assert mgr.primary is not None
    assert mgr.primary.display_id == "disp-2"


async def test_refresh_always_emits_refreshed(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    event_bus = mgr.event_bus
    assert isinstance(event_bus, FakeEventBus)
    event_bus.emitted.clear()
    await mgr.refresh()
    await _flush()
    found = [e for e in event_bus.emitted if isinstance(e, DisplaysRefreshed)]
    assert found
    assert found[0].count == 3


# -- Output routing ------------------------------------------------------------


async def test_set_live_output_emits_event(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    event_bus = mgr.event_bus
    assert isinstance(event_bus, FakeEventBus)
    mgr.set_live_output("disp-2")
    await _flush()
    assert event_bus.assert_event_emitted(DisplayLiveOutputChanged) is None
    assert mgr.live_output is not None
    assert mgr.live_output.display_id == "disp-2"


async def test_set_live_output_unknown_raises(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    with pytest.raises(DisplayNotFoundError):
        mgr.set_live_output("ghost")


async def test_set_preview_output_emits_event(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    event_bus = mgr.event_bus
    assert isinstance(event_bus, FakeEventBus)
    mgr.set_preview_output("disp-1")
    await _flush()
    assert event_bus.assert_event_emitted(DisplayPreviewOutputChanged) is None
    assert mgr.preview_output is not None
    assert mgr.preview_output.display_id == "disp-1"


async def test_dangling_live_output_cleared_on_refresh(manager: object) -> None:
    mgr, provider = manager  # type: ignore[misc]
    event_bus = mgr.event_bus
    assert isinstance(event_bus, FakeEventBus)
    mgr.set_live_output("disp-3")
    provider.disconnect("disp-3")
    await mgr.refresh()
    await _flush()
    assert mgr.live_output is None
    found = [e for e in event_bus.emitted if isinstance(e, DisplayLiveOutputChanged)]
    assert found and found[-1].display_id is None


# -- Display operations --------------------------------------------------------


async def test_identify_forwards_to_provider(manager: object) -> None:
    mgr, provider = manager  # type: ignore[misc]
    await mgr.identify("disp-1")
    assert provider.identify_calls == ["disp-1"]


async def test_identify_unknown_raises(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    with pytest.raises(DisplayNotFoundError):
        await mgr.identify("ghost")


async def test_get_modes_returns_supported(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    modes = await mgr.get_modes("disp-2")
    assert isinstance(modes, tuple)
    assert modes
    assert all(isinstance(m, DisplayMode) for m in modes)


# -- Window operations ----------------------------------------------------------


async def test_move_window_to_positions_on_display(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    window = FakeWindow()
    mgr.move_window_to("disp-1", window)
    assert window.geometry == (0, 0, 3840, 2160)


async def test_set_fullscreen_moves_and_shows(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    window = FakeWindow()
    mgr.set_fullscreen("disp-2", window)
    assert window.geometry is not None
    assert window.fullscreen


async def test_restore_window_exits_fullscreen(manager: object) -> None:
    mgr, _provider = manager  # type: ignore[misc]
    window = FakeWindow()
    mgr.set_fullscreen("disp-2", window)
    mgr.restore_window(window)
    assert not window.fullscreen
    assert window.normal_calls == 1
