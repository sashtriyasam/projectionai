"""Functional tests for DisplaysPanel projector-output controls.

A duck-typed fake view model records the calls each button makes; the
panel is rendered offscreen (``QT_QPA_PLATFORM=offscreen``). Because
``run_async`` falls back to ``asyncio.run`` outside a running loop,
button clicks drive the view-model coroutines synchronously.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QToolButton

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.hardware.errors import OutputSessionError
from projectionai.hardware.models import DisplayInfo, DisplayKind
from projectionai.hardware.output_manager import OutputState
from projectionai.hardware.patterns import PatternKind
from projectionai.ui.panels.displays_panel import DisplaysPanel


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Return the process-wide QApplication (created once)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeViewModel:
    """Duck-typed stand-in for DisplaysViewModel."""

    def __init__(
        self,
        displays: tuple[DisplayInfo, ...],
        *,
        fail_live: bool = False,
    ) -> None:
        self._displays = displays
        self.message: str | None = None
        self.output_state = OutputState.IDLE
        self.preview_display_id: str | None = None
        self.calls: list[tuple[str, Any]] = []
        self._fail_live = fail_live

    def displays(self) -> tuple[DisplayInfo, ...]:
        return self._displays

    def projectors(self) -> tuple[DisplayInfo, ...]:
        return ()

    @property
    def live_display_id(self) -> str | None:
        return None

    def validate(self) -> Any:
        return type(
            "_Report",
            (),
            {"is_ok": True, "errors": [], "warnings": [], "recommendations": []},
        )()

    def subscribe(self, handler: Any) -> None:
        """No-op: tests drive refresh directly."""

    def set_message(self, text: str | None) -> None:
        self.message = text

    def clear_message(self) -> None:
        self.message = None

    async def select_live(self, display_id: str) -> Any:
        self.calls.append(("select_live", display_id))
        if self._fail_live:
            raise OutputSessionError("Switch rejected by validation")

    async def select_preview(self, display_id: str) -> None:
        self.calls.append(("select_preview", display_id))

    async def test_pattern(self, display_id: str, pattern: PatternKind) -> None:
        self.calls.append(("test_pattern", (display_id, pattern)))

    async def enter_fullscreen(self, display_id: str) -> None:
        self.calls.append(("enter_fullscreen", display_id))

    async def blackout(self) -> None:
        self.calls.append(("blackout", None))

    async def toggle_freeze(self) -> None:
        self.calls.append(("toggle_freeze", None))

    async def exit_output(self) -> None:
        self.calls.append(("exit_output", None))

    async def refresh_displays(self) -> int:
        self.calls.append(("refresh_displays", None))
        return len(self._displays)

    async def identify(self, display_id: str) -> None:
        self.calls.append(("identify", display_id))


def _displays(*ids: str) -> tuple[DisplayInfo, ...]:
    return tuple(
        DisplayInfo(
            display_id=display_id,
            index=i,
            name=f"Display {display_id}",
            kind=DisplayKind.PROJECTOR,
        )
        for i, display_id in enumerate(ids)
    )


def _button(panel: DisplaysPanel, text: str) -> QToolButton:
    for button in panel.findChildren(QToolButton):
        if button.text() == text:
            return button
    raise AssertionError(f"No button labelled {text!r} in panel")


class TestActionButtons:
    def test_select_live_button_routes_selected_display(
        self, qapp: QApplication
    ) -> None:
        vm = _FakeViewModel(_displays("p1", "p2"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)
        panel.display_list.setCurrentRow(1)

        _button(panel, "Select as Live").click()

        assert vm.calls == [("select_live", "p2")]

    def test_select_preview_button_routes_selected_display(
        self, qapp: QApplication
    ) -> None:
        vm = _FakeViewModel(_displays("p1"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)
        panel.display_list.setCurrentRow(0)

        _button(panel, "Select as Preview").click()

        assert vm.calls == [("select_preview", "p1")]

    def test_test_pattern_button_uses_pattern_combo(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)
        panel.display_list.setCurrentRow(0)

        kind = panel.pattern_combo.currentData()
        assert kind is not None and kind is not PatternKind.BLACK

        _button(panel, "Test Pattern").click()

        assert vm.calls == [("test_pattern", ("p1", kind))]

    def test_fullscreen_button_routes_selected_display(
        self, qapp: QApplication
    ) -> None:
        vm = _FakeViewModel(_displays("p1"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)
        panel.display_list.setCurrentRow(0)

        _button(panel, "Fullscreen").click()

        assert vm.calls == [("enter_fullscreen", "p1")]

    def test_blackout_button(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        _button(panel, "Blackout").click()

        assert vm.calls == [("blackout", None)]

    def test_freeze_button_toggles(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        _button(panel, "Freeze").click()

        assert vm.calls == [("toggle_freeze", None)]

    def test_exit_output_button(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        _button(panel, "Exit Output").click()

        assert vm.calls == [("exit_output", None)]

    def test_refresh_button(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        _button(panel, "Refresh").click()

        assert vm.calls == [("refresh_displays", None)]

    def test_identify_button_routes_selected_display(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)
        panel.display_list.setCurrentRow(0)

        _button(panel, "Identify").click()

        assert vm.calls == [("identify", "p1")]


class TestActionFeedback:
    def test_action_failure_surfaces_as_message(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"), fail_live=True)
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)
        panel.display_list.setCurrentRow(0)

        _button(panel, "Select as Live").click()

        assert vm.message is not None
        assert "Switch rejected" in vm.message

    def test_successful_action_clears_message(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"))
        vm.set_message("stale error")
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        _button(panel, "Blackout").click()

        assert vm.message is None


class TestSessionStateRendering:
    def test_freeze_button_syncs_with_output_state(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)
        assert not panel.freeze_button.isChecked()

        vm.output_state = OutputState.FREEZE
        panel.refresh()

        assert vm.calls == []
        assert panel.freeze_button.isChecked()

    def test_message_label_shows_vm_message(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"))
        vm.set_message("Display disconnected")
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        assert panel.message_label.text() == "Display disconnected"

    def test_session_label_shows_state(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        assert "IDLE" in panel.session_label.text()
