"""CalibrationProgressViewModel — Qt-free presentation for the Phase 7.4 progress UI.

Wraps a :class:`ProductionWorkflow` instance (it does *not* own the
workflow) and exposes read-only, display-ready properties for the
calibration progress panel. Widgets poll :attr:`revision` after
:meth:`refresh` to decide when to re-render; the viewmodel never mutates
the workflow.

Device status (camera / projector) is read from an optional
:class:`DevicesViewModel`; when none is attached the panel shows
``"Not connected"``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, ClassVar

from projectionai.application.calibration_workflow import (
    ProductionWorkflow,
    StageStatus,
    WorkflowState,
)
from projectionai.ui.viewmodels.observable import Observable

if TYPE_CHECKING:
    from projectionai.ui.viewmodels.devices import DevicesViewModel


_STATE_DISPLAY: dict[WorkflowState, str] = {
    WorkflowState.IDLE: "Idle",
    WorkflowState.PRECHECK: "Running preflight checks",
    WorkflowState.PREPARING: "Preparing patterns",
    WorkflowState.CAPTURING: "Capturing patterns",
    WorkflowState.DECODING: "Decoding patterns",
    WorkflowState.RECONSTRUCTING: "Reconstructing geometry",
    WorkflowState.SOLVING: "Solving calibration",
    WorkflowState.VALIDATING: "Validating calibration",
    WorkflowState.PREVIEW: "Preview",
    WorkflowState.SAVING: "Saving calibration",
    WorkflowState.READY_TO_ARM: "Ready to arm",
    WorkflowState.ARMED: "Armed",
    WorkflowState.LIVE: "Live",
    WorkflowState.CANCELLED: "Cancelled",
    WorkflowState.FAILED: "Failed",
}

_STAGE_STATUS_DISPLAY: dict[StageStatus, str] = {
    StageStatus.PENDING: "PENDING",
    StageStatus.RUNNING: "RUNNING",
    StageStatus.DONE: "COMPLETE",
    StageStatus.FAILED: "FAILED",
    StageStatus.SKIPPED: "SKIPPED",
}

_CANCELLABLE_STATES: frozenset[WorkflowState] = frozenset(
    {
        WorkflowState.PRECHECK,
        WorkflowState.PREPARING,
        WorkflowState.CAPTURING,
        WorkflowState.DECODING,
        WorkflowState.RECONSTRUCTING,
        WorkflowState.SOLVING,
        WorkflowState.VALIDATING,
        WorkflowState.PREVIEW,
        WorkflowState.SAVING,
        WorkflowState.READY_TO_ARM,
        WorkflowState.ARMED,
        WorkflowState.LIVE,
    }
)

_TERMINAL_STATES: frozenset[WorkflowState] = frozenset(
    {
        WorkflowState.READY_TO_ARM,
        WorkflowState.ARMED,
        WorkflowState.LIVE,
        WorkflowState.CANCELLED,
        WorkflowState.FAILED,
    }
)


class CalibrationProgressViewModel(Observable):
    """Read-only observable facade over a :class:`ProductionWorkflow`."""

    def __init__(
        self,
        workflow: ProductionWorkflow,
        devices: DevicesViewModel | None = None,
    ) -> None:
        super().__init__()
        self._workflow = workflow
        self._devices = devices

    # -- Wiring -----------------------------------------------------------

    def set_workflow(self, workflow: ProductionWorkflow) -> None:
        """Swap the workflow being observed and notify subscribers."""
        self._workflow = workflow
        self._notify()

    def refresh(self) -> None:
        """Bump :attr:`revision` so polling widgets re-render."""
        self._notify()

    # -- Workflow state text ------------------------------------------------

    @property
    def workflow_state(self) -> str:
        """Human-readable label for the current workflow state."""
        state = self._workflow.state
        return _STATE_DISPLAY.get(state, state.value)

    @property
    def current_stage(self) -> str:
        """Display name of the running (or most recently failed) stage.

        Returns an empty string when no stage has started yet.
        """
        stage = self._active_stage_id()
        if stage is None:
            return ""
        return stage.replace("_", " ").title()

    @property
    def stage_status(self) -> str:
        """PENDING / RUNNING / COMPLETE / FAILED / CANCELLED for the current stage."""
        if self._workflow.state == WorkflowState.CANCELLED:
            return "CANCELLED"
        stage = self._active_stage_id()
        if stage is None:
            return "PENDING"
        result = self._workflow.stages.get(stage)
        if result is None:
            return "PENDING"
        return _STAGE_STATUS_DISPLAY.get(result.status, "PENDING")

    # -- Progress -----------------------------------------------------------

    @property
    def stage_progress(self) -> float:
        """0.0-1.0 progress of the current stage (0.0 when none is active)."""
        stage = self._active_stage_id()
        if stage is None:
            return 0.0
        result = self._workflow.stages.get(stage)
        if result is None:
            return 0.0
        return max(0.0, min(1.0, result.progress))

    @property
    def overall_progress(self) -> float:
        """0.0-1.0 overall workflow progress (pass-through)."""
        return self._workflow.progress

    @property
    def elapsed_time(self) -> float:
        """Seconds since the first stage started; frozen at end of terminal states."""
        started = [
            sr.started_at
            for sr in self._workflow.stages.values()
            if sr.started_at is not None
        ]
        if not started:
            return 0.0
        t0 = min(started)
        if self._workflow.state in _TERMINAL_STATES:
            completed = [
                sr.completed_at
                for sr in self._workflow.stages.values()
                if sr.completed_at is not None
            ]
            t1 = max(completed) if completed else t0
        else:
            t1 = time.time()
        return max(0.0, t1 - t0)

    @property
    def estimated_remaining(self) -> float | None:
        """ETA in seconds, or ``None`` when there is insufficient data."""
        if self._workflow.state in _TERMINAL_STATES:
            return None
        progress = self.overall_progress
        elapsed = self.elapsed_time
        if progress <= 0.0 or elapsed <= 0.0:
            return None
        return elapsed * (1.0 - progress) / progress

    # -- Pattern counter ------------------------------------------------------

    @property
    def pattern_index(self) -> int:
        """Current pattern index, or 0 when the workflow does not expose it."""
        raw = getattr(self._workflow, "pattern_index", 0)
        return int(raw) if isinstance(raw, (int, float)) else 0

    @property
    def pattern_total(self) -> int:
        """Total pattern count, or 0 when the workflow does not expose it."""
        raw = getattr(self._workflow, "pattern_total", 0)
        return int(raw) if isinstance(raw, (int, float)) else 0

    # -- Source mode --------------------------------------------------------

    @property
    def source_mode(self) -> str:
        if self._workflow.is_synthetic:
            return "SYNTHETIC"
        return "LIVE"

    # -- Stage metrics ------------------------------------------------------

    @property
    def stage_metrics(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for stage_id, result in self._workflow.stages.items():
            if isinstance(result.result, dict):
                out[stage_id] = result.result
        return out

    @property
    def current_stage_metrics(self) -> dict[str, Any]:
        stage = self._active_stage_id()
        if stage is None:
            return {}
        result = self._workflow.stages.get(stage)
        if result is None or not isinstance(result.result, dict):
            return {}
        return result.result

    _ERROR_CATEGORY_MAP: ClassVar[dict[str, str]] = {
        "No frames to decode": "CAPTURE_DATA_ERROR",
        "Got 0 frames for": "CAPTURE_DATA_ERROR",
        "sequence_id mismatch": "CAPTURE_DATA_ERROR",
        "No valid correspondences": "DECODE_ERROR",
        "pattern_ids": "DECODE_ERROR",
        "duplicate pattern_id": "DECODE_ERROR",
        "No valid correspondences to reconstruct": "RECONSTRUCTION_ERROR",
        "Only 0 correspondences": "RECONSTRUCTION_ERROR",
        "Too few correspondences": "RECONSTRUCTION_ERROR",
        "Too few calibration orientations": "INSUFFICIENT_ORIENTATION_DIVERSITY",
        "Insufficient calibration orientation diversity": "INSUFFICIENT_ORIENTATION_DIVERSITY",
        "Frontal": "DEGENERATE_GEOMETRY",
        "near-degenerate": "DEGENERATE_GEOMETRY",
        "condition number": "DEGENERATE_GEOMETRY",
        "No reconstructions provided": "SOLVER_ERROR",
        "cross-plane consistency": "QUALITY_THRESHOLD_FAILURE",
        "cancelled": "CANCELLED",
        "Hardware-pending": "HARDWARE_PENDING",
    }

    @property
    def error_category(self) -> str:
        errors = self.errors
        if not errors:
            return ""
        first = errors[0]
        for pattern, category in self._ERROR_CATEGORY_MAP.items():
            if pattern in first:
                return category
        return "UNKNOWN_ERROR"

    # -- Devices ---------------------------------------------------------------

    @property
    def camera_status(self) -> str:
        """Short camera status line, or ``"Not connected"`` without a DevicesViewModel."""
        if self._devices is None:
            return "Not connected"
        count = self._devices.camera_count
        if count <= 0:
            return "No cameras"
        return "1 camera" if count == 1 else f"{count} cameras"

    @property
    def projector_status(self) -> str:
        """Short projector status line, or ``"Not connected"`` without a DevicesViewModel."""
        if self._devices is None:
            return "Not connected"
        count = self._devices.projector_count
        if count <= 0:
            return "No projectors"
        return "1 projector" if count == 1 else f"{count} projectors"

    # -- Diagnostics -----------------------------------------------------------

    @property
    def warnings(self) -> list[str]:
        """Workflow-level plus per-stage warnings, de-duplicated in order."""
        return self._collect("warning")

    @property
    def errors(self) -> list[str]:
        """Workflow-level plus per-stage errors, de-duplicated in order."""
        return self._collect("error")

    # -- Capabilities ----------------------------------------------------------

    @property
    def can_cancel(self) -> bool:
        """True while the workflow is in an active, cancellable state."""
        return self._workflow.state in _CANCELLABLE_STATES

    @property
    def can_retry(self) -> bool:
        """True when the workflow FAILED and :meth:`ProductionWorkflow.reset` applies."""
        return self._workflow.state == WorkflowState.FAILED

    @property
    def hardware_pending(self) -> tuple[str, ...]:
        """The seven hardware-pending gates (pass-through from the workflow)."""
        return self._workflow.hardware_pending

    # -- Internals ---------------------------------------------------------------

    def _active_stage_id(self) -> str | None:
        """First RUNNING stage id; failing that, the first FAILED stage id."""
        failed: str | None = None
        for stage_id, result in self._workflow.stages.items():
            if result.status == StageStatus.RUNNING:
                return stage_id
            if failed is None and result.status == StageStatus.FAILED:
                failed = stage_id
        return failed

    def _collect(self, field_name: str) -> list[str]:
        """Gather workflow-level and per-stage *field_name* messages in order."""
        seen: set[str] = set()
        out: list[str] = []
        top = getattr(self._workflow, field_name, None)
        if isinstance(top, str) and top and top not in seen:
            seen.add(top)
            out.append(top)
        for result in self._workflow.stages.values():
            msg = getattr(result, field_name, None)
            if isinstance(msg, str) and msg and msg not in seen:
                seen.add(msg)
                out.append(msg)
        return out
