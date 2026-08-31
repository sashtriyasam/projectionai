"""Tests for ProductionWorkflow — state machine, cancellation, hardware-pending."""

import asyncio

import pytest

from projectionai.application.calibration_workflow import (
    ProductionWorkflow,
    StageStatus,
    WorkflowState,
    _VALID_TRANSITIONS,
    _WORKFLOW_STAGE_ORDER,
)


def test_valid_transitions():
    w = ProductionWorkflow()
    assert w.state == WorkflowState.IDLE
    w.transition(WorkflowState.PRECHECK)
    assert w.state == WorkflowState.PRECHECK
    with pytest.raises(ValueError):
        w.transition(WorkflowState.LIVE)  # invalid from PRECHECK


def test_every_valid_transition():
    for src, dsts in _VALID_TRANSITIONS.items():
        for dst in dsts:
            w = ProductionWorkflow()
            w.state = src
            w.transition(dst)
            assert w.state == dst


def test_every_invalid_transition():
    all_states = set(WorkflowState)
    for src in WorkflowState:
        allowed = _VALID_TRANSITIONS.get(src, set())
        invalid = all_states - allowed
        for dst in invalid:
            if dst == src:
                continue
            w = ProductionWorkflow()
            w.state = src
            with pytest.raises(ValueError):
                w.transition(dst)


def test_progress_monotonicity():
    w = ProductionWorkflow()
    prev = w.progress
    assert prev == 0.0
    for idx, sid in enumerate(_WORKFLOW_STAGE_ORDER):
        w._set_stage(sid, StageStatus.DONE, 1.0)
        cur = w.progress
        assert cur >= prev, f"progress not monotonic at {sid}: {prev} -> {cur}"
        prev = cur
    assert w.progress == 1.0


def test_stage_ordering():
    w = ProductionWorkflow()
    assert _WORKFLOW_STAGE_ORDER == (
        "prepare",
        "capture",
        "decode",
        "reconstruct",
        "solve",
        "validate",
        "warp",
        "persist",
    )
    for sid in _WORKFLOW_STAGE_ORDER:
        assert sid not in w.stages
    w._set_stage("prepare", StageStatus.DONE, 1.0)
    assert list(w.stages.keys()) == ["prepare"]


def test_stage_failure_propagation():
    w = ProductionWorkflow()
    w.state = WorkflowState.CAPTURING
    w._set_stage("capture", StageStatus.RUNNING, 0.5)
    # Simulate exception in run_full path: stage should become FAILED, workflow FAILED
    w.state = WorkflowState.FAILED
    w.error = "capture failed"
    w._set_stage("capture", StageStatus.FAILED, 0.0, error="capture failed")
    assert w.stages["capture"].status == StageStatus.FAILED
    assert w.state == WorkflowState.FAILED
    assert w.error == "capture failed"


@pytest.mark.asyncio
async def test_preflight_ok():
    w = ProductionWorkflow()
    report = await w.preflight(
        camera_available=True,
        projector_available=True,
        resolution=(1280, 720),
        surface_valid=True,
        storage_path="/tmp",
    )
    assert report.is_ok
    assert w.state == WorkflowState.PREPARING
    assert "7 hardware-pending" in report.warnings[0]


@pytest.mark.asyncio
async def test_preflight_fails_without_camera():
    w = ProductionWorkflow()
    report = await w.preflight(
        camera_available=False,
        projector_available=True,
        resolution=(1280, 720),
        surface_valid=True,
        storage_path=None,
    )
    assert not report.is_ok
    assert "camera unavailable" in report.errors
    assert w.state == WorkflowState.FAILED


@pytest.mark.asyncio
async def test_cancellation_before_stage():
    w = ProductionWorkflow()
    w.request_cancel()
    with pytest.raises(asyncio.CancelledError):
        await w.run_full()
    assert w.state == WorkflowState.CANCELLED
    assert w.calibration_result is None
    assert w.warp_mesh is None


