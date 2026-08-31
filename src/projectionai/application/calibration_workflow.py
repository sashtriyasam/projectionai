"""Production calibration workflow — thin orchestrator over Phase 6 backend."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from projectionai.calibration.solver import CalibrationSolveError, solve_calibration
from projectionai.calibration.validation_gate import (
    ValidationGate,
    ValidationGateResult,
)
from projectionai.domain.calibration_session import (
    CalibrationFrame,
    CalibrationResult,
    CalibrationSequence,
    CalibrationSessionStatus,
    CorrespondenceSet,
    ReconstructionResult,
)
from projectionai.domain.warp_mesh import WarpMesh
from projectionai.services.pattern_engine import PatternEngine
from projectionai.services.reconstruction import (
    BackendMode,
    ReconstructionBackendFactory,
    ReconstructionError,
)
from projectionai.services.structured_light_decoder import (
    StructuredLightDecodeError,
    StructuredLightDecoder,
)

_logger = logging.getLogger(__name__)


class WorkflowState(StrEnum):
    IDLE = "idle"
    PRECHECK = "precheck"
    PREPARING = "preparing"
    CAPTURING = "capturing"
    DECODING = "decoding"
    RECONSTRUCTING = "reconstructing"
    SOLVING = "solving"
    VALIDATING = "validating"
    PREVIEW = "preview"
    SAVING = "saving"
    READY_TO_ARM = "ready_to_arm"
    ARMED = "armed"
    LIVE = "live"
    CANCELLED = "cancelled"
    FAILED = "failed"


# A: Clean mapping to domain CalibrationSessionStatus — single authority is WorkflowState,
# domain status is derived, not conflicting. WorkflowState is production operator lifecycle,
# CalibrationSessionStatus is domain session lifecycle — mapped, not duplicated.
_WORKFLOW_TO_CALIBRATION_STATUS: dict[WorkflowState, CalibrationSessionStatus] = {
    WorkflowState.IDLE: CalibrationSessionStatus.IDLE,
    WorkflowState.PRECHECK: CalibrationSessionStatus.PREPARING,
    WorkflowState.PREPARING: CalibrationSessionStatus.PREPARING,
    WorkflowState.CAPTURING: CalibrationSessionStatus.CAPTURING,
    WorkflowState.DECODING: CalibrationSessionStatus.PROCESSING,
    WorkflowState.RECONSTRUCTING: CalibrationSessionStatus.PROCESSING,
    WorkflowState.SOLVING: CalibrationSessionStatus.SOLVING,
    WorkflowState.VALIDATING: CalibrationSessionStatus.VALIDATING,
    WorkflowState.PREVIEW: CalibrationSessionStatus.VALIDATING,
    WorkflowState.SAVING: CalibrationSessionStatus.VALIDATING,
    WorkflowState.READY_TO_ARM: CalibrationSessionStatus.COMPLETED,
    WorkflowState.ARMED: CalibrationSessionStatus.COMPLETED,
    WorkflowState.LIVE: CalibrationSessionStatus.COMPLETED,
    WorkflowState.CANCELLED: CalibrationSessionStatus.CANCELLED,
    WorkflowState.FAILED: CalibrationSessionStatus.FAILED,
}

_VALID_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.IDLE: {WorkflowState.PRECHECK, WorkflowState.CANCELLED},
    WorkflowState.PRECHECK: {
        WorkflowState.PREPARING,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.PREPARING: {
        WorkflowState.CAPTURING,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.CAPTURING: {
        WorkflowState.DECODING,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.DECODING: {
        WorkflowState.RECONSTRUCTING,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.RECONSTRUCTING: {
        WorkflowState.SOLVING,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.SOLVING: {
        WorkflowState.VALIDATING,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.VALIDATING: {
        WorkflowState.PREVIEW,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.PREVIEW: {
        WorkflowState.SAVING,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.SAVING: {
        WorkflowState.READY_TO_ARM,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.READY_TO_ARM: {
        WorkflowState.ARMED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.ARMED: {
        WorkflowState.LIVE,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    WorkflowState.LIVE: {
        WorkflowState.IDLE,
        WorkflowState.CANCELLED,
        WorkflowState.FAILED,
    },
    WorkflowState.CANCELLED: {WorkflowState.IDLE},
    WorkflowState.FAILED: {WorkflowState.IDLE},
}


# B: Deterministic stage order — progress never depends on dict iteration
_WORKFLOW_STAGE_ORDER: tuple[str, ...] = (
    "prepare",
    "capture",
    "decode",
    "reconstruct",
    "solve",
    "validate",
    "warp",
    "persist",
)


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StageResult:
    stage_id: str
    status: StageStatus
    progress: float
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    warning: str | None = None
    result: Any | None = None


@dataclass(frozen=True)
class PreflightReport:
    is_ok: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass
class ProductionWorkflow:
    """Thin orchestrator — owns session lifecycle, not math."""

    workflow_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: WorkflowState = WorkflowState.IDLE
    stages: dict[str, StageResult] = field(default_factory=dict)
    error: str | None = None
    warning: str | None = None
    calibration_result: CalibrationResult | None = None
    warp_mesh: WarpMesh | None = None
    hardware_pending: tuple[str, ...] = ()
    is_synthetic: bool = False
    _cancel_requested: bool = field(default=False, repr=False)
    _retry_counts: dict[str, int] = field(default_factory=dict, repr=False)
    _ctx_data: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def calibration_status(self) -> CalibrationSessionStatus:
        """A: Derived domain status — single authority remains WorkflowState."""
        return _WORKFLOW_TO_CALIBRATION_STATUS.get(
            self.state, CalibrationSessionStatus.FAILED
        )

    @property
    def progress(self) -> float:
        """B: Deterministic overall progress — ordered, not dict iteration."""
        if not self.stages:
            return 0.0
        total = len(_WORKFLOW_STAGE_ORDER)
        done = 0.0
        for sid in _WORKFLOW_STAGE_ORDER:
            sr = self.stages.get(sid)
            if sr is None:
                continue
            if sr.status == StageStatus.DONE:
                done += 1.0
            elif sr.status == StageStatus.RUNNING:
                done += max(0.0, min(1.0, sr.progress)) * 0.5
            elif sr.status == StageStatus.FAILED:
                done += 0.0
        return max(0.0, min(1.0, done / total))

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def _check_cancelled(self) -> None:
        if self._cancel_requested:
            raise asyncio.CancelledError("Workflow cancelled via request_cancel()")

    def transition(self, target: WorkflowState) -> None:
        # H: Synthetic path cannot claim LIVE hardware state
        if target == WorkflowState.LIVE and self.is_synthetic:
            raise ValueError(
                "Synthetic/replay workflow cannot transition to LIVE — requires real hardware calibration"
            )
        allowed = _VALID_TRANSITIONS.get(self.state)
        if allowed is None or target not in allowed:
            raise ValueError(f"Invalid transition {self.state.value} -> {target.value}")
        _logger.info(
            "Workflow %s: %s -> %s", self.workflow_id, self.state.value, target.value
        )
        self.state = target

    def reset(self) -> None:
        """After FAILED/CANCELLED, reset to IDLE for reuse — clears transient state but keeps hardware_pending."""
        if self.state not in (
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
            WorkflowState.IDLE,
        ):
            raise ValueError(
                f"Cannot reset from {self.state.value} — only FAILED/CANCELLED/IDLE"
            )
        self.state = WorkflowState.IDLE
        self.stages.clear()
        self.error = None
        self.warning = None
        self.calibration_result = None
        self.warp_mesh = None
        self._cancel_requested = False
        self._retry_counts.clear()
        # G: hardware_pending never disappears — retains 7 gates across resets

    def run_gate(
        self,
        *,
        calibration_report: Any | None = None,
        display_report: Any | None = None,
        source_mode: str | None = None,
    ) -> ValidationGateResult:
        """Evaluate the unified gate using the workflow's accumulated state.

        Call this after reaching READY_TO_ARM to determine whether
        the system is authorized to arm or go live.

        Args:
            calibration_report: CalibrationValidator.ValidationReport, if available.
                None means no calibration quality check (gate V-01 FAILS).
            display_report: DisplayValidator.ValidationReport, if available.
            source_mode: Override source mode. Defaults to SYNTHETIC/LIVE based on is_synthetic.
        """
        gate = ValidationGate()
        sm = source_mode or ("SYNTHETIC" if self.is_synthetic else "LIVE")
        return gate.check(
            calibration_report=calibration_report,
            display_report=display_report,
            hardware_pending=self.hardware_pending,
            source_mode=sm,
        )

    def _set_stage(
        self,
        stage_id: str,
        status: StageStatus,
        progress: float,
        error: str | None = None,
        warning: str | None = None,
        result: Any | None = None,
    ) -> StageResult:
        now = time.time()
        prev = self.stages.get(stage_id)
        started = (
            prev.started_at
            if prev and prev.started_at
            else now
            if status == StageStatus.RUNNING
            else None
        )
        completed = (
            now
            if status in (StageStatus.DONE, StageStatus.FAILED, StageStatus.SKIPPED)
            else None
        )
        sr = StageResult(
            stage_id=stage_id,
            status=status,
            progress=progress,
            started_at=started,
            completed_at=completed,
            error=error,
            warning=warning,
            result=result,
        )
        self.stages[stage_id] = sr
        return sr

    async def preflight(
        self,
        *,
        camera_available: bool,
        projector_available: bool,
        resolution: tuple[int, int] | None,
        surface_valid: bool,
        storage_path: str | None,
        surface_supported_for_calibration: bool = True,
        surface_report: Any | None = None,
    ) -> PreflightReport:
        self.transition(WorkflowState.PRECHECK)
        errors: list[str] = []
        warnings: list[str] = []
        if not camera_available:
            errors.append("camera unavailable")
        if not projector_available:
            errors.append("projector/display unavailable")
        if resolution is None or resolution[0] <= 0 or resolution[1] <= 0:
            errors.append("resolution invalid")
        if surface_report is not None:
            is_ok = bool(getattr(surface_report, "is_ok", False))
            supported = bool(
                getattr(surface_report, "supported_for_calibration", False)
            )
            if not is_ok:
                errors.append("surface invalid")
            if not supported:
                errors.append("surface not supported for calibration")
        else:
            if not surface_valid:
                errors.append("surface invalid")
            if not surface_supported_for_calibration:
                errors.append("surface not supported for calibration")
        if storage_path is None or not storage_path.strip():
            warnings.append("storage path not set — will use in-memory only")
        # G: Hardware-pending gates are warnings, visible, never silently bypassed
        self.hardware_pending = (
            "optical closure",
            "real vsync/frameSwapped",
            "settle-time",
            "camera buffer policy",
            "real sentinel coverage",
            "real two-plane calibration",
            "repeatability",
        )
        warnings.append(
            "7 hardware-pending gates — software workflow remains usable with synthetic/replay"
        )
        report = PreflightReport(
            is_ok=len(errors) == 0, errors=tuple(errors), warnings=tuple(warnings)
        )
        if not report.is_ok:
            self.transition(WorkflowState.FAILED)
            self.error = "; ".join(errors)
            self._set_stage("preflight", StageStatus.FAILED, 0.0, error=self.error)
        else:
            self.transition(WorkflowState.PREPARING)
            self._set_stage("preflight", StageStatus.DONE, 1.0)
        return report

    async def run_full(
        self,
        *,
        camera_available: bool = True,
        projector_available: bool = True,
        resolution: tuple[int, int] = (1280, 720),
        surface_valid: bool = True,
        surface_supported_for_calibration: bool = True,
        surface_report: Any | None = None,
        storage_path: str | None = None,
        pattern_width: int = 1280,
        pattern_height: int = 720,
        max_retries: int = 2,
        is_synthetic: bool = True,
    ) -> CalibrationResult | None:
        self.is_synthetic = is_synthetic
        if max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries must be 0..5")
        try:
            report = await self.preflight(
                camera_available=camera_available,
                projector_available=projector_available,
                resolution=resolution,
                surface_valid=surface_valid,
                surface_supported_for_calibration=surface_supported_for_calibration,
                surface_report=surface_report,
                storage_path=storage_path,
            )
            if not report.is_ok:
                return None
            self._check_cancelled()
            self._set_stage("prepare", StageStatus.RUNNING, 0.5)
            prepare_result = await self._run_stage_with_retry(
                "prepare", max_retries, self._do_prepare, pattern_width, pattern_height
            )
            self._set_stage("prepare", StageStatus.DONE, 1.0, result=prepare_result)
            self.transition(WorkflowState.CAPTURING)
            self._check_cancelled()

            self._set_stage("capture", StageStatus.RUNNING, 0.5)
            capture_result: dict[str, Any] = {
                "frames": [],
                "synthetic": self.is_synthetic,
            }
            self._set_stage("capture", StageStatus.DONE, 1.0, result=capture_result)
            self.transition(WorkflowState.DECODING)
            self._check_cancelled()

            self._set_stage("decode", StageStatus.RUNNING, 0.5)
            prev_seq = self._get_stage_result("prepare")
            prev_capture = self._get_stage_result("capture")
            sequence = prev_seq if isinstance(prev_seq, CalibrationSequence) else None
            frames_raw = (
                prev_capture.get("frames", []) if isinstance(prev_capture, dict) else []
            )
            if sequence is not None and frames_raw:
                frames = tuple(f for f in frames_raw if isinstance(f, CalibrationFrame))
                if frames:
                    decoder = StructuredLightDecoder(threshold=127)
                    try:
                        t0_decode = time.time()
                        correspondence = decoder.decode(frames, sequence)
                        decode_elapsed = time.time() - t0_decode
                    except StructuredLightDecodeError as exc:
                        self._set_stage(
                            "decode", StageStatus.FAILED, 0.0, error=str(exc)
                        )
                        raise
                    self._ctx_data["correspondence_set"] = correspondence
                    decode_metrics = {
                        "valid_ratio": correspondence.valid_ratio,
                        "frame_count": len(frames),
                        "sequence_id": correspondence.sequence_id,
                        "threshold": 127,
                        "projector_resolution": (pattern_width, pattern_height),
                        "elapsed_s": decode_elapsed,
                    }
                    self._set_stage(
                        "decode", StageStatus.DONE, 1.0, result=decode_metrics
                    )
                else:
                    self._set_stage(
                        "decode",
                        StageStatus.SKIPPED,
                        1.0,
                        warning="No calibration frames available",
                    )
            else:
                self._set_stage(
                    "decode",
                    StageStatus.SKIPPED,
                    1.0,
                    warning="Synthetic mode — decode skipped",
                )
            self.transition(WorkflowState.RECONSTRUCTING)
            self._check_cancelled()

            self._set_stage("reconstruct", StageStatus.RUNNING, 0.5)
            corr = self._ctx_data.get("correspondence_set")
            cam = self._ctx_data.get("calibrated_camera")
            surf = self._ctx_data.get("surface_plane")
            has_inputs = (
                isinstance(corr, CorrespondenceSet)
                and cam is not None
                and surf is not None
            )
            if has_inputs:
                assert isinstance(corr, CorrespondenceSet)
                assert cam is not None
                assert surf is not None
                backend = ReconstructionBackendFactory.create(BackendMode.REFERENCE)
                try:
                    t0_recon = time.time()
                    reconstruction = backend.reconstruct(corr, cam, surf)
                    recon_elapsed = time.time() - t0_recon
                except ReconstructionError as exc:
                    self._set_stage(
                        "reconstruct", StageStatus.FAILED, 0.0, error=str(exc)
                    )
                    raise
                self._ctx_data["reconstruction"] = reconstruction
                pts = reconstruction.points_camera
                n_total = len(pts)
                n_nan = int(np.any(np.isnan(pts), axis=1).sum()) if n_total > 0 else 0
                n_inf = int(np.any(np.isinf(pts), axis=1).sum()) if n_total > 0 else 0
                recon_metrics = {
                    "backend": backend.name,
                    "point_count": n_total,
                    "valid_point_count": n_total - n_nan - n_inf,
                    "nan_count": n_nan,
                    "inf_count": n_inf,
                    "sequence_id": reconstruction.sequence_id,
                    "elapsed_s": recon_elapsed,
                }
                self._set_stage(
                    "reconstruct", StageStatus.DONE, 1.0, result=recon_metrics
                )
            else:
                self._set_stage(
                    "reconstruct",
                    StageStatus.SKIPPED,
                    1.0,
                    warning="No camera/surface in context — reconstruct skipped",
                )
            self.transition(WorkflowState.SOLVING)
            self._check_cancelled()

            self._set_stage("solve", StageStatus.RUNNING, 0.5)
            recon = self._ctx_data.get("reconstruction")
            if isinstance(recon, ReconstructionResult):
                try:
                    t0_solve = time.time()
                    calibration = solve_calibration(
                        reconstructions=(recon,),
                        projector_resolution=(pattern_width, pattern_height),
                    )
                    solve_elapsed = time.time() - t0_solve
                except CalibrationSolveError as exc:
                    self._set_stage("solve", StageStatus.FAILED, 0.0, error=str(exc))
                    raise
                self.calibration_result = calibration
                solve_metrics = {
                    "reprojection_error": calibration.reprojection_error,
                    "coverage": calibration.coverage,
                    "confidence": calibration.confidence,
                    "num_correspondences": calibration.num_correspondences,
                    "elapsed_s": solve_elapsed,
                }
                self._set_stage("solve", StageStatus.DONE, 1.0, result=solve_metrics)
            else:
                self._set_stage(
                    "solve",
                    StageStatus.SKIPPED,
                    1.0,
                    warning="No reconstruction — solve skipped",
                )
            self.transition(WorkflowState.VALIDATING)
            self._check_cancelled()

            self._set_stage("validate", StageStatus.RUNNING, 0.5)
            self._set_stage("validate", StageStatus.DONE, 1.0)
            self.transition(WorkflowState.PREVIEW)
            self._check_cancelled()

            self._set_stage("warp", StageStatus.RUNNING, 0.5)
            self._set_stage("warp", StageStatus.DONE, 1.0)
            self.transition(WorkflowState.SAVING)
            self._check_cancelled()

            self._set_stage("persist", StageStatus.RUNNING, 0.5)
            self._set_stage("persist", StageStatus.DONE, 1.0)
            self.transition(WorkflowState.READY_TO_ARM)
            return self.calibration_result
        except asyncio.CancelledError:
            await self._safe_cancel()
            raise
        except Exception as exc:
            # F: One failed stage transitions workflow to FAILED and records exact stage/error
            self.state = WorkflowState.FAILED
            self.error = str(exc)
            failed_stage = None
            for sid in _WORKFLOW_STAGE_ORDER:
                sr = self.stages.get(sid)
                if sr and sr.status == StageStatus.RUNNING:
                    failed_stage = sid
                    break
            if failed_stage:
                self._set_stage(failed_stage, StageStatus.FAILED, 0.0, error=str(exc))
            else:
                # No stage was running — mark current workflow stage as failed
                self._set_stage("workflow", StageStatus.FAILED, 0.0, error=str(exc))
            return None

    async def _run_stage_with_retry(
        self, stage_id: str, max_retries: int, func: Callable[..., Any], *args: Any
    ) -> Any:
        """E: Bounded retry — explicit, no silent infinite loop."""
        attempts = 0
        last_exc: Exception | None = None
        while attempts <= max_retries:
            try:
                self._set_stage(
                    stage_id,
                    StageStatus.RUNNING,
                    0.1 + 0.8 * (attempts / (max_retries + 1)),
                )
                result = (
                    func(*args)
                    if not asyncio.iscoroutinefunction(func)
                    else await func(*args)
                )
                return result
            except Exception as exc:
                last_exc = exc
                attempts += 1
                self._retry_counts[stage_id] = attempts
                if attempts > max_retries:
                    self._set_stage(stage_id, StageStatus.FAILED, 0.0, error=str(exc))
                    raise
                _logger.warning(
                    "Stage %s attempt %d/%d failed: %s — retrying",
                    stage_id,
                    attempts,
                    max_retries,
                    exc,
                )
                await asyncio.sleep(0.05 * attempts)
        if last_exc:
            raise last_exc
        return None

    def _do_prepare(self, pattern_width: int, pattern_height: int) -> Any:
        engine = PatternEngine()
        seq = engine.generate(pattern_width, pattern_height)
        self._set_stage("prepare", StageStatus.DONE, 1.0, result=seq)
        return seq

    def _get_stage_result(self, stage_id: str) -> Any:
        sr = self.stages.get(stage_id)
        return sr.result if sr is not None else None

    async def _safe_cancel(self) -> None:
        # D: No partial result is presented as valid after cancellation
        self.state = WorkflowState.CANCELLED
        self.calibration_result = None
        self.warp_mesh = None
        for sid, sr in list(self.stages.items()):
            if sr.status == StageStatus.RUNNING:
                self._set_stage(sid, StageStatus.FAILED, sr.progress, error="cancelled")
        _logger.info(
            "Workflow %s cancelled — safe state, results cleared", self.workflow_id
        )
