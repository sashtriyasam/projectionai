"""Central action registry — menus, toolbar, and command wiring.

Every ``QAction`` in the application is created and owned by
:class:`Actions`. Menus and the toolbar are assembled from the same
registry, so the command palette, shortcuts reference, and future
toolbars all share one source of truth.

Features deliberately out of scope for the shell build (projection
mapping, AI generation, calibration algorithms, video decoding, export)
still appear in the menus as *present but inert* actions: they respond
with a status-bar hint instead of silently disappearing. No fake
implementations are provided.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QLabel,
    QMenu,
    QMenuBar,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from projectionai.editor.events import (
    EditorEvent,
    EditorEventBus,
    SnapToggled,
    SpaceChanged,
    TransformModeChanged,
)
from projectionai.editor.types import TransformMode, TransformSpace
from projectionai.managers.command_manager import CommandManager
from projectionai.managers.project_manager import ProjectManager
from projectionai.managers.scene_manager import SceneManager
from projectionai.managers.workspace_manager import WorkspaceManager
from projectionai.ui.actions.command_palette import CommandPaletteDialog
from projectionai.ui.state_machine import OutputState
from projectionai.ui.viewmodels.output import OutputViewModel
from projectionai.ui.views.status_bar import StatusBar
from projectionai.ui.widgets.panel_base import run_async

Slot = Callable[..., object]

_TOOL_MODES: tuple[tuple[str, str, str, TransformMode], ...] = (
    ("tool.select", "Select", "V", TransformMode.NONE),
    ("tool.move", "Move", "G", TransformMode.TRANSLATE),
    ("tool.rotate", "Rotate", "R", TransformMode.ROTATE),
    ("tool.scale", "Scale", "S", TransformMode.SCALE),
)

_EXPORTS: tuple[tuple[str, str], ...] = (
    ("file.export.video", "Video..."),
    ("file.export.image_sequence", "Image Sequence..."),
    ("file.export.single_frame", "Single Frame..."),
    ("file.export.calibration_pack", "Calibration Pack..."),
)


class Actions(QObject):
    """Owns every QAction in the editor; assembles menus and the toolbar."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        workspace: WorkspaceManager | None = None,
        commands: CommandManager | None = None,
        projects: ProjectManager | None = None,
        scenes: SceneManager | None = None,
        output_vm: OutputViewModel | None = None,
        controller: Any | None = None,
        status_bar: StatusBar | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = parent
        self._workspace = workspace
        self._commands = commands
        self._projects = projects
        self._scenes = scenes
        self._output_vm = output_vm
        self._controller = controller
        self._status_bar = status_bar
        self._on_quit = on_quit
        self._actions: dict[str, QAction] = {}
        self._scene_combo: QComboBox | None = None
        self._workspace_menus: list[QMenu] = []
        self._panels_menus: list[QMenu] = []

        self._unsubscribe_commands: Callable[[], None] | None = None
        self._unsubscribe_output_vm: Callable[[], None] | None = None
        self._unsubscribe_events: Callable[[], None] | None = None
        if commands is not None:
            self._unsubscribe_commands = commands.subscribe(self._sync_history_state)

        self._build_actions()
        self._sync_history_state()
        self._sync_tool_state()
        self._sync_view_toggles()
        self._sync_output_state()

        if output_vm is not None:
            output_vm.subscribe(self._on_output_changed)

            def _unsubscribe_output_vm() -> None:
                output_vm.unsubscribe(self._on_output_changed)

            self._unsubscribe_output_vm = _unsubscribe_output_vm
        if controller is not None:
            bus = getattr(controller, "editor_bus", None)
            if isinstance(bus, EditorEventBus):
                bus.subscribe(TransformModeChanged, self._on_transform_mode_changed)
                bus.subscribe(SnapToggled, self._on_snap_toggled)
                bus.subscribe(SpaceChanged, self._on_space_changed)

                def _unsubscribe_events() -> None:
                    bus.unsubscribe(
                        TransformModeChanged, self._on_transform_mode_changed
                    )
                    bus.unsubscribe(SnapToggled, self._on_snap_toggled)
                    bus.unsubscribe(SpaceChanged, self._on_space_changed)

                self._unsubscribe_events = _unsubscribe_events

        for action in self._actions.values():
            action.hovered.connect(lambda a=action: self._hint(_clean_text(a)))

    # -- Public API ---------------------------------------------------------

    def action(self, action_id: str) -> QAction | None:
        """Look up a registered action by id."""
        return self._actions.get(action_id)

    def shutdown(self) -> None:
        """Unsubscribe from the command manager, output viewmodel, and
        editor event bus; safe to call multiple times.

        Invokes each stored cleanup callback exactly once and clears the
        reference so the managers, the viewmodel, and the event bus no
        longer retain this object after the owning window has closed.
        """
        if self._unsubscribe_commands is not None:
            self._unsubscribe_commands()
            self._unsubscribe_commands = None
        if self._unsubscribe_output_vm is not None:
            self._unsubscribe_output_vm()
            self._unsubscribe_output_vm = None
        if self._unsubscribe_events is not None:
            self._unsubscribe_events()
            self._unsubscribe_events = None

    def actions(self) -> list[QAction]:
        """All registered actions, in creation order."""
        return list(self._actions.values())

    def build_menu_bar(self) -> QMenuBar:
        """Assemble the top-level menu bar from the registered menus."""
        menubar = QMenuBar(self._window)
        for menu in (
            self._file_menu,
            self._edit_menu,
            self._view_menu,
            self._scene_menu,
            self._tools_menu,
            self._window_menu,
            self._help_menu,
        ):
            menubar.addMenu(menu)
        return menubar

    def build_toolbar(self) -> QToolBar:
        """Assemble the main toolbar from registered actions."""
        toolbar = QToolBar("Main Toolbar", self._window)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        for action_id in (
            "tool.select",
            "tool.move",
            "tool.rotate",
            "tool.scale",
            "tool.warp",
        ):
            toolbar.addAction(self._actions[action_id])
        toolbar.addSeparator()
        toolbar.addAction(self._actions["edit.undo"])
        toolbar.addAction(self._actions["edit.redo"])
        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" Scene: "))
        toolbar.addWidget(self.build_scene_combo())
        toolbar.addSeparator()
        toolbar.addAction(self._actions["tools.live.arm"])
        toolbar.addAction(self._actions["tools.live.blackout"])
        toolbar.addAction(self._actions["tools.live.send"])
        toolbar.addSeparator()
        toolbar.addAction(self._actions["tools.generate_ai"])
        toolbar.addAction(self._actions["tools.scan_object"])
        toolbar.addAction(self._actions["tools.calibrate_wizard"])
        toolbar.addSeparator()
        toolbar.addAction(self._actions["view.toggle_snap"])
        toolbar.addAction(self._actions["view.toggle_grid"])
        toolbar.addAction(self._actions["view.toggle_local_space"])

        arm_button = toolbar.widgetForAction(self._actions["tools.live.arm"])
        if arm_button is not None:
            arm_button.setObjectName("armLiveButton")
            arm_button.setMinimumHeight(30)
        return toolbar

    def build_scene_combo(self) -> QComboBox:
        """Scene switcher used by the toolbar."""
        combo = QComboBox()
        combo.setObjectName("sceneCombo")
        combo.setMinimumWidth(160)
        combo.activated.connect(self._scene_combo_activated)
        self._scene_combo = combo
        self._refresh_scene_combo()
        return combo

    # -- Action factory -----------------------------------------------------

    def _make(
        self,
        action_id: str,
        text: str,
        *,
        shortcut: str = "",
        slot: Slot | None = None,
        checkable: bool = False,
        checked: bool = False,
        tooltip: str = "",
    ) -> QAction:
        action = QAction(text, self._window)
        action.setObjectName(action_id)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if checkable:
            action.setCheckable(True)
            action.setChecked(checked)
        if tooltip:
            action.setToolTip(tooltip)
        if slot is not None:
            action.triggered.connect(slot)
        self._actions[action_id] = action
        return action

    def _inert(self, feature: str) -> Slot:
        """Slot factory for present-but-inert (out-of-scope) actions."""

        def _slot(_checked: bool = False) -> None:
            self._hint_not_implemented(feature)

        return _slot

    # -- Menu construction --------------------------------------------------

    def _build_actions(self) -> None:
        self._build_tools()
        self._build_file_menu()
        self._build_edit_menu()
        self._build_view_menu()
        self._build_scene_menu()
        self._build_tools_menu()
        self._build_window_menu()
        self._build_help_menu()

    def _build_tools(self) -> None:
        group = QActionGroup(self)
        group.setExclusive(True)
        for action_id, label, key, mode in _TOOL_MODES:
            action = self._make(
                action_id,
                f"{label}\t{key}",
                shortcut=key,
                checkable=True,
                tooltip=f"{label} tool ({key})",
                slot=lambda _=False, m=mode: self._set_tool_mode(m),
            )
            group.addAction(action)
        warp = self._make(
            "tool.warp",
            "Warp\tW",
            shortcut="W",
            checkable=True,
            tooltip="Warp tool (W)",
            slot=self._warp_triggered,
        )
        group.addAction(warp)

    def _build_file_menu(self) -> None:
        menu = QMenu("&File", self._window)
        self._file_menu = menu
        self._make(
            "file.new_project",
            "&New Project...",
            shortcut="Ctrl+N",
            slot=self._new_project,
        )
        self._make(
            "file.open_project",
            "&Open Project...",
            shortcut="Ctrl+O",
            slot=self._open_project,
        )
        menu.addAction(self._actions["file.new_project"])
        menu.addAction(self._actions["file.open_project"])
        recent = QMenu("&Recent Projects", menu)
        menu.addMenu(recent)
        self._recent_menu = recent
        recent.aboutToShow.connect(self._populate_recent_menu)
        menu.addSeparator()
        self._make("file.save", "&Save", shortcut="Ctrl+S", slot=self._save_project)
        menu.addAction(self._actions["file.save"])
        self._make(
            "file.save_as",
            "Save &As...",
            shortcut="Ctrl+Shift+S",
            slot=self._save_project_as,
        )
        menu.addAction(self._actions["file.save_as"])
        menu.addSeparator()
        self._make(
            "file.import_assets",
            "&Import Assets...",
            shortcut="Ctrl+I",
            slot=self._inert("Import Assets"),
        )
        menu.addAction(self._actions["file.import_assets"])
        export = QMenu("&Export", menu)
        for action_id, label in _EXPORTS:
            self._make(action_id, label, slot=self._inert("Export"))
            export.addAction(self._actions[action_id])
        menu.addMenu(export)
        self._make(
            "file.collect_pack",
            "&Collect & Pack...",
            slot=self._inert("Collect and Pack"),
        )
        menu.addAction(self._actions["file.collect_pack"])
        menu.addSeparator()
        self._make(
            "file.project_settings",
            "Project &Settings...",
            slot=self._inert("Project Settings"),
        )
        menu.addAction(self._actions["file.project_settings"])
        menu.addSeparator()
        self._make("file.quit", "&Quit", shortcut="Ctrl+Q", slot=self._quit)
        menu.addAction(self._actions["file.quit"])
        self._populate_recent_menu()

    def _build_edit_menu(self) -> None:
        menu = QMenu("&Edit", self._window)
        self._edit_menu = menu
        self._make("edit.undo", "&Undo", shortcut="Ctrl+Z", slot=self._undo)
        self._make("edit.redo", "&Redo", shortcut="Ctrl+Shift+Z", slot=self._redo)
        menu.addAction(self._actions["edit.undo"])
        menu.addAction(self._actions["edit.redo"])
        menu.addSeparator()
        self._make(
            "edit.cut", "Cu&t", shortcut="Ctrl+X", slot=self._clipboard_edit("cut")
        )
        self._make(
            "edit.copy", "&Copy", shortcut="Ctrl+C", slot=self._clipboard_edit("copy")
        )
        self._make(
            "edit.paste",
            "&Paste",
            shortcut="Ctrl+V",
            slot=self._clipboard_edit("paste"),
        )
        menu.addAction(self._actions["edit.cut"])
        menu.addAction(self._actions["edit.copy"])
        menu.addAction(self._actions["edit.paste"])
        menu.addSeparator()
        self._make(
            "edit.duplicate", "D&uplicate", shortcut="Ctrl+D", slot=self._duplicate
        )
        self._make("edit.delete", "&Delete", shortcut="Del", slot=self._delete)
        menu.addAction(self._actions["edit.duplicate"])
        menu.addAction(self._actions["edit.delete"])
        menu.addSeparator()
        self._make(
            "edit.select_all", "Select &All", shortcut="Ctrl+A", slot=self._select_all
        )
        self._make("edit.deselect", "&Deselect", shortcut="Esc", slot=self._deselect)
        menu.addAction(self._actions["edit.select_all"])
        menu.addAction(self._actions["edit.deselect"])
        menu.addSeparator()
        palette = self._make(
            "edit.command_palette",
            "&Command Palette...",
            shortcut="Ctrl+Shift+F",
            slot=self._open_command_palette,
        )
        palette.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        menu.addAction(palette)

    def _build_view_menu(self) -> None:
        menu = QMenu("&View", self._window)
        self._view_menu = menu
        menu.addMenu(self._workspaces_menu())
        menu.addMenu(self._panels_menu())
        menu.addSeparator()
        self._make(
            "view.toggle_grid", "Toggle &Grid", checkable=True, slot=self._toggle_grid
        )
        self._make(
            "view.toggle_gizmos",
            "Toggle &Gizmos",
            checkable=True,
            slot=self._toggle_gizmos,
        )
        self._make(
            "view.toggle_statistics",
            "Toggle &Overlays",
            checkable=True,
            slot=self._toggle_statistics,
        )
        self._make(
            "view.toggle_bounding_boxes",
            "Toggle &Bounding Boxes",
            checkable=True,
            slot=self._toggle_bounding_boxes,
        )
        self._make(
            "view.toggle_selection_outlines",
            "Toggle &Selection Outlines",
            checkable=True,
            slot=self._toggle_selection_outlines,
        )
        for action_id in (
            "view.toggle_grid",
            "view.toggle_gizmos",
            "view.toggle_statistics",
            "view.toggle_bounding_boxes",
            "view.toggle_selection_outlines",
        ):
            menu.addAction(self._actions[action_id])
        menu.addSeparator()
        self._make(
            "view.toggle_snap", "Toggle &Snap", checkable=True, slot=self._toggle_snap
        )
        self._make(
            "view.toggle_local_space",
            "Toggle &Local Space",
            checkable=True,
            slot=self._toggle_local_space,
        )
        menu.addAction(self._actions["view.toggle_snap"])
        menu.addAction(self._actions["view.toggle_local_space"])
        menu.addSeparator()
        self._make(
            "view.lock_layout",
            "&Lock Layout",
            shortcut="Ctrl+Alt+L",
            checkable=True,
            slot=self._toggle_lock_layout,
        )
        self._make(
            "view.fullscreen",
            "&Fullscreen",
            shortcut="F11",
            checkable=True,
            slot=self._toggle_fullscreen,
        )
        self._make(
            "view.output_window",
            "&Output Window",
            slot=self._inert("The output window"),
        )
        menu.addAction(self._actions["view.lock_layout"])
        menu.addAction(self._actions["view.fullscreen"])
        menu.addAction(self._actions["view.output_window"])

    def _build_scene_menu(self) -> None:
        menu = QMenu("&Scene", self._window)
        self._scene_menu = menu
        self._make(
            "scene.new_scene",
            "&New Scene",
            shortcut="Ctrl+Shift+N",
            slot=self._new_scene,
        )
        self._make(
            "scene.duplicate_scene",
            "&Duplicate Scene",
            slot=self._inert("Scene duplication"),
        )
        self._make("scene.delete_scene", "&Delete Scene", slot=self._delete_scene)
        self._make(
            "scene.scene_properties",
            "Scene &Properties...",
            slot=self._inert("Scene Properties"),
        )
        for action_id in (
            "scene.new_scene",
            "scene.duplicate_scene",
            "scene.delete_scene",
            "scene.scene_properties",
        ):
            menu.addAction(self._actions[action_id])

    def _build_tools_menu(self) -> None:
        menu = QMenu("&Tools", self._window)
        self._tools_menu = menu
        self._make(
            "tools.calibrate_wizard",
            "&Calibrate Wizard...",
            slot=self._inert("The Calibrate Wizard"),
        )
        self._make(
            "tools.scan_object", "&Scan Object...", slot=self._inert("Object scanning")
        )
        self._make(
            "tools.generate_ai",
            "&Generate with AI...",
            shortcut="Ctrl+J",
            slot=self._inert("AI generation"),
        )
        self._make(
            "tools.warp_wizard", "&Warp Wizard...", slot=self._inert("The Warp Wizard")
        )
        for action_id in (
            "tools.calibrate_wizard",
            "tools.scan_object",
            "tools.generate_ai",
            "tools.warp_wizard",
        ):
            menu.addAction(self._actions[action_id])
        menu.addSeparator()
        live = QMenu("&Live", menu)
        self._make(
            "tools.live.arm",
            "&Arm Live\tF9",
            shortcut="F9",
            checkable=True,
            slot=self._arm_triggered,
        )
        self._make("tools.live.send", "&Send to Live\tEnter", slot=self._send_live)
        self._make(
            "tools.live.blackout",
            "&Blackout\tB",
            shortcut="B",
            slot=self._toggle_blackout,
        )
        for action_id in ("tools.live.arm", "tools.live.send", "tools.live.blackout"):
            live.addAction(self._actions[action_id])
        menu.addMenu(live)
        menu.addSeparator()
        self._make(
            "tools.control_mapping",
            "&Control Mapping...",
            slot=self._inert("Control Mapping"),
        )
        menu.addAction(self._actions["tools.control_mapping"])

    def _build_window_menu(self) -> None:
        menu = QMenu("&Window", self._window)
        self._window_menu = menu
        menu.addMenu(self._workspaces_menu())
        self._make(
            "window.reset_workspace", "&Reset Workspace", slot=self._reset_workspace
        )
        self._make(
            "window.save_layout_as",
            "&Save Layout As...",
            slot=self._inert("Saving layouts"),
        )
        menu.addAction(self._actions["window.reset_workspace"])
        menu.addAction(self._actions["window.save_layout_as"])
        menu.addSeparator()
        menu.addMenu(self._panels_menu())
        menu.addAction(self._actions["view.lock_layout"])

    def _build_help_menu(self) -> None:
        menu = QMenu("&Help", self._window)
        self._help_menu = menu
        self._make(
            "help.shortcuts",
            "&Shortcuts Reference",
            shortcut="F1",
            slot=self._show_shortcuts_reference,
        )
        self._make(
            "help.documentation", "&Documentation", slot=self._inert("Documentation")
        )
        self._make(
            "help.calibration_guides",
            "&Calibration Guides",
            slot=self._inert("Calibration guides"),
        )
        self._make(
            "help.check_updates",
            "Check for &Updates...",
            slot=self._inert("Checking for updates"),
        )
        self._make(
            "help.diagnostics", "&Diagnostics...", slot=self._inert("Diagnostics")
        )
        self._make("help.about", "&About ProjectionAI", slot=self._show_about)
        for action_id in (
            "help.shortcuts",
            "help.documentation",
            "help.calibration_guides",
            "help.check_updates",
            "help.diagnostics",
            "help.about",
        ):
            menu.addAction(self._actions[action_id])

    def _workspaces_menu(self) -> QMenu:
        menu = QMenu("&Workspaces", self._window)
        self._refresh_workspaces_menu(menu)
        self._workspace_menus.append(menu)
        return menu

    def _panels_menu(self) -> QMenu:
        menu = QMenu("&Panels", self._window)
        self._refresh_panels_menu(menu)
        self._panels_menus.append(menu)
        return menu

    # -- File handlers ------------------------------------------------------

    def _new_project(self) -> None:
        if self._projects is None:
            self._hint_not_implemented("Project creation")
            return
        path, _ = QFileDialog.getSaveFileName(
            self._window, "New Project", "", "ProjectionAI Project (*.proj)"
        )
        if not path:
            return
        self._projects.create_project(name=Path(path).stem, path=Path(path))
        self._hint(f"Created project {Path(path).name}")

    def _open_project(self) -> None:
        if self._projects is None:
            self._hint_not_implemented("Project opening")
            return
        path, _ = QFileDialog.getOpenFileName(
            self._window, "Open Project", "", "ProjectionAI Project (*.proj)"
        )
        if path:
            run_async(self._projects.open_project(Path(path)))

    def _save_project(self) -> None:
        if self._projects is None:
            self._hint_not_implemented("Project saving")
            return
        if not self._projects.is_open:
            self._hint("No project open to save")
            return
        run_async(self._projects.save_project())

    def _save_project_as(self) -> None:
        if self._projects is None:
            self._hint_not_implemented("Project saving")
            return
        path, _ = QFileDialog.getSaveFileName(
            self._window, "Save Project As", "", "ProjectionAI Project (*.proj)"
        )
        if path:
            run_async(self._projects.save_project(Path(path)))

    def _populate_recent_menu(self) -> None:
        menu = self._recent_menu
        menu.clear()
        if self._projects is None:
            menu.addAction("No recent projects").setEnabled(False)
            return
        recent = self._projects.recent_projects
        if not recent:
            menu.addAction("No recent projects").setEnabled(False)
            return
        for entry in recent:
            path = getattr(entry, "path", None)
            if path is None:
                continue
            label = getattr(entry, "name", None) or Path(path).name
            action = menu.addAction(label)
            action.triggered.connect(lambda _=False, p=path: self._open_recent(p))

    def _open_recent(self, path: Any) -> None:
        if self._projects is not None:
            run_async(self._projects.open_project(Path(path)))

    def _quit(self) -> None:
        if self._on_quit is not None:
            self._on_quit()
        elif self._window is not None:
            self._window.close()

    # -- Edit handlers ------------------------------------------------------

    def _undo(self) -> None:
        if self._commands is not None and self._commands.can_undo:
            run_async(self._commands.undo())
        else:
            self._hint("Nothing to undo")

    def _redo(self) -> None:
        if self._commands is not None and self._commands.can_redo:
            run_async(self._commands.redo())
        else:
            self._hint("Nothing to redo")

    def _clipboard_edit(self, mode: str) -> Slot:
        def _slot(_checked: bool = False) -> None:
            widget = QApplication.focusWidget()
            method = getattr(widget, mode, None) if widget is not None else None
            if callable(method):
                method()
            else:
                self._hint(f"Nothing to {mode}")

        return _slot

    def _duplicate(self) -> None:
        if self._controller is not None:
            self._controller.handle_key("duplicate", [])
        else:
            self._hint("Nothing to duplicate")

    def _delete(self) -> None:
        if self._controller is not None:
            self._controller.handle_key("delete", [])
        else:
            self._hint("Nothing to delete")

    def _select_all(self) -> None:
        widget = QApplication.focusWidget()
        if widget is not None and hasattr(widget, "selectAll"):
            widget.selectAll()
        elif self._controller is not None:
            self._controller.handle_key("select_all", [])

    def _deselect(self) -> None:
        if self._controller is not None:
            self._controller.handle_key("deselect", [])
        else:
            self._hint("Nothing selected")

    def _open_command_palette(self) -> None:
        dialog = CommandPaletteDialog(list(self._actions.values()), self._window)
        dialog.exec()

    # -- View handlers ------------------------------------------------------

    def _toggle_grid(self, checked: bool) -> None:
        if self._controller is not None:
            self._controller.overlays.grid.enabled = checked
        else:
            self._hint_not_implemented("Viewport grid")

    def _toggle_gizmos(self, checked: bool) -> None:
        self._hint_not_implemented("Gizmo visibility toggling")
        self._actions["view.toggle_gizmos"].setChecked(False)

    def _toggle_statistics(self, checked: bool) -> None:
        if self._controller is not None:
            self._controller.overlays.show_statistics = checked
        else:
            self._hint_not_implemented("Viewport overlays")

    def _toggle_bounding_boxes(self, checked: bool) -> None:
        if self._controller is not None:
            self._controller.overlays.show_bounding_boxes = checked
        else:
            self._hint_not_implemented("Viewport overlays")

    def _toggle_selection_outlines(self, checked: bool) -> None:
        if self._controller is not None:
            self._controller.overlays.show_selection_outlines = checked
        else:
            self._hint_not_implemented("Viewport overlays")

    def _toggle_snap(self, checked: bool) -> None:
        if self._controller is not None:
            self._controller.snap.enabled = checked
        else:
            self._hint_not_implemented("Snapping")

    def _toggle_local_space(self, checked: bool) -> None:
        if self._controller is not None:
            self._controller.coordinates.space = (
                TransformSpace.LOCAL if checked else TransformSpace.WORLD
            )
        else:
            self._hint_not_implemented("Transform space")

    def _toggle_lock_layout(self, checked: bool) -> None:
        if checked:
            self._hint("Layout locked")
        else:
            self._hint("Layout unlocked")

    def _toggle_fullscreen(self, checked: bool) -> None:
        window = self._window
        if window is None:
            return
        if checked:
            window.showFullScreen()
        else:
            window.showNormal()

    # -- Scene handlers -----------------------------------------------------

    def _new_scene(self) -> None:
        if self._scenes is None:
            self._hint_not_implemented("Scene creation")
            return
        scene = self._scenes.create_scene()
        self._hint(f"Created scene: {scene.name}")
        self._refresh_scene_combo()

    def _delete_scene(self) -> None:
        if self._scenes is None:
            return
        scene_id = self._scenes.active_scene_id
        if scene_id is None:
            self._hint("No scene to delete")
            return
        self._scenes.delete_scene(scene_id)
        self._hint("Scene deleted")
        self._refresh_scene_combo()

    def _scene_combo_activated(self, index: int) -> None:
        if self._scenes is None or self._scene_combo is None:
            return
        scene_id = self._scene_combo.itemData(index)
        if scene_id:
            self._scenes.activate_scene(scene_id)
            active = self._scenes.active_scene
            self._hint(f"Scene: {active.name if active else scene_id}")

    def _refresh_scene_combo(self) -> None:
        combo = self._scene_combo
        if combo is None or self._scenes is None:
            return
        combo.blockSignals(True)
        combo.clear()
        current = self._scenes.active_scene_id
        for scene in self._scenes.get_all_scenes():
            combo.addItem(scene.name, scene.id)
        if current is not None:
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    # -- Tool handlers ------------------------------------------------------

    def _set_tool_mode(self, mode: TransformMode) -> None:
        if self._controller is not None:
            self._controller.transform_mode = mode
            self._hint(f"Tool: {mode.name.title()}")
        else:
            self._hint_not_implemented("Viewport tool switching")

    def _warp_triggered(self, checked: bool) -> None:
        self._hint_not_implemented("The Warp tool")
        self._sync_tool_state()

    def _sync_tool_state(self) -> None:
        mode = getattr(self._controller, "transform_mode", None)
        if not isinstance(mode, TransformMode):
            mode = TransformMode.NONE
        mapping = {m: action_id for action_id, _, _, m in _TOOL_MODES}
        target = mapping.get(mode, "tool.select")
        for action_id, _, _, _ in _TOOL_MODES:
            self._actions[action_id].setChecked(action_id == target)

    # -- Live handlers ------------------------------------------------------

    def _arm_triggered(self) -> None:
        vm = self._output_vm
        if vm is None:
            self._hint("Live output is not available")
            return
        # Arm toggles: ARMED -> disarm, IDLE/PREVIEW -> arm. Use can_disarm()
        # as the armed predicate — is_live only covers LIVE (not ARMED).
        if vm.can_disarm():
            vm.disarm()
            self._hint("Live output disarmed")
        elif vm.is_live:
            self._hint("Live output cannot be disarmed right now")
        elif vm.can_arm():
            vm.arm()
            self._hint("Live output armed")
        else:
            self._hint(f"Cannot arm live output from {vm.state.name} state")
        self._sync_arm_checked()

    def _send_live(self) -> None:
        if self._output_vm is not None and self._output_vm.can_send():
            self._output_vm.send_to_live()
        else:
            self._hint("Nothing to send — arm live output first")

    def _toggle_blackout(self) -> None:
        vm = self._output_vm
        if vm is None:
            self._hint("Live output is not available")
            return
        if vm.can_blackout():
            vm.blackout()
        elif vm.can_unblackout():
            vm.unblackout()
        else:
            self._hint("Cannot blackout in the current state")

    def _sync_arm_checked(self) -> None:
        if self._output_vm is not None:
            self._actions["tools.live.arm"].setChecked(self._output_vm.can_disarm())

    # -- Workspace handlers -------------------------------------------------

    def _activate_workspace(self, name: str) -> None:
        if self._workspace is not None:
            self._workspace.activate_layout(name)
            self._hint(f"Workspace: {name}")
            self._refresh_workspace_menus()
            self._refresh_panel_menus()

    def _reset_workspace(self) -> None:
        if self._workspace is None:
            self._hint_not_implemented("Workspace reset")
            return
        names = self._workspace.layout_names
        if not names:
            self._hint("No workspaces available")
            return
        default = "Projection" if "Projection" in names else names[0]
        self._workspace.activate_layout(default)
        self._hint(f"Reset workspace: {default}")
        self._refresh_workspace_menus()
        self._refresh_panel_menus()

    def _set_panel_visible(self, panel_id: str, visible: bool) -> None:
        if self._workspace is not None:
            self._workspace.set_panel_visible(panel_id, visible)
            self._refresh_panel_menus()

    def _refresh_workspace_menus(self) -> None:
        for menu in self._workspace_menus:
            self._refresh_workspaces_menu(menu)

    def _refresh_panel_menus(self) -> None:
        for menu in self._panels_menus:
            self._refresh_panels_menu(menu)

    def _refresh_workspaces_menu(self, menu: QMenu) -> None:
        menu.clear()
        if self._workspace is None:
            return
        group = QActionGroup(menu)
        active = self._workspace.active_layout_name
        for name in self._workspace.layout_names:
            action = QAction(name, menu)
            action.setCheckable(True)
            action.setChecked(name == active)
            action.triggered.connect(
                lambda _=False, n=name: self._activate_workspace(n)
            )
            group.addAction(action)
            menu.addAction(action)

    def _refresh_panels_menu(self, menu: QMenu) -> None:
        menu.clear()
        if self._workspace is None:
            return
        layout = self._workspace.active_layout
        if layout is None:
            return
        for panel_id, panel in layout.panels.items():
            action = QAction(panel_id.replace("_", " ").title(), menu)
            action.setCheckable(True)
            action.setChecked(panel.visible)
            action.triggered.connect(
                lambda checked=False, pid=panel_id: self._set_panel_visible(
                    pid, checked
                )
            )
            menu.addAction(action)

    # -- Help handlers ------------------------------------------------------

    def _show_shortcuts_reference(self) -> None:
        rows: list[tuple[str, str]] = []
        for action in self._actions.values():
            key = action.shortcut().toString()
            if key:
                rows.append((_clean_text(action), key))
        if not rows:
            self._hint("No shortcuts registered")
            return
        dialog = QDialog(self._window)
        dialog.setWindowTitle("Shortcuts Reference")
        table = QTableWidget(len(rows), 2, dialog)
        table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        for row, (text, key) in enumerate(sorted(rows, key=lambda r: r[0].lower())):
            table.setItem(row, 0, QTableWidgetItem(text))
            table.setItem(row, 1, QTableWidgetItem(key))
        table.horizontalHeader().setStretchLastSection(True)
        table.resizeColumnsToContents()
        layout = QVBoxLayout(dialog)
        layout.addWidget(table)
        dialog.resize(560, 420)
        dialog.exec()

    def _show_about(self) -> None:
        QMessageBox.about(
            self._window,
            "About ProjectionAI",
            "ProjectionAI — AI-powered projection mapping platform.\n\n"
            "Desktop shell build v0.1.0.",
        )

    # -- State sync ---------------------------------------------------------

    def _sync_history_state(self) -> None:
        if self._commands is None:
            return
        undo = self._actions["edit.undo"]
        redo = self._actions["edit.redo"]
        undo.setEnabled(self._commands.can_undo)
        redo.setEnabled(self._commands.can_redo)
        undo.setToolTip(self._commands.undo_text or "Undo")
        redo.setToolTip(self._commands.redo_text or "Redo")

    def _sync_view_toggles(self) -> None:
        controller = self._controller
        if controller is None:
            return
        self._actions["view.toggle_snap"].setChecked(controller.snap.enabled)
        self._actions["view.toggle_local_space"].setChecked(
            controller.coordinates.space == TransformSpace.LOCAL
        )
        self._actions["view.toggle_grid"].setChecked(controller.overlays.grid.enabled)
        self._actions["view.toggle_statistics"].setChecked(
            controller.overlays.show_statistics
        )
        self._actions["view.toggle_bounding_boxes"].setChecked(
            controller.overlays.show_bounding_boxes
        )
        self._actions["view.toggle_selection_outlines"].setChecked(
            controller.overlays.show_selection_outlines
        )

    def _on_output_changed(self, old: OutputState, new: OutputState) -> None:
        self._sync_output_state()

    def _sync_output_state(self) -> None:
        vm = self._output_vm
        if vm is None:
            return
        self._actions["tools.live.arm"].setEnabled(
            vm.can_arm() or vm.can_disarm() or vm.is_live
        )
        self._actions["tools.live.send"].setEnabled(vm.can_send())
        self._actions["tools.live.blackout"].setEnabled(
            vm.can_blackout() or vm.can_unblackout()
        )
        self._sync_arm_checked()

    def _on_transform_mode_changed(self, event: EditorEvent) -> None:
        if isinstance(event, TransformModeChanged):
            self._sync_tool_state()

    def _on_snap_toggled(self, event: EditorEvent) -> None:
        if isinstance(event, SnapToggled):
            self._actions["view.toggle_snap"].setChecked(event.enabled)

    def _on_space_changed(self, event: EditorEvent) -> None:
        if isinstance(event, SpaceChanged):
            self._actions["view.toggle_local_space"].setChecked(
                event.space == TransformSpace.LOCAL
            )

    # -- Hints --------------------------------------------------------------

    def _hint(self, text: str) -> None:
        if self._status_bar is not None:
            self._status_bar.set_hint(text)

    def _hint_not_implemented(self, feature: str) -> None:
        self._hint(f"{feature} — not implemented in this build")


def _clean_text(action: QAction) -> str:
    """Menu text without accelerators or key-suffix tabs."""
    return action.text().replace("&", "").replace("\t", " ")