@pytest.mark.asyncio
async def test_cancellation_during_stage():
    w = ProductionWorkflow()

    # Make prepare stage slow and cancellable
    original_prepare = w._do_prepare

    async def slow_prepare(*args):
        await asyncio.sleep(0.1)
        return original_prepare(*args)

    w._do_prepare = slow_prepare  # type: ignore[method-assign]
    task = asyncio.create_task(w.run_full())
    await asyncio.sleep(0.02)
    w.request_cancel()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError:
        pass
    assert w.state in (WorkflowState.CANCELLED, WorkflowState.FAILED)
    assert w.calibration_result is None
    assert w.warp_mesh is None


def test_repeated_cancel():
    w = ProductionWorkflow()
    w.request_cancel()
    w.request_cancel()
    assert w._cancel_requested is True
    with pytest.raises(asyncio.CancelledError):
        w._check_cancelled()
    # Second check still raises
    with pytest.raises(asyncio.CancelledError):
        w._check_cancelled()


@pytest.mark.asyncio
async def test_retry_limit_bounded():
    w = ProductionWorkflow()
    # _run_stage_with_retry should retry exactly max_retries times then fail
    call_count = 0

    def failing_func():
        nonlocal call_count
        call_count += 1
        raise RuntimeError(f"fail {call_count}")

    with pytest.raises(RuntimeError):
        await w._run_stage_with_retry("prepare", 2, failing_func)
    assert call_count == 3  # initial + 2 retries
    assert w._retry_counts["prepare"] == 3

    # max_retries >5 should raise immediately
    with pytest.raises(ValueError):
        await w.run_full(max_retries=10)


@pytest.mark.asyncio
async def test_cancellation():
    w = ProductionWorkflow()
    w.request_cancel()
    with pytest.raises(asyncio.CancelledError):
        await w.run_full()
    assert w.state == WorkflowState.CANCELLED


@pytest.mark.asyncio
async def test_hardware_pending_exposed():
    w = ProductionWorkflow()
    await w.preflight(
        camera_available=True,
        projector_available=True,
        resolution=(1280, 720),
        surface_valid=True,
        storage_path=None,
    )
    assert len(w.hardware_pending) == 7
    assert "optical closure" in w.hardware_pending


def test_hardware_pending_never_disappearing():
    w = ProductionWorkflow()
    # Initially empty
    assert w.hardware_pending == ()
    # After preflight, 7
    import asyncio as _asyncio

    async def _run():
        await w.preflight(
            camera_available=True,
            projector_available=True,
            resolution=(1280, 720),
            surface_valid=True,
            storage_path=None,
        )

    _asyncio.run(_run())
    assert len(w.hardware_pending) == 7
    # After reset, still 7
    w.state = WorkflowState.FAILED
    w.reset()
    assert len(w.hardware_pending) == 7
    w.state = WorkflowState.CANCELLED
    w.reset()
    assert len(w.hardware_pending) == 7


def test_synthetic_cannot_claim_live():
    w = ProductionWorkflow()
    w.is_synthetic = True
    w.state = WorkflowState.ARMED
    with pytest.raises(ValueError, match="Synthetic.*cannot.*LIVE"):
        w.transition(WorkflowState.LIVE)
    # Real hardware can
    w.is_synthetic = False
    w.transition(WorkflowState.LIVE)
    assert w.state == WorkflowState.LIVE


def test_workflow_reset_after_failed():
    w = ProductionWorkflow()
    w.state = WorkflowState.FAILED
    w.error = "some error"
    w._set_stage("prepare", StageStatus.FAILED, 0.0, error="some error")
    w.calibration_result = None
    w.reset()
    assert w.state == WorkflowState.IDLE
    assert w.error is None
    assert w.stages == {}
    assert w._cancel_requested is False


def test_workflow_reset_after_cancelled():
    w = ProductionWorkflow()
    w.state = WorkflowState.CANCELLED
    w._set_stage("capture", StageStatus.FAILED, 0.0, error="cancelled")
    w.reset()
    assert w.state == WorkflowState.IDLE
    assert w.stages == {}


