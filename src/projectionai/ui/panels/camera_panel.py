"""CameraPanel — camera device list with open/close actions (left dock).

Camera-specific panel bound to the shared
:class:`~projectionai.ui.viewmodels.devices.DevicesViewModel` (the
camera half of the devices view model). Enumeration is async on the
manager side, so actions are scheduled through ``run_async``.
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from projectionai.services.camera import CameraInfo
from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.panels.common import make_action_button, make_section_header
from projectionai.ui.theme import OK_GREEN, TEXT_DIM
from projectionai.ui.widgets.panel_base import run_async

_USER_ROLE = int(Qt.ItemDataRole.UserRole)


class CameraPanel(ViewModelPanel):
    """Camera device list with refresh/open/close actions."""

    panel_id = "camera"

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("cameraPanel")

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
        """Empty the camera list."""
        self.camera_list.clear()
        self.status_label.setText("No cameras")

    def _refresh_cameras_list(self) -> None:
        vm = self._viewmodel
        selected = self._selected_camera_id()
        self.camera_list.clear()
        if vm is None:
            self.status_label.setText("Camera view model not bound")
            return
        cameras = vm.cameras()
        open_count = sum(1 for camera in cameras if vm.is_open(camera.camera_id))
        self.status_label.setText(f"{len(cameras)} camera(s) · {open_count} open")
        for camera in cameras:
            self.camera_list.addItem(
                self._camera_item(camera, vm.is_open(camera.camera_id))
            )
        if selected is not None:
            for i in range(self.camera_list.count()):
                item = self.camera_list.item(i)
                if item.data(_USER_ROLE) == selected:
                    self.camera_list.setCurrentItem(item)
                    break

    # -- Item builders --------------------------------------------------------

    @classmethod
    def _camera_item(cls, camera: CameraInfo, is_open: bool) -> QListWidgetItem:
        backend = camera.backend or "unknown"
        resolution = camera.max_resolution
        res_text = f"{resolution[0]}x{resolution[1]}" if resolution else "—"
        status = "OPEN" if is_open else "closed"
        color = OK_GREEN if is_open else TEXT_DIM
        item = QListWidgetItem(
            f"{camera.name}  ·  {backend}  ·  {res_text}  ·  {status}"
        )
        item.setData(_USER_ROLE, camera.camera_id)
        item.setForeground(QColor(color))
        return item

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
