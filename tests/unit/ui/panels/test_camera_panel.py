"""Tests for CameraPanel (refresh, selection, open/close actions).

The panel reads a duck-typed DevicesViewModel: ``cameras()`` returns
``CameraInfo`` rows, ``is_open(camera_id)`` marks open devices, and
open/close actions are scheduled through ``run_async`` (which runs the
coroutine synchronously when no loop is running, as in these tests).
Rendering happens offscreen (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.services.camera import CameraInfo
from projectionai.ui.panels.camera_panel import CameraPanel


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Return the process-wide QApplication (created once)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _camera(camera_id: str, name: str) -> CameraInfo:
    return CameraInfo(
        camera_id=camera_id,
        name=name,
        backend="mock",
        max_resolution=(640, 480),
    )


class _FakeDevicesViewModel:
    """Duck-typed stand-in for DevicesViewModel."""

    def __init__(self, cameras: list[CameraInfo], open_ids: set[str]) -> None:
        self._cameras = cameras
        self._open = open_ids
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.refreshes = 0

    def cameras(self) -> list[CameraInfo]:
        return self._cameras

    def is_open(self, camera_id: str) -> bool:
        return camera_id in self._open

    def subscribe(self, handler: Any) -> None:
        """No-op: tests drive refresh() directly."""

    def unsubscribe(self, handler: Any) -> None:
        """No-op."""

    async def refresh_cameras(self) -> int:
        self.refreshes += 1
        return len(self._cameras)

    async def open_camera(self, camera_id: str) -> bool:
        self.opened.append(camera_id)
        return True

    async def close_camera(self, camera_id: str) -> None:
        self.closed.append(camera_id)


class TestRefresh:
    def test_populates_list_and_status(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel(
            [_camera("cam-0", "Front"), _camera("cam-1", "Rear")], {"cam-0"}
        )
        panel = CameraPanel()
        panel.bind_viewmodel(vm)

        assert panel.camera_list.count() == 2
        assert "Front" in panel.camera_list.item(0).text()
        assert "OPEN" in panel.camera_list.item(0).text()
        assert "Rear" in panel.camera_list.item(1).text()
        assert "closed" in panel.camera_list.item(1).text()
        assert "2 camera(s) · 1 open" in panel.status_label.text()

    def test_without_viewmodel_shows_unbound(self, qapp: QApplication) -> None:
        panel = CameraPanel()
        panel.refresh()
        assert "Camera view model not bound" in panel.status_label.text()

    def test_clear_empties_list(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel([_camera("cam-0", "Front")], set())
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel.clear()
        assert panel.camera_list.count() == 0
        assert panel.status_label.text() == "No cameras"

    def test_refresh_action_schedules_viewmodel_refresh(
        self, qapp: QApplication
    ) -> None:
        vm = _FakeDevicesViewModel([_camera("cam-0", "Front")], set())
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._refresh_cameras()
        assert vm.refreshes == 1

    def test_refresh_action_without_viewmodel_is_noop(self, qapp: QApplication) -> None:
        panel = CameraPanel()
        panel._refresh_cameras()


class TestOpenCloseActions:
    def test_open_selected(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel([_camera("cam-0", "Front")], set())
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel.camera_list.setCurrentRow(0)
        panel._open_selected()
        assert vm.opened == ["cam-0"]

    def test_close_selected(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel([_camera("cam-0", "Front")], {"cam-0"})
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel.camera_list.setCurrentRow(0)
        panel._close_selected()
        assert vm.closed == ["cam-0"]

    def test_open_without_selection_is_noop(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel([_camera("cam-0", "Front")], set())
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._open_selected()
        assert vm.opened == []

    def test_actions_without_viewmodel_are_noop(self, qapp: QApplication) -> None:
        panel = CameraPanel()
        panel._open_selected()
        panel._close_selected()
