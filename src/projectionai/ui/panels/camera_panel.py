"""CameraPanel — camera list, open/close, and live preview (left dock).

Camera-specific panel bound to the shared
:class:`~projectionai.ui.viewmodels.devices.DevicesViewModel` (the
camera half of the devices view model). Enumeration, capture, and
preview control are async on the manager side, so actions are
scheduled through ``run_async``; frames arrive synchronously on the
main thread via the view model's frame subscriber and are rendered by
a ~30 fps ``QTimer`` that always paints the newest frame.
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from projectionai.services.camera import CameraInfo, Frame
from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.panels.common import make_action_button, make_section_header
from projectionai.ui.theme import BORDER, LIVE_RED, OK_GREEN, TEXT_DIM, WELL_BG
from projectionai.ui.widgets.panel_base import run_async

_USER_ROLE = int(Qt.ItemDataRole.UserRole)

_PREVIEW_INTERVAL_MS = 33


class CameraPanel(ViewModelPanel):
    """Camera device list with refresh/open/close and live preview."""

    panel_id = "camera"

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("cameraPanel")

        self._current_frame: Frame | None = None
        self._last_rendered_frame = -1
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(_PREVIEW_INTERVAL_MS)
        self._preview_timer.timeout.connect(self._render_preview_frame)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(
            make_section_header(
                "CAMERA",
                self._refresh_cameras,
                action_text="Refresh",
                action_tooltip="Re-scan connected cameras",
            )
        )
        self.preview_label = QLabel("No preview")
        self.preview_label.setObjectName("cameraPreviewLabel")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(180)
        self.preview_label.setStyleSheet(
            f"background: {WELL_BG}; border: 1px solid {BORDER};"
            f" color: {TEXT_DIM}; border-radius: 4px;"
        )
        root.addWidget(self.preview_label)
        self.preview_info_label = QLabel("idle")
        self.preview_info_label.setObjectName("cameraPreviewInfo")
        self.preview_info_label.setStyleSheet(f"color: {TEXT_DIM}; padding: 2px 4px;")
        root.addWidget(self.preview_info_label)

        self.camera_list = QListWidget()
        self.camera_list.setObjectName("cameraList")
        self.camera_list.itemClicked.connect(self._camera_clicked)
        root.addWidget(self.camera_list, stretch=1)

        self.status_label = QLabel("No cameras")
        self.status_label.setObjectName("cameraStatusLabel")
        self.status_label.setStyleSheet(f"color: {TEXT_DIM}; padding: 2px 4px;")
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(4, 4, 4, 4)
        actions.setSpacing(4)
        actions.addWidget(make_action_button("Refresh", self._refresh_cameras))
        self.preview_button = make_action_button("Preview", self._start_preview)
        self.stop_button = make_action_button("Stop", self._stop_preview)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.stop_button)
        actions.addWidget(make_action_button("Open", self._open_selected))
        actions.addWidget(make_action_button("Close", self._close_selected))
        actions.addStretch(1)
        root.addLayout(actions)

    # -- Refresh -------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the camera list from the view model."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._refresh_cameras_list()
        finally:
            self._refreshing = False

    def clear(self) -> None:
        """Empty the camera list and reset the preview area."""
        self._preview_timer.stop()
        self._reset_preview_display()
        self._update_preview_info()
        self.camera_list.clear()
        self.status_label.setText("No cameras")
        self.status_label.setStyleSheet(f"color: {TEXT_DIM}; padding: 2px 4px;")

    def shutdown(self) -> None:
        """Stop previewing, then detach from the view model."""
        self._preview_timer.stop()
        vm = self._viewmodel
        if vm is not None and hasattr(vm, "stop_preview"):
            run_async(vm.stop_preview())
        super().shutdown()

    def _refresh_cameras_list(self) -> None:
        vm = self._viewmodel
        selected = self._selected_camera_id()
        self.camera_list.clear()
        if vm is None:
            self.status_label.setText("Camera view model not bound")
            return
        cameras = vm.cameras()
        open_count = sum(1 for camera in cameras if vm.is_open(camera.camera_id))
        live_id = getattr(vm, "preview_camera_id", None)
        error = getattr(vm, "preview_error", lambda: None)()
        if error:
            self.status_label.setText(error)
            self.status_label.setStyleSheet(f"color: {LIVE_RED}; padding: 2px 4px;")
        else:
            self.status_label.setText(f"{len(cameras)} camera(s) · {open_count} open")
            self.status_label.setStyleSheet(f"color: {TEXT_DIM}; padding: 2px 4px;")
        for camera in cameras:
            self.camera_list.addItem(
                self._camera_item(
                    camera,
                    vm.is_open(camera.camera_id),
                    live=camera.camera_id == live_id,
                )
            )
        if selected is not None:
            for i in range(self.camera_list.count()):
                item = self.camera_list.item(i)
                if item.data(_USER_ROLE) == selected:
                    self.camera_list.setCurrentItem(item)
                    break
        self._sync_preview_ui()

    # -- Item builders --------------------------------------------------------

    @classmethod
    def _camera_item(
        cls, camera: CameraInfo, is_open: bool, live: bool = False
    ) -> QListWidgetItem:
        backend = camera.backend or "unknown"
        resolution = camera.max_resolution
        res_text = f"{resolution[0]}x{resolution[1]}" if resolution else "—"
        if live:
            status = "LIVE"
            color = LIVE_RED
        elif is_open:
            status = "OPEN"
            color = OK_GREEN
        else:
            status = "closed"
            color = TEXT_DIM
        item = QListWidgetItem(
            f"{camera.name}  ·  {backend}  ·  {res_text}  ·  {status}"
        )
        item.setData(_USER_ROLE, camera.camera_id)
        item.setForeground(QColor(color))
        return item

    # -- Live preview ----------------------------------------------------------

    def _start_preview(self) -> None:
        vm = self._viewmodel
        camera_id = self._selected_camera_id()
        if vm is None or camera_id is None or not hasattr(vm, "start_preview"):
            return
        self._preview_timer.start()
        run_async(vm.start_preview(camera_id))

    def _stop_preview(self) -> None:
        vm = self._viewmodel
        if vm is None or not hasattr(vm, "stop_preview"):
            return
        self._preview_timer.stop()
        run_async(vm.stop_preview())

    def _render_preview_frame(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        if getattr(vm, "preview_camera_id", None) is None:
            return
        frame = getattr(vm, "latest_frame", lambda: None)()
        if frame is None or frame.frame_number == self._last_rendered_frame:
            return
        self._current_frame = frame
        self._display_frame(frame)
        self._last_rendered_frame = frame.frame_number
        mark_rendered = getattr(vm, "mark_frame_rendered", None)
        if mark_rendered is not None:
            mark_rendered(frame.frame_number)
        self._update_preview_info()

    def _display_frame(self, frame: Frame) -> None:
        image = QImage(
            frame.image.data,
            frame.width,
            frame.height,
            3 * frame.width,
            QImage.Format.Format_RGB888,
        )
        pixmap = QPixmap.fromImage(image)
        size = self.preview_label.size()
        if size.isEmpty():
            size = QSize(frame.width, frame.height)
        scaled = pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    def _sync_preview_ui(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        preview_id = getattr(vm, "preview_camera_id", None)
        if preview_id is None:
            self._preview_timer.stop()
            self._reset_preview_display()
        else:
            # Camera switched: the previous camera's frame and frame
            # number are stale, so drop them before the new camera's
            # frames arrive. Otherwise the first frame of the new
            # camera is skipped when its frame number coincides with
            # the previous camera's last rendered one.
            current_id = (
                self._current_frame.camera_id
                if self._current_frame is not None
                else None
            )
            if current_id != preview_id:
                self._reset_preview_display()
            self._preview_timer.start()
        self._update_preview_info()

    def _update_preview_info(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        preview_id = getattr(vm, "preview_camera_id", None)
        if preview_id is None:
            self.preview_info_label.setText("idle")
            self.preview_info_label.setStyleSheet(
                f"color: {TEXT_DIM}; padding: 2px 4px;"
            )
            return
        frame = self._current_frame
        fps = getattr(vm, "preview_fps", 30)
        frames = getattr(vm, "frame_count", 0)
        dropped = getattr(vm, "dropped_count", 0)
        if frame is not None:
            text = (
                f"LIVE · {preview_id} · {frame.width}x{frame.height}"
                f" · {fps} fps · {frames} frames · {dropped} dropped"
            )
        else:
            text = f"LIVE · {preview_id} · {fps} fps"
        self.preview_info_label.setText(text)
        self.preview_info_label.setStyleSheet(f"color: {OK_GREEN}; padding: 2px 4px;")

    def _reset_preview_display(self) -> None:
        self._current_frame = None
        self._last_rendered_frame = -1
        self.preview_label.setText("No preview")
        self.preview_label.setStyleSheet(
            f"background: {WELL_BG}; border: 1px solid {BORDER};"
            f" color: {TEXT_DIM}; border-radius: 4px;"
        )

    # -- Interactions -----------------------------------------------------------

    def _refresh_cameras(self) -> None:
        if self._viewmodel is not None:
            run_async(self._viewmodel.refresh_cameras())

    def _camera_clicked(self, item: QListWidgetItem) -> None:
        self.camera_list.setCurrentItem(item)

    def _selected_camera_id(self) -> str | None:
        item = self.camera_list.currentItem()
        if item is None:
            return None
        return cast(str | None, item.data(_USER_ROLE))

    def _open_selected(self) -> None:
        vm = self._viewmodel
        camera_id = self._selected_camera_id()
        if vm is None or camera_id is None:
            return
        run_async(vm.open_camera(camera_id))

    def _close_selected(self) -> None:
        vm = self._viewmodel
        camera_id = self._selected_camera_id()
        if vm is None or camera_id is None:
            return
        run_async(vm.close_camera(camera_id))
