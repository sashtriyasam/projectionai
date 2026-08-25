"""Regression tests for Actions teardown/shutdown.

``Actions`` stores an unsubscribe closure from ``CommandManager.subscribe``
in ``__init__`` but previously never invoked it, so the command manager
retained a bound ``Actions`` method for the app's lifetime. ``shutdown()``
must invoke that closure exactly once and clear the reference (idempotent),
and the owning window's close lifecycle must call it.
Rendering happens offscreen (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.core.events import EventBus
from projectionai.editor.events import EditorEventBus, SnapToggled
from projectionai.editor.types import TransformMode, TransformSpace
from projectionai.managers.command_manager import CommandManager
from projectionai.ui.actions.actions import Actions
from projectionai.ui.main_window import MainWindow
from projectionai.ui.viewmodels.output import OutputViewModel

# qapp provided by pytest-qt (function-scoped) - custom module fixture removed to avoid leak


class _EditorControllerStub:
    """Minimal controller carrying an editor event bus for Actions wiring."""

    def __init__(self, bus: EditorEventBus) -> None:
        self.editor_bus = bus
        self.transform_mode = TransformMode.NONE
        self.snap = SimpleNamespace(enabled=False)
        self.coordinates = SimpleNamespace(space=TransformSpace.WORLD)
        self.overlays = SimpleNamespace(
            grid=SimpleNamespace(enabled=True),
            show_statistics=False,
            show_bounding_boxes=True,
            show_selection_outlines=True,
        )


def _unrelated_listener() -> None:
    """Unrelated command subscriber that must survive teardown."""


class _BareMainWindow(MainWindow):
    """MainWindow with UI construction stubbed — exercises closeEvent only."""

    def _setup_ui(self) -> None:
        self._poll_timer = QTimer(self)

    def _connect_workspace_events(self) -> None:
        pass

    def _seed_workspaces(self) -> None:
        pass

    def _apply_layout(self) -> None:
        pass


class TestShutdown:
    def test_shutdown_releases_command_subscription(self, qapp: QApplication) -> None:
        commands = CommandManager(EventBus())
        actions = Actions(None, commands=commands)
        assert commands._stack_change_handlers, (
            "Actions should hold one stack-change subscription"
        )

        actions.shutdown()

        assert commands._stack_change_handlers == []

    def test_shutdown_releases_output_vm_and_event_bus_subscriptions(
        self, qapp: QApplication
    ) -> None:
        output_vm = OutputViewModel()
        bus = EditorEventBus()
        actions = Actions(
            None, output_vm=output_vm, controller=_EditorControllerStub(bus)
        )
        assert len(output_vm._handlers) == 1, "Actions should hold one VM subscription"

        actions.shutdown()

        assert output_vm._handlers == []
        for listeners in bus._listeners.values():
            assert listeners == []

    def test_shutdown_is_idempotent(self, qapp: QApplication) -> None:
        commands = CommandManager(EventBus())
        output_vm = OutputViewModel()
        bus = EditorEventBus()
        actions = Actions(
            None,
            commands=commands,
            output_vm=output_vm,
            controller=_EditorControllerStub(bus),
        )

        actions.shutdown()
        actions.shutdown()  # second call must be a no-op

        assert commands._stack_change_handlers == []
        assert output_vm._handlers == []
        for listeners in bus._listeners.values():
            assert listeners == []

    def test_emitting_sources_after_shutdown_does_not_execute_callbacks(
        self, qapp: QApplication
    ) -> None:
        output_vm = OutputViewModel()
        bus = EditorEventBus()
        actions = Actions(
            None, output_vm=output_vm, controller=_EditorControllerStub(bus)
        )

        # Positive control: subscriptions are live before shutdown.
        bus.emit(SnapToggled(enabled=True))
        assert actions._actions["view.toggle_snap"].isChecked()
        bus.emit(SnapToggled(enabled=False))
        assert not actions._actions["view.toggle_snap"].isChecked()
        assert not actions._actions["tools.live.send"].isEnabled()  # IDLE baseline
        output_vm.arm()  # IDLE -> ARMED emits to the viewmodel
        assert actions._actions["tools.live.send"].isEnabled()

        actions.shutdown()
        actions.shutdown()  # teardown must stay idempotent with new callbacks

        # Emits after shutdown must not reach any callback.
        bus.emit(SnapToggled(enabled=True))
        assert not actions._actions["view.toggle_snap"].isChecked()
        output_vm.disarm()  # ARMED -> IDLE emit would re-disable Send-to-Live
        assert actions._actions["tools.live.send"].isEnabled()

    def test_window_close_lifecycle_shuts_down_actions_exactly_once(
        self, qapp: QApplication
    ) -> None:
        commands = CommandManager(EventBus())
        commands.subscribe(_unrelated_listener)  # must survive teardown
        actions = Actions(None, commands=commands)
        window = _BareMainWindow(SimpleNamespace(event_bus=EventBus(), workspace=None))
        window._actions = actions

        calls: list[int] = []
        unsubscribe = actions._unsubscribe_commands
        assert unsubscribe is not None, "Actions must hold the command closure"

        def _tracked() -> None:
            calls.append(1)
            unsubscribe()

        actions._unsubscribe_commands = _tracked

        window.closeEvent(QCloseEvent())
        window.closeEvent(QCloseEvent())  # second close request

        assert calls == [1], "unsubscribe closure must run exactly once"
        assert commands._stack_change_handlers == [_unrelated_listener], (
            "only the Actions subscription may be removed"
        )
