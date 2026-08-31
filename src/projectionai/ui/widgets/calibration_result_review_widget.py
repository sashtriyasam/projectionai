"""Calibration Result Review Widget — presentation only, no solver/math."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from projectionai.ui.theme import (
    ACCENT,
    LIVE_RED,
    OK_GREEN,
    PANEL_BG,
    TEXT,
    TEXT_DIM,
    WARN_YELLOW,
    WINDOW_BG,
)
from projectionai.ui.viewmodels.calibration_result_review import (
    CalibrationResultReviewViewModel,
)

_POLL_INTERVAL_MS = 250

_STATUS_COLORS: dict[str, str] = {
    "SUCCESS": OK_GREEN,
    "WARNING": WARN_YELLOW,
    "FAILED": LIVE_RED,
    "NO RESULT": TEXT_DIM,
}


def _make_separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    line.setStyleSheet(f"color: {WINDOW_BG}; background: {WINDOW_BG};")
    line.setFixedHeight(1)
    return line


class CalibrationResultReviewWidget(QWidget):
    """Review panel for a canonical CalibrationResult.

    - Reads from CalibrationResultReviewViewModel (poll-based).
    - Never mutates the result; decision stored in ViewModel.
    - Signals for host to wire: accepted, rejected, recalibrate, cancelled.
    """

    accepted_for_preview = Signal()
    rejected = Signal()
    recalibrate_requested = Signal()
    cancelled = Signal()

    def __init__(
        self,
        viewmodel: CalibrationResultReviewViewModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel
        self._last_revision: int = -1
        self._advanced_visible: bool = False

        self.setObjectName("calibrationResultReviewWidget")
        self.setStyleSheet(
            f"background: {PANEL_BG}; color: {TEXT};"
            f"QWidget#calibrationResultReviewWidget {{ background: {PANEL_BG}; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background: {PANEL_BG}; border: none;")
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet(f"background: {PANEL_BG};")
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # -- Title ---------------------------------------------------------
        title = QLabel("Calibration Result")
        title.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {TEXT};")
        root.addWidget(title)

        # Status banner
        self._status_label = QLabel("NO RESULT")
        self._status_label.setObjectName("reviewStatusLabel")
        self._status_label.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {TEXT_DIM};"
            f"padding: 6px 8px; border-radius: 4px; background: {WINDOW_BG};"
        )
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._status_label)

        self._eligibility_label = QLabel("")
        self._eligibility_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        self._eligibility_label.setWordWrap(True)
        root.addWidget(self._eligibility_label)

        root.addWidget(_make_separator())

        # Source mode
        self._source_label = QLabel("SOURCE: SYNTHETIC")
        self._source_label.setStyleSheet(
            f"font-weight: bold; font-size: 11px; color: {ACCENT};"
        )
        root.addWidget(self._source_label)

        self._physical_label = QLabel("PHYSICAL VALIDATION: NOT VERIFIED")
        self._physical_label.setStyleSheet(f"color: {WARN_YELLOW}; font-size: 11px;")
        root.addWidget(self._physical_label)

        root.addWidget(_make_separator())

        # Summary
        summary_header = QLabel("Summary")
        summary_header.setStyleSheet(f"font-weight: bold; color: {TEXT_DIM};")
        root.addWidget(summary_header)

        self._camera_label = QLabel("Camera: —")
        self._projector_label = QLabel("Projector: —")
        self._surface_label = QLabel("Surface: —")
        self._resolution_label = QLabel("Resolution: —")
        self._method_label = QLabel("Method: —")
        self._orientations_label = QLabel("Orientations: —")
        for lbl in (
            self._camera_label,
            self._projector_label,
            self._surface_label,
            self._resolution_label,
            self._method_label,
            self._orientations_label,
        ):
            lbl.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
            lbl.setWordWrap(True)
            root.addWidget(lbl)

        root.addWidget(_make_separator())

        # Quality
        quality_header = QLabel("Quality")
        quality_header.setStyleSheet(f"font-weight: bold; color: {TEXT_DIM};")
        root.addWidget(quality_header)

        self._reproj_label = QLabel("Reprojection RMS: —")
        self._coverage_label = QLabel("Coverage: —")
        self._confidence_label = QLabel("Confidence: —")
        self._corr_label = QLabel("Correspondences: —")
        self._orientation_count_label = QLabel("Orientation count: —")
        self._per_plane_label = QLabel("Per-point errors: —")
        for lbl in (
            self._reproj_label,
            self._coverage_label,
            self._confidence_label,
            self._corr_label,
            self._orientation_count_label,
            self._per_plane_label,
        ):
            lbl.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
            lbl.setWordWrap(True)
            root.addWidget(lbl)

        root.addWidget(_make_separator())

        # Intrinsics
        intr_header = QLabel("Intrinsics  (projector, pixels)")
        intr_header.setStyleSheet(f"font-weight: bold; color: {TEXT_DIM};")
        root.addWidget(intr_header)

        self._intrinsics_label = QLabel("fx —  fy —  cx —  cy —")
        self._intrinsics_label.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        root.addWidget(self._intrinsics_label)

        self._intrinsics_matrix = QLabel("—")
        self._intrinsics_matrix.setStyleSheet(
            f"color: {TEXT_DIM}; font-family: monospace; font-size: 11px;"
            f"background: {WINDOW_BG}; padding: 6px; border-radius: 4px;"
        )
        self._intrinsics_matrix.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self._intrinsics_matrix)

        root.addWidget(_make_separator())

        # Pose
        pose_header = QLabel("Pose  (projector → camera)")
        pose_header.setStyleSheet(f"font-weight: bold; color: {TEXT_DIM};")
        root.addWidget(pose_header)

        self._pose_frame_label = QLabel("Frame: projector → camera")
        self._pose_frame_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        root.addWidget(self._pose_frame_label)

        self._pose_translation_label = QLabel("Translation: —")
        self._pose_translation_label.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        self._pose_translation_label.setWordWrap(True)
        root.addWidget(self._pose_translation_label)

        self._pose_quat_label = QLabel("Orientation (quat w,x,y,z): —")
        self._pose_quat_label.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        self._pose_quat_label.setWordWrap(True)
        root.addWidget(self._pose_quat_label)

        self._pose_matrix = QLabel("—")
        self._pose_matrix.setStyleSheet(
            f"color: {TEXT_DIM}; font-family: monospace; font-size: 11px;"
            f"background: {WINDOW_BG}; padding: 6px; border-radius: 4px;"
        )
        self._pose_matrix.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self._pose_matrix)

        root.addWidget(_make_separator())

        # Warnings
        self._warnings_label = QLabel("")
        self._warnings_label.setWordWrap(True)
        self._warnings_label.setStyleSheet(f"color: {WARN_YELLOW}; font-size: 11px;")
        self._warnings_label.hide()
        root.addWidget(self._warnings_label)

        # Blocking errors
        self._errors_label = QLabel("")
        self._errors_label.setWordWrap(True)
        self._errors_label.setStyleSheet(f"color: {LIVE_RED}; font-size: 11px;")
        self._errors_label.hide()
        root.addWidget(self._errors_label)

        # Gate failures (dedicated section — shown when gate_result has failures)
        self._gate_failures_label = QLabel("")
        self._gate_failures_label.setWordWrap(True)
        self._gate_failures_label.setStyleSheet(f"color: {LIVE_RED}; font-size: 11px;")
        self._gate_failures_label.hide()
        root.addWidget(self._gate_failures_label)

        # Stale gate warning
        self._stale_gate_label = QLabel("")
        self._stale_gate_label.setWordWrap(True)
        self._stale_gate_label.setStyleSheet(
            f"color: {WARN_YELLOW}; font-size: 11px; font-weight: bold;"
        )
        self._stale_gate_label.hide()
        root.addWidget(self._stale_gate_label)

        # Hardware pending
        hw_header = QLabel("HARDWARE PENDING")
        hw_header.setStyleSheet(
            f"font-weight: bold; color: {WARN_YELLOW}; font-size: 11px;"
        )
        root.addWidget(hw_header)

        self._hw_frame = QFrame()
        self._hw_layout = QVBoxLayout(self._hw_frame)
        self._hw_layout.setContentsMargins(0, 0, 0, 0)
        self._hw_layout.setSpacing(2)
        self._hw_labels: list[QLabel] = []
        root.addWidget(self._hw_frame)

        root.addWidget(_make_separator())

        # Actions
        actions_header = QLabel("Actions")
        actions_header.setStyleSheet(f"font-weight: bold; color: {TEXT_DIM};")
        root.addWidget(actions_header)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        self._continue_btn = QPushButton("Continue to preview")
        self._continue_btn.setObjectName("primaryButton")
        self._continue_btn.setEnabled(False)
        self._continue_btn.clicked.connect(self._on_continue)
        self._recalibrate_btn = QPushButton("Recalibrate")
        self._recalibrate_btn.clicked.connect(self._on_recalibrate)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        actions_row.addWidget(self._continue_btn)
        actions_row.addWidget(self._recalibrate_btn)
        actions_row.addWidget(self._cancel_btn)
        actions_row.addStretch(1)
        root.addLayout(actions_row)

        self._reject_btn = QPushButton("Reject")
        self._reject_btn.setStyleSheet(
            f"QPushButton {{ background: {WINDOW_BG}; color: {TEXT_DIM}; border: 1px solid {LIVE_RED}; padding: 4px 12px; border-radius: 3px; }}"
        )
        self._reject_btn.clicked.connect(self._on_reject)
        root.addWidget(self._reject_btn)

        root.addWidget(_make_separator())

        # Advanced details (expandable)
        self._advanced_toggle = QToolButton()
        self._advanced_toggle.setText("Advanced details  ▸")
        self._advanced_toggle.setCheckable(True)
        self._advanced_toggle.setStyleSheet(
            f"QToolButton {{ color: {TEXT_DIM}; font-size: 11px; border: none; text-align: left; padding: 4px; }}"
            f"QToolButton:hover {{ color: {TEXT}; }}"
        )
        self._advanced_toggle.toggled.connect(self._on_toggle_advanced)
        root.addWidget(self._advanced_toggle)

        self._advanced_frame = QFrame()
        self._advanced_frame.setStyleSheet(
            f"background: {WINDOW_BG}; border-radius: 4px;"
        )
        adv_layout = QVBoxLayout(self._advanced_frame)
        adv_layout.setContentsMargins(8, 8, 8, 8)
        adv_layout.setSpacing(4)

        self._adv_calib_id = QLabel("Calibration ID: —")
        self._adv_sequence_ids = QLabel("Sequence IDs: —")
        self._adv_method = QLabel("Method: —")
        self._adv_resolution = QLabel("Projector resolution: —")
        self._adv_camera_matrix = QLabel("Camera matrix: —")
        self._adv_distortion = QLabel("Distortion: —")
        self._adv_corr_count = QLabel("Correspondence count: —")
        self._adv_per_point = QLabel("Per-point stats: —")
        self._adv_created = QLabel("Created: —")
        self._adv_metadata = QLabel("Metadata: —")
        for lbl in (
            self._adv_calib_id,
            self._adv_sequence_ids,
            self._adv_method,
            self._adv_resolution,
            self._adv_camera_matrix,
            self._adv_distortion,
            self._adv_corr_count,
            self._adv_per_point,
            self._adv_created,
            self._adv_metadata,
        ):
            lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            adv_layout.addWidget(lbl)

        self._advanced_frame.hide()
        root.addWidget(self._advanced_frame)

        root.addStretch(1)

        # Poll timer
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # -- Slots -----------------------------------------------------------

    def _on_continue(self) -> None:
        self._vm.accept()
        self.accepted_for_preview.emit()

    def _on_reject(self) -> None:
        self._vm.reject()
        self.rejected.emit()

    def _on_recalibrate(self) -> None:
        self._vm.needs_recalibration()
        self.recalibrate_requested.emit()

    def _on_cancel(self) -> None:
        self.cancelled.emit()

    def _on_toggle_advanced(self, checked: bool) -> None:
        self._advanced_visible = checked
        self._advanced_frame.setVisible(checked)
        self._advanced_toggle.setText(
            "Advanced details  ▾" if checked else "Advanced details  ▸"
        )

    # -- Public API ------------------------------------------------------

    def refresh(self) -> None:
        if self._vm.revision == self._last_revision:
            return
        self._last_revision = self._vm.revision
        vm = self._vm

        # Status
        kind = vm.status_kind
        color = _STATUS_COLORS.get(kind, TEXT_DIM)
        self._status_label.setText(vm.status_text)
        self._status_label.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {color};"
            f"padding: 6px 8px; border-radius: 4px; background: {WINDOW_BG};"
        )
        self._eligibility_label.setText(vm.eligibility_text)

        # Source
        self._source_label.setText(vm.source_label)
        self._physical_label.setText(vm.physical_validation_label)

        # Summary
        self._camera_label.setText(f"Camera: {vm.camera_id or '—'}")
        self._projector_label.setText(f"Projector: {vm.projector_id or '—'}")
        self._surface_label.setText(f"Surface: {vm.surface_id or '—'}")
        self._resolution_label.setText(f"Resolution: {vm.projector_resolution_text}")
        self._method_label.setText(f"Method: {vm.method or '—'}")
        ori_ids = ", ".join(vm.orientation_ids) if vm.orientation_ids else "—"
        self._orientations_label.setText(
            f"Orientations ({vm.orientation_count}): {ori_ids}"
        )

        # Quality
        self._reproj_label.setText(f"Reprojection RMS: {vm.reprojection_error:.3f} px")
        self._coverage_label.setText(f"Coverage: {vm.coverage:.1%}")
        self._confidence_label.setText(f"Confidence: {vm.confidence:.2f}")
        self._corr_label.setText(f"Correspondences: {vm.num_correspondences}")
        self._orientation_count_label.setText(
            f"Orientation count: {vm.orientation_count}"
        )
        stats = vm.per_point_stats
        if stats["count"] > 0:
            self._per_plane_label.setText(
                f"Per-point errors — count {int(stats['count'])}  "
                f"mean {stats['mean']:.3f}px  max {stats['max']:.3f}px  rms {stats['rms']:.3f}px"
            )
        else:
            self._per_plane_label.setText("Per-point errors: —")

        # Intrinsics
        intr = vm.intrinsics
        self._intrinsics_label.setText(
            f"fx {intr['fx']:.1f}  fy {intr['fy']:.1f}  cx {intr['cx']:.1f}  cy {intr['cy']:.1f}"
        )
        self._intrinsics_matrix.setText(vm.intrinsics_matrix_text)

        # Pose
        self._pose_translation_label.setText(f"Translation: {vm.pose_translation_text}")
        self._pose_quat_label.setText(
            f"Orientation (quat w,x,y,z): {vm.pose_quaternion_text}"
        )
        self._pose_matrix.setText(vm.pose_matrix_text)

        # Warnings
        warnings = vm.warnings
        if warnings:
            self._warnings_label.setText("Warnings:\n- " + "\n- ".join(warnings))
            self._warnings_label.show()
        else:
            self._warnings_label.hide()

        # Errors
        errors = vm.blocking_errors
        if errors:
            self._errors_label.setText("Blocking errors:\n- " + "\n- ".join(errors))
            self._errors_label.show()
        else:
            self._errors_label.hide()

        # Gate failures (dedicated section)
        gate_summary = vm.gate_failure_summary
        if gate_summary:
            self._gate_failures_label.setText(
                "Gate failures:\n- " + gate_summary.replace("; ", "\n- ")
            )
            self._gate_failures_label.show()
        else:
            self._gate_failures_label.hide()

        # Stale gate warning
        if vm.is_gate_stale:
            age = vm.gate_age_seconds
            age_text = f"{age:.0f}s" if age is not None else "unknown"
            self._stale_gate_label.setText(
                f"GATE STALE — last evaluated {age_text} ago. Re-evaluate before use."
            )
            self._stale_gate_label.show()
        else:
            self._stale_gate_label.hide()

        # Hardware pending
        self._update_hw_gates(vm.hardware_pending)

        # Actions — eligible only when review_ok
        self._continue_btn.setEnabled(vm.review_ok)

        # Advanced
        self._adv_calib_id.setText(f"Calibration ID: {vm.calibration_id or '—'}")
        seq_text = (
            ", ".join(vm.calibration_sequence_ids)
            if vm.calibration_sequence_ids
            else "—"
        )
        self._adv_sequence_ids.setText(f"Sequence IDs: {seq_text}")
        self._adv_method.setText(f"Method: {vm.method or '—'}")
        self._adv_resolution.setText(
            f"Projector resolution: {vm.projector_resolution_text}"
        )
        self._adv_camera_matrix.setText(f"Camera matrix:\n{vm.camera_matrix_text}")
        self._adv_distortion.setText(f"Distortion: {vm.distortion_text}")
        self._adv_corr_count.setText(f"Correspondence count: {vm.num_correspondences}")
        if stats["count"] > 0:
            self._adv_per_point.setText(
                f"Per-point — count {int(stats['count'])} mean {stats['mean']:.3f} "
                f"max {stats['max']:.3f} rms {stats['rms']:.3f}"
            )
        else:
            self._adv_per_point.setText("Per-point: —")
        self._adv_created.setText(f"Created: {vm.created_at_text}")
        meta = vm.result.metadata if vm.result else {}
        meta_text = str(meta) if meta else "—"
        # Truncate very long metadata for display
        if len(meta_text) > 400:
            meta_text = meta_text[:400] + "…"
        self._adv_metadata.setText(f"Metadata: {meta_text}")

    def _update_hw_gates(self, gates: tuple[str, ...]) -> None:
        for lbl in self._hw_labels:
            self._hw_layout.removeWidget(lbl)
            lbl.deleteLater()
        self._hw_labels.clear()
        if not gates:
            empty = QLabel("None — no pending gates")
            empty.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
            self._hw_layout.addWidget(empty)
            self._hw_labels.append(empty)
            return
        for gate in gates:
            lbl = QLabel(f"  ○ {gate}")
            lbl.setStyleSheet(f"color: {WARN_YELLOW}; font-size: 11px;")
            self._hw_layout.addWidget(lbl)
            self._hw_labels.append(lbl)

    def closeEvent(self, event: object) -> None:  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)  # type: ignore[arg-type]
