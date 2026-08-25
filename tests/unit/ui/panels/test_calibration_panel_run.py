"""Tests for the CalibrationSessionsPanel run row.

The "Run Camera Calibration" button must disable while a run is in
flight, reflect ``last_run_status``, and start a run on the first open
camera — or surface an informational message when no camera is open.
The view model is faked; ``run_async`` runs the coroutine synchronously
when no event loop is running, so the scheduled call is observable.
Rendering happens offscreen (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.ui.panels.calibration_panel import CalibrationSessionsPanel

# qapp provided by pytest-qt (function-scoped) - custom module fixture removed to avoid leak


class _FakeViewModel:
    """Duck-typed stand-in for CalibrationViewModel."""

    def __init__(
        self,
        *,
        camera_ids: tuple[str, ...] = (),
        running: bool = False,
        status: str | None = None,
    ) -> None:
        self._camera_ids = camera_ids
        self._running = running
        self._status = status
        self.run_camera_ids: list[str] = []

    # -- Panel surface ------------------------------------------------------

    def methods(self) -> list[Any]:
        return []

    def sessions(self) -> list[Any]:
        return []

    def active_session(self) -> Any:
        return None

    def subscribe(self, handler: Any) -> None:
        """No-op: tests drive refresh() directly."""

    def unsubscribe(self, handler: Any) -> None:
        """No-op."""

    # -- Run row ------------------------------------------------------------

    def is_calibration_running(self) -> bool:
        return self._running

    def last_run_status(self) -> str | None:
        return self._status

    def open_camera_ids(self) -> tuple[str, ...]:
        return self._camera_ids

    async def run_camera_calibration(self, camera_id: str, **_: Any) -> Any:
        self.run_camera_ids.append(camera_id)
        return None


class TestRunRowState:
    def test_running_disables_button(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(running=True)
        panel = CalibrationSessionsPanel()
        panel.bind_viewmodel(vm)
        assert panel.run_button.isEnabled() is False

    def test_idle_enables_button(self, qapp: QApplication) -> None:
        vm = _FakeViewModel()
        panel = CalibrationSessionsPanel()
        panel.bind_viewmodel(vm)
        assert panel.run_button.isEnabled() is True

    def test_status_label_shown(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(status="Calibration complete")
        panel = CalibrationSessionsPanel()
        panel.bind_viewmodel(vm)
        assert panel.status_label.text() == "Calibration complete"

    def test_no_viewmodel_disables_button(self, qapp: QApplication) -> None:
        panel = CalibrationSessionsPanel()
        panel.refresh()
        assert panel.run_button.isEnabled() is False


class TestRunAction:
    def test_run_on_first_open_camera(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(camera_ids=("cam-1", "cam-2"))
        panel = CalibrationSessionsPanel()
        panel.bind_viewmodel(vm)
        panel._run_camera_calibration()
        assert vm.run_camera_ids == ["cam-1"]

    def test_no_cameras_shows_info_message(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vm = _FakeViewModel(camera_ids=())
        panel = CalibrationSessionsPanel()
        panel.bind_viewmodel(vm)

        messages: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "information",
            staticmethod(lambda _parent, _title, text: messages.append(text)),
        )
        panel._run_camera_calibration()

        assert vm.run_camera_ids == []
        assert messages == ["Open a camera first (Camera panel)."]

    def test_no_viewmodel_is_noop(self, qapp: QApplication) -> None:
        panel = CalibrationSessionsPanel()
        panel._run_camera_calibration()