def test_reset_invalid_from_preparing():
    w = ProductionWorkflow()
    w.state = WorkflowState.PREPARING
    with pytest.raises(ValueError):
        w.reset()


def test_stage_contract():
    w = ProductionWorkflow()
    sr = w._set_stage("prepare", StageStatus.RUNNING, 0.5)
    assert sr.stage_id == "prepare"
    assert sr.status == StageStatus.RUNNING
    assert 0 <= sr.progress <= 1
    sr2 = w._set_stage("prepare", StageStatus.DONE, 1.0)
    assert sr2.status == StageStatus.DONE
    assert sr2.progress == 1.0


def test_calibration_status_mapping():
    w = ProductionWorkflow()
    w.state = WorkflowState.CAPTURING
    assert w.calibration_status.value == "capturing"
    w.state = WorkflowState.SOLVING
    assert w.calibration_status.value == "solving"
    w.state = WorkflowState.FAILED
    assert w.calibration_status.value == "failed"


def test_safe_cancellation_clears_results():
    w = ProductionWorkflow()
    w._set_stage("prepare", StageStatus.RUNNING, 0.5)
    # Simulate having a partial result (should be cleared on cancel)
    w.calibration_result = object()  # type: ignore[assignment]
    import asyncio as _asyncio

    _asyncio.run(w._safe_cancel())
    assert w.state == WorkflowState.CANCELLED
    assert w.calibration_result is None
    assert w.warp_mesh is None
    assert w.stages["prepare"].status == StageStatus.FAILED


# ---------------------------------------------------------------------------
# Gate 4 — Synthetic SKIPPED ≠ DONE
# ---------------------------------------------------------------------------


def test_synthetic_skipped_not_done():
    """Synthetic pipeline produces SKIPPED for decode/reconstruct/solve, never DONE."""
    w = ProductionWorkflow()
    w.is_synthetic = True
    # Simulate a synthetic pipeline that reached decode with no frames
    w._set_stage("prepare", StageStatus.DONE, 1.0, result=None)
    w._set_stage(
        "decode", StageStatus.SKIPPED, 1.0, warning="Synthetic mode — decode skipped"
    )
    w._set_stage(
        "reconstruct", StageStatus.SKIPPED, 1.0, warning="No camera/surface in context"
    )
    w._set_stage("solve", StageStatus.SKIPPED, 1.0, warning="No reconstruction")
    assert w.stages["decode"].status == StageStatus.SKIPPED
    assert w.stages["decode"].status != StageStatus.DONE
    assert w.stages["reconstruct"].status == StageStatus.SKIPPED
    assert w.stages["solve"].status == StageStatus.SKIPPED
    assert w.calibration_result is None


def test_synthetic_skipped_ui_not_complete():
    """SKIPPED maps to 'SKIPPED' in UI, not 'COMPLETE'."""
    from projectionai.ui.viewmodels.calibration_progress import _STAGE_STATUS_DISPLAY

    assert _STAGE_STATUS_DISPLAY[StageStatus.SKIPPED] == "SKIPPED"
    assert _STAGE_STATUS_DISPLAY[StageStatus.SKIPPED] != "COMPLETE"


# ---------------------------------------------------------------------------
# Gate 11 — Cancellation during heavy stages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancellation_during_decode():
    """Cancelling during decode produces CANCELLED state, no stale results."""
    w = ProductionWorkflow()
    w.state = WorkflowState.DECODING
    w._set_stage("decode", StageStatus.RUNNING, 0.5)
    w.calibration_result = object()  # type: ignore[assignment]
    import asyncio as _asyncio

    await w._safe_cancel()
    assert w.state == WorkflowState.CANCELLED
    assert w.calibration_result is None
    assert w.stages["decode"].status == StageStatus.FAILED
    assert w.stages["decode"].error == "cancelled"


