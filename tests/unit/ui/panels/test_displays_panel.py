"""Functional tests for DisplaysPanel projector-output controls.

A duck-typed fake view model records the calls each button makes; the
panel is rendered offscreen (``QT_QPA_PLATFORM=offscreen``). Because
``run_async`` falls back to ``asyncio.run`` outside a running loop,
button clicks drive the view-model coroutines synchronously.
"""

from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolButton

from projectionai.core.errors import ProjectionAIError
from projectionai.hardware.display_validator import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from projectionai.hardware.errors import OutputSwitchError
from projectionai.hardware.models import (
    DisplayConnection,
    DisplayInfo,
    DisplayKind,
)
from projectionai.hardware.output_manager import OutputState
from projectionai.hardware.patterns import PatternKind
from projectionai.ui.panels.displays_panel import DisplaysPanel

# qapp provided by pytest-qt (function-scoped) - custom module fixture removed to avoid leak


class _FakeViewModel:
    """Duck-typed stand-in for DisplaysViewModel."""

    def __init__(
        self,
        displays: tuple[DisplayInfo, ...],
        *,
        fail_live: bool = False,
        fail_refresh: bool = False,
    ) -> None:
        self._displays = displays
        self.message: str | None = None
        self.output_state = OutputState.IDLE
        self.session: Any = None
        self.preview_display_id: str | None = None
        self.calls: list[tuple[str, Any]] = []
        self._fail_live = fail_live
        self._fail_refresh = fail_refresh
        self._handlers: list[Any] = []

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
        self._handlers.append(handler)

    def set_message(self, text: str | None) -> None:
        self.message = text
        for handler in self._handlers:
            handler()

    def clear_message(self) -> None:
        self.set_message(None)

    async def select_live(self, display_id: str) -> Any:
        self.calls.append(("select_live", display_id))
        if self._fail_live:
            raise OutputSwitchError(
                "Switch rejected by validation",
                ValidationReport(
                    issues=(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="no_renderer",
                            message="Renderer not ready",
                        ),
                    )
                ),
            )

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
        if self._fail_refresh:
            raise ProjectionAIError("Scan failed")
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


def _display_info(*, manufacturer: str = "", model: str = "") -> DisplayInfo:
    return DisplayInfo(
        display_id="p1",
        index=0,
        name="Screen",
        kind=DisplayKind.PROJECTOR,
        manufacturer=manufacturer,
        model=model,
    )


class TestDisplayLabel:
    def test_device_joins_manufacturer_and_model(self) -> None:
        label = DisplaysPanel._display_label(
            _display_info(manufacturer="Epson", model="EB-2250U"), None, None
        )

        assert label.startswith("Screen · Epson/EB-2250U · ")

    def test_device_uses_model_when_manufacturer_unset(self) -> None:
        label = DisplaysPanel._display_label(
            _display_info(model="EB-2250U"), None, None
        )

        assert label.startswith("Screen · EB-2250U · ")
        assert "Epson" not in label

    def test_device_omitted_when_both_unset(self) -> None:
        label = DisplaysPanel._display_label(_display_info(), None, None)

        assert label.startswith("Screen · ")
        assert not label.startswith("Screen · /")

    def test_projector_item_uses_connection_label(self, qapp: QApplication) -> None:
        display = DisplayInfo(
            display_id="p1",
            index=0,
            name="P1",
            kind=DisplayKind.PROJECTOR,
            connection=DisplayConnection.HDMI,
        )

        item = DisplaysPanel._projector_item(display, None, None)

        assert "HDMI" in item.text()
        assert "hdmi" not in item.text()


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

    def test_freeze_click_does_not_stick_checked_state(
        self, qapp: QApplication
    ) -> None:
        """The checked state follows the VM, not the click.

        The button is checkable, so Qt toggles it on click; the panel
        must revert it to the view-model state immediately (the toggle
        is async and the fake never reaches FREEZE).
        """
        vm = _FakeViewModel(_displays("p1"))
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)
        assert not panel.freeze_button.isChecked()

        _button(panel, "Freeze").click()

        assert vm.calls == [("toggle_freeze", None)]
        assert not panel.freeze_button.isChecked()

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

    def test_switch_rejection_renders_validation_report(
        self, qapp: QApplication
    ) -> None:
        vm = _FakeViewModel(_displays("p1"), fail_live=True)
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)
        panel.display_list.setCurrentRow(0)

        _button(panel, "Select as Live").click()

        assert vm.message is not None
        assert "Switch rejected" in vm.message
        # The rejection report survives the refresh triggered by the
        # view-model notification (no stale vm.validate() overwrite).
        assert "Renderer not ready" in panel.validation_label.text()

    def test_rejected_switch_report_clears_after_successful_action(
        self, qapp: QApplication
    ) -> None:
        vm = _FakeViewModel(_displays("p1"), fail_live=True)
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)
        panel.display_list.setCurrentRow(0)

        _button(panel, "Select as Live").click()
        assert "Renderer not ready" in panel.validation_label.text()

        _button(panel, "Blackout").click()

        assert "Renderer not ready" not in panel.validation_label.text()

    def test_refresh_failure_surfaces_as_message(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("p1"), fail_refresh=True)
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        _button(panel, "Refresh").click()

        assert vm.message is not None
        assert "Scan failed" in vm.message

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
