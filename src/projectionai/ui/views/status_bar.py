"""StatusBar — always-on telemetry strip (UX-ARCHITECTURE.md §2.1, P3).

The bottom strip is the "Nothing hidden" principle: output state, FPS,
latency, resolution, GPU/memory and job activity are always visible.
A left-aligned hint shows contextual keyboard hints ("Press G to move
selection"); the right-aligned permanent widgets show project · scene/
cameras/projectors · ● output state · FPS · latency · resolution ·
GPU/memory · dropped frames · jobs.

Follows the :class:`StatusViewModel` observation contract with a
push+poll hybrid: the widget subscribes so any external
``vm.refresh()`` updates it immediately, and a 500 ms timer pulls
``vm.refresh()`` to catch manager-side drift (e.g. performance
telemetry, which is set without notifying).
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QStatusBar, QWidget

from projectionai.ui.theme import (
    ACCENT,
    OK_GREEN,
    TEXT_DIM,
    TEXT_FAINT,
    WARN_YELLOW,
)
from projectionai.ui.viewmodels.status import StatusViewModel


class StatusBar(QStatusBar):
    """Bottom telemetry strip bound to a :class:`StatusViewModel`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mainStatusBar")
        self.setSizeGripEnabled(False)
        self._viewmodel: StatusViewModel | None = None
        self._latency_ms: float | None = None
        self._resolution: tuple[int, int, float] | None = None
        self._dropped_frames: int = 0
        self._indicator_count = 0

        self._project_label = self._add_indicator("No Project")
        self._scene_label = self._add_indicator("—")
        self._live_label = self._add_indicator("● IDLE", object_name="liveStateLabel")
        self._hardware_label = self._add_indicator("0 disp · 0 proj")
        self._health_label = self._add_indicator("● OK", object_name="healthLabel")
        self._fps_label = self._add_indicator("— FPS")
        self._latency_label = self._add_indicator("— ms")
        self._res_label = self._add_indicator("—")
        self._gpu_label = self._add_indicator("GPU —")
        self._dropped_label = self._add_indicator("✓ 0 dropped")
        self._jobs_label = self._add_indicator("Jobs idle")

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # -- Construction helpers -------------------------------------------------

    def _add_indicator(self, text: str, object_name: str = "") -> QLabel:
        """Append a right-aligned permanent label with a leading separator."""
        if self._indicator_count > 0:
            self.addPermanentWidget(self._separator())
        label = QLabel(text)
        if object_name:
            label.setObjectName(object_name)
        self.addPermanentWidget(label)
        self._indicator_count += 1
        return label

    @staticmethod
    def _separator() -> QLabel:
        label = QLabel("│")
        label.setStyleSheet(f"color: {TEXT_FAINT};")
        return label

    # -- View model -----------------------------------------------------------

    def bind_viewmodel(self, viewmodel: StatusViewModel | None) -> None:
        """Attach the status view model and refresh immediately."""
        if self._viewmodel is not None:
            self._viewmodel.unsubscribe(self._on_changed)
        self._viewmodel = viewmodel
        if viewmodel is not None:
            viewmodel.subscribe(self._on_changed)
        self.refresh()

    def _on_changed(self) -> None:
        """Re-render when the view model notifies."""
        self.refresh()

    def refresh(self) -> None:
        """Re-read the view model into the indicator labels."""
        vm = self._viewmodel
        if vm is None:
            self._project_label.setText("No Project")
            self._scene_label.setText("—")
            self._live_label.setText("● IDLE")
            self._live_label.setStyleSheet(f"color: {TEXT_DIM};")
            self._hardware_label.setText("0 disp · 0 proj")
            self._health_label.setText("● OK")
            self._health_label.setStyleSheet(f"color: {TEXT_DIM};")
            self._fps_label.setText("— FPS")
            self._latency_label.setText("— ms")
            self._res_label.setText("—")
            self._gpu_label.setText("GPU —")
            self._dropped_label.setText("✓ 0 dropped")
            self._dropped_label.setStyleSheet(f"color: {TEXT_DIM};")
            self._jobs_label.setText("Jobs idle")
            return

        self._project_label.setText(
            f"{vm.project_name}{' ●' if vm.project_dirty else ''}"
        )
        self._project_label.setStyleSheet(
            f"color: {ACCENT};" if vm.project_dirty else ""
        )
        self._scene_label.setText(
            f"{vm.active_scene_name} · {vm.camera_count} Cam · "
            f"{vm.projector_count} Proj"
        )
        state = vm.output_label.upper()
        self._live_label.setText(f"● {state}")
        self._live_label.setStyleSheet(f"color: {vm.output_color};")
        self._hardware_label.setText(
            f"{vm.display_count} disp · {vm.projector_count} proj"
        )
        healthy = vm.hardware_healthy
        self._health_label.setText("● OK" if healthy else "⚠ ISSUES")
        self._health_label.setStyleSheet(
            f"color: {OK_GREEN};" if healthy else f"color: {WARN_YELLOW};"
        )
        self._fps_label.setText(f"{vm.fps:.0f} FPS")
        self._latency_label.setText(
            "— ms" if self._latency_ms is None else f"{self._latency_ms:.1f} ms"
        )
        if self._resolution is not None:
            width, height, fps = self._resolution
            self._res_label.setText(f"{width}x{height} @ {int(fps)}")
        else:
            self._res_label.setText("—")
        self._gpu_label.setText(f"{vm.gpu_name} · {vm.memory_mb} MB")
        dropped = self._dropped_frames
        self._dropped_label.setText(f"{'⚠' if dropped else '✓'} {dropped} dropped")
        self._dropped_label.setStyleSheet(
            f"color: {WARN_YELLOW};" if dropped else f"color: {TEXT_DIM};"
        )
        self._jobs_label.setText(vm.job_summary)

    # -- Poll loop -------------------------------------------------------------

    def _poll(self) -> None:
        """Pull fresh manager state through the view model."""
        if self._viewmodel is not None:
            self._viewmodel.refresh()

    # -- External feeds ----------------------------------------------------------

    def set_hint(self, text: str) -> None:
        """Set the left-aligned contextual hint (e.g. ``"Press G to move"``)."""
        self.showMessage(text)

    def set_latency(self, latency_ms: float | None) -> None:
        """Set the measured output latency (``None`` = unknown)."""
        self._latency_ms = latency_ms
        self.refresh()

    def set_resolution(self, width: int, height: int, fps: float) -> None:
        """Set the program resolution / frame rate readout."""
        self._resolution = (width, height, fps)
        self.refresh()

    def set_dropped_frames(self, count: int) -> None:
        """Set the dropped-frame counter (⚠ when non-zero)."""
        self._dropped_frames = max(0, count)
        self.refresh()

    # -- Teardown ----------------------------------------------------------------

    def shutdown(self) -> None:
        """Stop polling, unsubscribe, and reset the strip."""
        self._timer.stop()
        if self._viewmodel is not None:
            self._viewmodel.unsubscribe(self._on_changed)
        self._viewmodel = None
        self.clearMessage()
        self.refresh()
