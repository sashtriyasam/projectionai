"""Tests for the hardware manager facade — aggregation and delegation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable

import pytest

from projectionai.hardware.display_manager import DisplayManager
from projectionai.hardware.display_validator import (
    DisplayValidator,
    ValidationReport,
)
from projectionai.hardware.display_watcher import DisplayWatcher
from projectionai.hardware.hardware_manager import HardwareManager
from projectionai.hardware.models import HardwareStatus
from projectionai.hardware.output_manager import OutputManager, OutputState
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
async def hardware(
    event_bus: FakeEventBus,
) -> AsyncIterator[tuple[HardwareManager, MockDisplayProvider]]:
    """Return an initialized HardwareManager over the mock topology."""
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    watcher = DisplayWatcher(event_bus, display_manager=dm, poll_interval_s=0.05)
    await watcher.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    hw = HardwareManager(
        event_bus,
        display_manager=dm,
        watcher=watcher,
        output_manager=om,
        validator=DisplayValidator(),
    )
    await hw.initialize()
    yield hw, provider
    await hw.shutdown()


# -- Topology -------------------------------------------------------------------


async def test_topology_properties(hardware: object) -> None:
    hw, _provider = hardware  # type: ignore[misc]
    assert hw.display_count == 3
    assert hw.projector_count == 1
    assert len(hw.displays) == 3
    assert len(hw.projectors) == 1
    assert hw.primary is not None
    assert hw.primary.is_primary


async def test_validate_returns_report(hardware: object) -> None:
    hw, _provider = hardware  # type: ignore[misc]
    report = hw.validate()
    assert isinstance(report, ValidationReport)
    assert report.is_ok


# -- Output session via facade ---------------------------------------------------


async def test_begin_output_session(hardware: object) -> None:
    hw, _provider = hardware  # type: ignore[misc]
    await hw.begin_output_session(preview_display_id="disp-1")
    assert hw.output_session is not None
    assert hw.output_state is OutputState.PREVIEW
    assert hw.preview_display_id == "disp-1"


async def test_arm_and_go_live_via_facade(hardware: object) -> None:
    hw, _provider = hardware  # type: ignore[misc]
    await hw.begin_output_session()
    report = await hw.arm_output()
    assert report.is_ok
    report = await hw.go_live()
    assert report.is_ok
    assert hw.is_live
    assert hw.live_display_id is not None


async def test_end_output_session(hardware: object) -> None:
    hw, _provider = hardware  # type: ignore[misc]
    await hw.begin_output_session()
    await hw.end_output_session()
    assert hw.output_session is None
    assert hw.output_state is OutputState.IDLE


async def test_identify_display_forwards(hardware: object) -> None:
    hw, provider = hardware  # type: ignore[misc]
    await hw.identify_display("disp-1")
    assert provider.identify_calls == ["disp-1"]


async def test_emergency_blackout_cuts_live(hardware: object) -> None:
    hw, _provider = hardware  # type: ignore[misc]
    await hw.begin_output_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    hw._output_manager.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await hw.arm_output()
    await hw.go_live()
    assert hw.is_live
    await hw.emergency_blackout()
    assert hw.output_state is OutputState.BLACKOUT
    assert not hw.is_live


async def test_emergency_blackout_without_session_is_noop(hardware: object) -> None:
    hw, _provider = hardware  # type: ignore[misc]
    await hw.emergency_blackout()
    assert hw.output_state is OutputState.IDLE


# -- Snapshot --------------------------------------------------------------------


async def test_snapshot_counts(hardware: object) -> None:
    hw, _provider = hardware  # type: ignore[misc]
    status = hw.snapshot()
    assert status.display_count == 3
    assert status.projector_count == 1
    assert status.monitor_count == 1
    assert status.virtual_count == 1
    assert status.unknown_count == 0
    assert status.healthy
    assert status.ready


async def test_snapshot_after_disconnect(hardware: object) -> None:
    hw, provider = hardware  # type: ignore[misc]
    provider.disconnect("disp-3")
    # The watcher applies topology changes asynchronously — poll until seen.
    await _wait_for(lambda: hw.display_count == 2)
    status = hw.snapshot()
    assert status.display_count == 2
    assert status.virtual_count == 0


async def test_snapshot_issue_count(hardware: object) -> None:
    hw, _provider = hardware  # type: ignore[misc]
    status = hw.snapshot()
    assert status.issue_count == 0


def test_summary_pluralizes_all_counts_but_one() -> None:
    assert HardwareStatus(display_count=0).summary == "0 displays"
    assert HardwareStatus(display_count=1).summary == "1 display"
    assert (
        HardwareStatus(display_count=2, projector_count=1).summary
        == "2 displays · 1 projector"
    )


def test_summary_omits_zero_non_display_counts() -> None:
    assert HardwareStatus(display_count=1).summary == "1 display"
    assert (
        HardwareStatus(
            display_count=3,
            projector_count=1,
            issue_count=1,
            warning_count=2,
        ).summary
        == "3 displays · 1 projector · 1 issue · 2 warnings"
    )