@pytest.mark.asyncio
async def test_cancellation_during_reconstruct():
    """Cancelling during reconstruct produces CANCELLED state, no stale results."""
    w = ProductionWorkflow()
    w.state = WorkflowState.RECONSTRUCTING
    w._set_stage("reconstruct", StageStatus.RUNNING, 0.5)
    w.calibration_result = object()  # type: ignore[assignment]
    import asyncio as _asyncio

    await w._safe_cancel()
    assert w.state == WorkflowState.CANCELLED
    assert w.calibration_result is None
    assert w.stages["reconstruct"].status == StageStatus.FAILED


@pytest.mark.asyncio
async def test_cancellation_during_solve():
    """Cancelling during solve produces CANCELLED state, no stale results."""
    w = ProductionWorkflow()
    w.state = WorkflowState.SOLVING
    w._set_stage("solve", StageStatus.RUNNING, 0.5)
    w.calibration_result = object()  # type: ignore[assignment]
    import asyncio as _asyncio

    await w._safe_cancel()
    assert w.state == WorkflowState.CANCELLED
    assert w.calibration_result is None
    assert w.stages["solve"].status == StageStatus.FAILED


# ---------------------------------------------------------------------------
# Gate 13 — Data integrity: stage result propagation
# ---------------------------------------------------------------------------


def test_skipped_stage_has_no_result():
    """SKIPPED stages carry no valid downstream result."""
    w = ProductionWorkflow()
    w._set_stage("decode", StageStatus.SKIPPED, 1.0, warning="skipped")
    sr = w.stages["decode"]
    assert sr.result is None
    assert sr.error is None


def test_done_stage_has_result_dict():
    """DONE stages carry structured metrics in result dict."""
    w = ProductionWorkflow()
    metrics = {"valid_ratio": 0.95, "frame_count": 12, "sequence_id": "abc"}
    w._set_stage("decode", StageStatus.DONE, 1.0, result=metrics)
    sr = w.stages["decode"]
    assert isinstance(sr.result, dict)
    assert sr.result["valid_ratio"] == 0.95


# ---------------------------------------------------------------------------
# Gate 13 — prepare stage result propagation via run_full
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_result_contains_calibration_sequence():
    """run_full preserves the CalibrationSequence in stages['prepare'].result."""
    from projectionai.domain.calibration_session import CalibrationSequence

    w = ProductionWorkflow()
    await w.run_full(
        camera_available=True,
        projector_available=True,
        is_synthetic=True,
    )
    prepare_sr = w.stages.get("prepare")
    assert prepare_sr is not None
    assert prepare_sr.result is not None
    assert isinstance(prepare_sr.result, CalibrationSequence), (
        f"Expected CalibrationSequence, got {type(prepare_sr.result)}"
    )


# ---------------------------------------------------------------------------
# Gate 9 — Stage contract: started_at / completed_at
# ---------------------------------------------------------------------------


def test_stage_started_and_completed_times():
    """RUNNING sets started_at; DONE/SKIPPED/FAILED sets completed_at."""
    w = ProductionWorkflow()
    sr_run = w._set_stage("decode", StageStatus.RUNNING, 0.5)
    assert sr_run.started_at is not None
    assert sr_run.completed_at is None

    sr_done = w._set_stage("decode", StageStatus.DONE, 1.0)
    assert sr_done.started_at is not None
    assert sr_done.completed_at is not None

    w._set_stage("fail_stage", StageStatus.FAILED, 0.0, error="boom")
    sr_fail = w.stages["fail_stage"]
    assert sr_fail.completed_at is not None

    w._set_stage("skip_stage", StageStatus.SKIPPED, 1.0)
    sr_skip = w.stages["skip_stage"]
    assert sr_skip.completed_at is not None


# ---------------------------------------------------------------------------
# Gate 12 — Retry: bounded attempts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_count_tracked():
    """_retry_counts records total attempts including final failure."""
    w = ProductionWorkflow()

    def always_fail():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        await w._run_stage_with_retry("prepare", 3, always_fail)
    assert w._retry_counts["prepare"] == 4  # 1 initial + 3 retries
