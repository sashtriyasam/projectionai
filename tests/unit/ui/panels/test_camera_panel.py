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

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.services.camera import CameraInfo, Frame
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


def _frame(camera_id: str, frame_number: int, value: int = 0) -> Frame:
    """Return a 640x480 RGB frame with a constant pixel value."""
    image = np.full((480, 640, 3), value, dtype=np.uint8)
    return Frame(
        image=image,
        timestamp=1.0,
        camera_id=camera_id,
        frame_number=frame_number,
    )


class _FakeDevicesViewModel:
    """Duck-typed stand-in for DevicesViewModel."""

    def __init__(
        self,
        cameras: list[CameraInfo],
        open_ids: set[str],
        preview_id: str | None = None,
    ) -> None:
        self._cameras = cameras
        self._open = open_ids
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.refreshes = 0
        self.preview_camera_id = preview_id
        self.preview_fps = 30
        self.frame_count = 0
        self.dropped_count = 0
        self.preview_error_msg: str | None = None
        self.latest: Frame | None = None
        self.started: list[str] = []
        self.stop_calls = 0
        self.rendered: list[int] = []

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

    async def start_preview(self, camera_id: str, fps: int = 30) -> bool:
        self.started.append(camera_id)
        self.preview_camera_id = camera_id
        self.preview_fps = fps
        return True

    async def stop_preview(self) -> None:
        self.stop_calls += 1
        self.preview_camera_id = None

    def preview_error(self) -> str | None:
        return self.preview_error_msg

    def latest_frame(self) -> Frame | None:
        return self.latest

    def mark_frame_rendered(self, frame_number: int) -> None:
        self.rendered.append(frame_number)


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


class TestPreview:
    def test_start_preview_selected_camera(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel([_camera("cam-0", "Front")], set())
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel.camera_list.setCurrentRow(0)
        panel._start_preview()
        assert vm.started == ["cam-0"]
        assert panel._preview_timer.isActive()

    def test_start_preview_without_selection_is_noop(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel([_camera("cam-0", "Front")], set())
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._start_preview()
        assert vm.started == []

    def test_start_preview_without_viewmodel_is_noop(self, qapp: QApplication) -> None:
        panel = CameraPanel()
        panel._start_preview()

    def test_stop_preview(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel(
            [_camera("cam-0", "Front")], set(), preview_id="cam-0"
        )
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._preview_timer.start()
        panel._stop_preview()
        assert vm.stop_calls == 1
        assert not panel._preview_timer.isActive()

    def test_render_displays_frame_and_marks_rendered(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel(
            [_camera("cam-0", "Front")], set(), preview_id="cam-0"
        )
        vm.latest = _frame("cam-0", 7)
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._render_preview_frame()
        assert panel.preview_label.pixmap() is not None
        assert vm.rendered == [7]
        assert "LIVE · cam-0" in panel.preview_info_label.text()

    def test_render_skips_duplicate_frame(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel(
            [_camera("cam-0", "Front")], set(), preview_id="cam-0"
        )
        vm.latest = _frame("cam-0", 3)
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._render_preview_frame()
        first = panel.preview_label.pixmap().cacheKey()
        vm.latest = _frame("cam-0", 3, value=99)
        panel._render_preview_frame()
        assert vm.rendered == [3]
        assert panel.preview_label.pixmap().cacheKey() == first

    def test_camera_switch_resets_frame_tracking_when_numbers_coincide(
        self, qapp: QApplication
    ) -> None:
        """Switching preview cameras must render the new camera's first
        frame even when its frame number equals the previous camera's last
        rendered one — stale tracking state must not skip it."""
        vm = _FakeDevicesViewModel(
            [_camera("cam-0", "Front"), _camera("cam-1", "Rear")],
            set(),
            preview_id="cam-0",
        )
        vm.latest = _frame("cam-0", 5)
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._render_preview_frame()
        assert vm.rendered == [5]
        first = panel.preview_label.pixmap().cacheKey()

        # Switch to cam-1; its first frame reuses frame number 5.
        vm.preview_camera_id = "cam-1"
        vm.latest = _frame("cam-1", 5, value=99)
        panel._sync_preview_ui()
        panel._render_preview_frame()

        assert vm.rendered == [5, 5]
        assert panel.preview_label.pixmap().cacheKey() != first
        assert panel._current_frame is not None
        assert panel._current_frame.camera_id == "cam-1"
        assert "LIVE · cam-1" in panel.preview_info_label.text()

    def test_restart_preview_renders_colliding_frame_number(
        self, qapp: QApplication
    ) -> None:
        vm = _FakeDevicesViewModel(
            [_camera("cam-0", "Front")], set(), preview_id="cam-0"
        )
        vm.latest = _frame("cam-0", 1)
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._render_preview_frame()
        assert vm.rendered == [1]
        first = panel.preview_label.pixmap().cacheKey()

        # Stop and restart the same camera: the new run restarts frame
        # numbering at 1, which collides with the previous run's last
        # rendered frame — the restarted preview must render it anyway.
        panel._stop_preview()
        vm.preview_camera_id = "cam-0"
        vm.latest = _frame("cam-0", 1, value=99)
        panel.camera_list.setCurrentRow(0)
        panel._start_preview()
        panel._render_preview_frame()

        assert vm.rendered == [1, 1]
        assert panel.preview_label.pixmap().cacheKey() != first
        assert panel._current_frame is not None
        assert panel._current_frame.frame_number == 1

    def test_preview_error_shown_in_preview_info(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel(
            [_camera("cam-0", "Front")], set(), preview_id="cam-0"
        )
        vm.preview_error_msg = "Frame capture failed"
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._update_preview_info()
        assert panel.preview_info_label.text() == "ERROR · Frame capture failed"

    def test_render_without_preview_is_noop(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel([_camera("cam-0", "Front")], set())
        vm.latest = _frame("cam-0", 1)
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._render_preview_frame()
        assert panel.preview_label.pixmap().isNull()
        assert vm.rendered == []

    def test_live_marker_in_list_item(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel(
            [_camera("cam-0", "Front")], set(), preview_id="cam-0"
        )
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        assert "LIVE" in panel.camera_list.item(0).text()

    def test_preview_error_shown_in_status(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel([_camera("cam-0", "Front")], set())
        vm.preview_error_msg = "Camera not found"
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        assert "Camera not found" in panel.status_label.text()

    def test_clear_resets_preview_display(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel(
            [_camera("cam-0", "Front")], set(), preview_id="cam-0"
        )
        vm.latest = _frame("cam-0", 5)
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._render_preview_frame()
        panel._preview_timer.start()
        panel.clear()
        assert not panel._preview_timer.isActive()
        assert panel.preview_label.text() == "No preview"
        assert panel.preview_label.pixmap().isNull()
        assert panel.camera_list.count() == 0
        assert panel.status_label.text() == "No cameras"

    def test_shutdown_stops_preview(self, qapp: QApplication) -> None:
        vm = _FakeDevicesViewModel(
            [_camera("cam-0", "Front")], set(), preview_id="cam-0"
        )
        panel = CameraPanel()
        panel.bind_viewmodel(vm)
        panel._preview_timer.start()
        panel.shutdown()
        assert not panel._preview_timer.isActive()
        assert vm.stop_calls == 1
