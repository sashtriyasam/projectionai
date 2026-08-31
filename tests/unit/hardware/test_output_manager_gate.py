"""Tests for OutputManager gate integration (7.11 Steps 6-7).

Verifies:
- OutputManager with ValidationGate configured evaluates gate on arm/go_live
- OutputManager without ValidationGate (legacy behavior) still works
- set_calibration_context wires cal/hardware_pending/source into gate
- gate_result property returns the last evaluation
- can_arm/can_live reflect gate authorization
- arm() respects gate: rejects when gate says NO
- go_live() respects gate: rejects when gate says NO
- gate result carries through when arm succeeds
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from projectionai.calibration.validator import (
    ValidationReport as CalValidationReport,
)
from projectionai.calibration.validation_gate import (
    ValidationGate,
    ValidationGateResult,
    AuthorizationLevel,
)
from projectionai.hardware.display_manager import DisplayManager
from projectionai.hardware.errors import LiveNotAuthorizedError, OutputSwitchError
from projectionai.hardware.output_manager import OutputManager, OutputState
from projectionai.infrastructure.display.mock_provider import (
    MockDisplayProvider,
    make_display,
)
from tests.conftest import FakeEventBus


async def _flush() -> None:
    await asyncio.sleep(0)


@pytest.fixture
async def gate_output_manager(
    event_bus: FakeEventBus,
) -> AsyncIterator[tuple[OutputManager, DisplayManager, MockDisplayProvider]]:
    """OutputManager WITH a ValidationGate configured."""
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(
        event_bus,
        display_manager=dm,
        validation_gate=ValidationGate(),
    )
    await om.initialize()
    yield om, dm, provider
    await om.shutdown()
    await dm.shutdown()


@pytest.fixture
async def legacy_output_manager(
    event_bus: FakeEventBus,
) -> AsyncIterator[tuple[OutputManager, DisplayManager, MockDisplayProvider]]:
    """OutputManager WITHOUT a ValidationGate (legacy behavior)."""
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    yield om, dm, provider
    await om.shutdown()
    await dm.shutdown()


# ---------------------------------------------------------------------------
# Basic gate integration
# ---------------------------------------------------------------------------


class TestOutputManagerGateInit:
    def test_no_gate_by_default(self, legacy_output_manager: object) -> None:
        om, _, _ = legacy_output_manager  # type: ignore[misc]
        assert om.gate_result is None
        assert om.can_arm is True  # legacy: no gate = always True
        assert om.can_live is True


class TestSetCalibrationContext:
    async def test_sets_context(self, gate_output_manager: object) -> None:
        om, _, _ = gate_output_manager  # type: ignore[misc]
        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal,
            hardware_pending=("V-05_lens",),
            source_mode="LIVE",
        )
        # Assert context stored correctly via private attributes
        assert om._calibration_report is cal
        assert om._hardware_pending == ("V-05_lens",)
        assert om._source_mode == "LIVE"

    async def test_normalizes_source_mode(self, gate_output_manager: object) -> None:
        om, _, _ = gate_output_manager  # type: ignore[misc]
        om.set_calibration_context(source_mode="synthetic")
        assert om._source_mode == "SYNTHETIC"

    async def test_invalid_source_mode_defaults_synthetic(
        self, gate_output_manager: object
    ) -> None:
        om, _, _ = gate_output_manager  # type: ignore[misc]
        om.set_calibration_context(source_mode="INVALID")
        assert om._source_mode == "SYNTHETIC"


class TestGateResultProperty:
    async def test_none_before_first_run(self, gate_output_manager: object) -> None:
        om, _, _ = gate_output_manager  # type: ignore[misc]
        assert om.gate_result is None

    async def test_set_after_arm(self, gate_output_manager: object) -> None:
        om, dm, provider = gate_output_manager  # type: ignore[misc]
        # Use LIVE source + all passing calibration so gate authorizes ARM
        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal, hardware_pending=(), source_mode="LIVE"
        )
        session = await om.begin_session(preview_display_id="disp-1")
        await om.set_live_target("disp-2")
        await om.arm()
        assert om.gate_result is not None
        assert isinstance(om.gate_result, ValidationGateResult)
        await om.end_session()


# ---------------------------------------------------------------------------
# Arm gate integration
# ---------------------------------------------------------------------------


class TestArmGateIntegration:
    async def test_arm_passes_when_gate_authorizes(
        self, gate_output_manager: object
    ) -> None:
        om, dm, provider = gate_output_manager  # type: ignore[misc]
        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal, hardware_pending=(), source_mode="LIVE"
        )
        await om.begin_session(preview_display_id="disp-1")
        await om.set_live_target("disp-2")
        report = await om.arm()
        assert om.state is OutputState.ARMED
        assert om.gate_result is not None
        assert om.gate_result.can_arm
        await om.end_session()

    async def test_arm_blocked_when_gate_fails_no_calibration(
        self, gate_output_manager: object
    ) -> None:
        """Without calibration report, gate V-01 fails → gate blocks arm."""
        om, dm, provider = gate_output_manager  # type: ignore[misc]
        # No calibration context set — gate will fail V-01
        await om.begin_session(preview_display_id="disp-1")
        await om.set_live_target("disp-2")
        report = await om.arm()
        # Display validation passes but gate blocks: state stays PREVIEW
        # (arm() returns report, doesn't raise — the caller checks report)
        # Actually looking at arm() code: it only transitions if report.is_ok AND gate_ok
        # When gate_ok=False, it doesn't transition
        assert om.state is OutputState.PREVIEW
        assert om.gate_result is not None
        assert not om.gate_result.can_arm
        await om.end_session()

    async def test_hardware_pending_allows_arm_blocks_live(
        self, gate_output_manager: object
    ) -> None:
        """Hardware pending → arm ALLOWED, live blocked."""
        om, dm, provider = gate_output_manager  # type: ignore[misc]
        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal,
            hardware_pending=("V-05_lens_distortion",),
            source_mode="LIVE",
        )
        await om.begin_session(preview_display_id="disp-1")
        await om.set_live_target("disp-2")
        await om.arm()
        # ARM should succeed (hardware pending doesn't block arm)
        assert om.state is OutputState.ARMED
        assert om.gate_result is not None
        assert om.gate_result.can_arm
        assert om.gate_result.can_preview
        # But LIVE should be blocked
        assert not om.gate_result.can_live
        await om.end_session()

    async def test_arm_blocked_with_synthetic_source(
        self, gate_output_manager: object
    ) -> None:
        """SYNTHETIC source → gate caps at PREVIEW → arm blocked."""
        om, dm, provider = gate_output_manager  # type: ignore[misc]
        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal, hardware_pending=(), source_mode="SYNTHETIC"
        )
        await om.begin_session(preview_display_id="disp-1")
        await om.set_live_target("disp-2")
        await om.arm()
        assert om.state is OutputState.PREVIEW
        await om.end_session()


# ---------------------------------------------------------------------------
# go_live gate integration
# ---------------------------------------------------------------------------


class TestGoLiveGateIntegration:
    async def test_go_live_blocked_when_gate_not_live(
        self, gate_output_manager: object
    ) -> None:
        """Hardware pending blocks LIVE but allows ARM (context changed after arm)."""
        om, dm, provider = gate_output_manager  # type: ignore[misc]
        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal,
            hardware_pending=(),
            source_mode="LIVE",
        )
        await om.begin_session(preview_display_id="disp-1")
        await om.set_live_target("disp-2")
        await om.arm()
        # Change context to block LIVE after arm
        om.set_calibration_context(
            calibration_report=cal,
            hardware_pending=("V-05_lens",),
            source_mode="LIVE",
        )
        with pytest.raises(LiveNotAuthorizedError):
            await om.go_live()
        assert om.state is OutputState.ARMED
        await om.end_session()

    async def test_go_live_blocked_when_hardware_pending(
        self, gate_output_manager: object
    ) -> None:
        """Hardware pending at arm time → arm ALLOWED, live BLOCKED."""
        om, dm, provider = gate_output_manager  # type: ignore[misc]
        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal,
            hardware_pending=("V-05_lens",),
            source_mode="LIVE",
        )
        await om.begin_session(preview_display_id="disp-1")
        await om.set_live_target("disp-2")
        report = await om.arm()
        # ARM should succeed (hardware pending doesn't block arm)
        assert om.state is OutputState.ARMED
        assert om.gate_result is not None
        assert om.gate_result.can_arm
        # But LIVE should be blocked by hardware pending
        with pytest.raises(LiveNotAuthorizedError):
            await om.go_live()
        assert om.state is OutputState.ARMED
        await om.end_session()


# ---------------------------------------------------------------------------
# Legacy behavior (no gate)
# ---------------------------------------------------------------------------


class TestLegacyArmGoLive:
    async def test_arm_without_gate(self, legacy_output_manager: object) -> None:
        """Without a gate, arm() follows display validation only."""
        om, dm, provider = legacy_output_manager  # type: ignore[misc]
        await om.begin_session(preview_display_id="disp-1")
        await om.set_live_target("disp-2")
        report = await om.arm()
        assert om.state is OutputState.ARMED
        assert om.gate_result is None
        assert om.can_arm is True
        await om.end_session()

    async def test_go_live_without_gate(self, legacy_output_manager: object) -> None:
        """Without a gate, go_live() follows display validation only."""
        om, dm, provider = legacy_output_manager  # type: ignore[misc]
        await om.begin_session(preview_display_id="disp-1")
        await om.set_live_target("disp-2")
        await om.arm()
        report = await om.go_live()
        assert om.state is OutputState.LIVE
        assert om.can_live is True
        await om.end_session()
