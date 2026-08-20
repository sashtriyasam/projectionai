"""Main application window — the desktop shell.

Owns the dock system, center viewport, status bar, and the Actions
module. Layout follows UX-ARCHITECTURE §2.1/§2.2:

- Left dock: collapsible section stack — Scenes, Assets, Devices
  (Projectors + Cameras), Calibration, Jobs, History.
- Center: :class:`MainViewport` — PREVIEW | LIVE companion panes.
- Right dock: section stack — Inspector, Project Properties, Output
  Settings.
- Bottom: Timeline (full width) with Timeline Properties and the AI
  Assistant stacked on the right.
- Status bar bound to :class:`StatusViewModel`.

Workspaces (§10): the seven presets (Projection, Calibration,
AI Creation, Animation, Live Show, Multi Projector, Minimal) are
seeded into the :class:`WorkspaceManager` on startup (only when a
layout with the same name does not already exist) and applied through
``WorkspaceLayoutChanged`` events. ``Ctrl+1..7`` switches workspaces.

Design decisions:
- Panels are created with their view models and registered in
  ``self._docks`` / ``self._panels`` under the panel's stable
  ``panel_id`` so workspace layouts can show/hide them.
- Dock visibility changes are written back to the workspace manager
  (source of truth); layout events are applied back to the docks with
  a guard flag to avoid feedback loops.
- The LIVE pane is treated as a pseudo-panel ("live") in layouts.
"""

from __future__ import annotations

import logging
from typing import Any, override

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QWidget,
)

from projectionai.core.events import Event, EventBus, WorkspaceLayoutChanged
from projectionai.domain.project import Project
from projectionai.domain.workspace import PanelState, WorkspaceLayout
from projectionai.editor.viewport_controller import ViewportController
from projectionai.infrastructure.renderer.camera import OrbitCamera
from projectionai.infrastructure.renderer.output_window import GLOutputWindow
from projectionai.ui.actions.actions import Actions
from projectionai.ui.panels import (
    AiAssistantPanel,
    AssetsPanel,
    CalibrationSessionsPanel,
    CameraPanel,
    ConsolePanel,
    DevicesPanel,
    DisplaysPanel,
    HistoryPanel,
    InspectorPanel,
    JobsPanel,
    OutputSettingsPanel,
    ProjectPropertiesPanel,
    ScenesPanel,
    TimelinePropertiesPanel,
    ViewModelPanel,
)
from projectionai.ui.viewmodels.ai import AiViewModel
from projectionai.ui.viewmodels.assets import AssetsViewModel
from projectionai.ui.viewmodels.calibration import CalibrationViewModel
from projectionai.ui.viewmodels.devices import DevicesViewModel
from projectionai.ui.viewmodels.displays import DisplaysViewModel
from projectionai.ui.viewmodels.history import HistoryViewModel
from projectionai.ui.viewmodels.jobs import JobsViewModel
from projectionai.ui.viewmodels.output import OutputViewModel
from projectionai.ui.viewmodels.output_settings import OutputSettingsViewModel
from projectionai.ui.viewmodels.project import ProjectViewModel
from projectionai.ui.viewmodels.scenes import ScenesViewModel
from projectionai.ui.viewmodels.status import StatusViewModel
from projectionai.ui.viewmodels.timeline_model import TimelineModel
from projectionai.ui.views import MainViewport, StatusBar, TimelineWidget
from projectionai.ui.widgets.panel_base import run_async

_logger = logging.getLogger(__name__)

_PANEL_TITLES: dict[str, str] = {
    "scenes": "Scenes",
    "assets": "Assets",
    "devices": "Devices",
    "displays": "Displays",
    "calibration": "Calibration",
    "camera": "Camera",
    "console": "Console",
    "jobs": "Jobs",
    "history": "History",
    "inspector": "Inspector",
    "project_properties": "Project Properties",
    "output_settings": "Output Settings",
    "timeline_properties": "Timeline Properties",
    "ai_assistant": "AI Assistant",
    "timeline": "Timeline",
}

# Workspace order = Ctrl+1..7 (UX §10).
_PRESET_NAMES: tuple[str, ...] = (
    "Projection",
    "Calibration",
    "AI Creation",
    "Animation",
    "Live Show",
    "Multi Projector",
    "Minimal",
)


def _preset_layout(
    name: str, *, locked: bool = False, **panels: bool
) -> WorkspaceLayout:
    """Build a preset layout from a panel-id -> visibility mapping."""
    return WorkspaceLayout(
        name=name,
        panels={
            pid: PanelState(panel_id=pid, visible=visible)
            for pid, visible in panels.items()
        },
        metadata={"locked": locked},
    )


# Appendix A — panel visibility matrix (default workspaces). "live" is the
# pseudo-panel for the LIVE pane of the center viewport.
_PRESETS: tuple[WorkspaceLayout, ...] = (
    _preset_layout(
        "Projection",
        scenes=True,
        assets=True,
        devices=True,
        camera=True,
        console=True,
        displays=True,
        calibration=True,
        jobs=True,
        history=True,
        inspector=True,
        project_properties=True,
        output_settings=True,
        timeline_properties=True,
        ai_assistant=True,
        timeline=True,
        live=True,
    ),
    _preset_layout(
        "Calibration",
        scenes=True,
        devices=True,
        camera=True,
        displays=True,
        calibration=True,
        history=True,
        inspector=True,
        live=True,
    ),
    _preset_layout(
        "AI Creation",
        scenes=True,
        assets=True,
        jobs=True,
        history=True,
        inspector=True,
        ai_assistant=True,
    ),
    _preset_layout(
        "Animation",
        scenes=True,
        assets=True,
        history=True,
        inspector=True,
        timeline_properties=True,
        timeline=True,
    ),
    _preset_layout(
        "Live Show",
        locked=True,
        devices=True,
        camera=True,
        console=True,
        displays=True,
        timeline=True,
        live=True,
    ),
    _preset_layout(
        "Multi Projector",
        scenes=True,
        devices=True,
        camera=True,
        displays=True,
        inspector=True,
        live=True,
    ),
    _preset_layout(
        "Minimal",
        live=True,
    ),
)


class _PanelDock(QDockWidget):
    """A dock widget that reports user-initiated close actions.

    ``visibilityChanged`` fires for many non-user causes (window
    minimize/restore, tab raises, dock moves), so it cannot drive
    workspace write-back. User closes (the title-bar close button)
    surface through ``closeEvent`` instead; re-opens through the dock's
    ``toggleViewAction``.
    """

    closed = Signal()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        self.closed.emit()
        super().closeEvent(event)


class MainWindow(QMainWindow):
    """Top-level application window (desktop shell)."""

    def __init__(self, app: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app: Any = app
        self._project: Project | None = None

        self._docks: dict[str, QDockWidget] = {}
        self._panels: dict[str, ViewModelPanel] = {}
        self._project_vm: ProjectViewModel | None = None
        self._output_vm: OutputViewModel | None = None
        self._calibration_vm: CalibrationViewModel | None = None
        self._displays_vm: DisplaysViewModel | None = None
        self._output_window: GLOutputWindow | None = None
        self._viewport: MainViewport | None = None
        self._status_bar: StatusBar | None = None
        self._actions: Actions | None = None
        self._applying_layout: bool = False
        self._last_applied_layout: str = ""

        self._setup_ui()
        self._connect_workspace_events()
        self._seed_workspaces()
        self._apply_layout()

    # -- Construction -------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("ProjectionAI")
        self.resize(1600, 1000)

        # -- View models (Qt-free, shared by panels) ------------------------
        output_vm = OutputViewModel()
        self._output_vm = output_vm
        output_settings_vm = OutputSettingsViewModel(
            self._app.project, output=output_vm
        )
        devices_vm = DevicesViewModel(self._app.cameras)
        displays_vm = DisplaysViewModel(self._app.hardware)
        self._displays_vm = displays_vm

        # -- Dedicated projector output window (borderless, fullscreen) ------
        # Created hidden; shown only when a display is selected as live.
        self._output_window = GLOutputWindow()
        self._output_window.output_escape_requested.connect(self._on_output_escape)
        displays_vm.attach_output_window(self._output_window)
        timeline_model = TimelineModel(fps=30.0, duration_frames=3600)
        scenes_vm = ScenesViewModel(self._app.scenes)
        self._project_vm = ProjectViewModel(self._app.project)

        # -- Center: PREVIEW | LIVE ----------------------------------------
        self._viewport = MainViewport()
        self._viewport.bind_viewmodels(
            scenes=scenes_vm,
            output=output_vm,
            output_settings=output_settings_vm,
            devices=devices_vm,
        )
        self.setCentralWidget(self._viewport)

        # -- Docks (keys = stable panel ids; see _build_docks) -------------
        calibration_vm = CalibrationViewModel(self._app.calibration)
        self._calibration_vm = calibration_vm
        calibration_vm.subscribe(self._sync_calibration_overlay)
        self._build_docks(
            scenes=scenes_vm,
            assets=AssetsViewModel(self._app.assets),
            devices=devices_vm,
            camera=devices_vm,
            console=None,
            displays=displays_vm,
            calibration=calibration_vm,
            jobs=JobsViewModel(self._app.jobs),
            history=HistoryViewModel(self._app.commands),
            inspector=scenes_vm,
            project_properties=self._project_vm,
            output_settings=output_settings_vm,
            timeline=timeline_model,
            timeline_properties=timeline_model,
            ai_assistant=AiViewModel(),
        )

        # -- Status bar -----------------------------------------------------
        self._status_bar = StatusBar()
        status_vm = StatusViewModel(
            self._app.project,
            self._app.scenes,
            self._app.jobs,
            output_vm,
            camera_count_provider=lambda: devices_vm.camera_count,
            hardware_provider=lambda: displays_vm.snapshot,
        )
        self._status_bar.bind_viewmodel(status_vm)
        self.setStatusBar(self._status_bar)

        # -- Editor controller (no OpenGL; drives Actions) -----------------
        controller = ViewportController(
            orbit_camera=OrbitCamera(),
            core_event_bus=self._app.event_bus,
            scene_manager=self._app.scenes,
            command_manager=self._app.commands,
        )

        # -- Actions: menu bar + toolbar (incl. scene combo) ---------------
        self._actions = Actions(
            self,
            workspace=self._app.workspace,
            commands=self._app.commands,
            projects=self._app.project,
            scenes=self._app.scenes,
            output_vm=output_vm,
            controller=controller,
            status_bar=self._status_bar,
            on_quit=self._quit,
        )
        self.setMenuBar(self._actions.build_menu_bar())
        self.addToolBar(self._actions.build_toolbar())

        # -- Poll timer: keep panels fresh (panels/__init__ contract) -------
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def _build_docks(self, **vms: Any) -> None:
        """Create all dock panels, bind view models, and arrange docks."""
        # Left section stack: Scenes, Assets, Devices, Camera, Displays,
        # Calibration, Jobs, History.
        left: list[tuple[type[ViewModelPanel], str]] = [
            (ScenesPanel, "scenes"),
            (AssetsPanel, "assets"),
            (DevicesPanel, "devices"),
            (CameraPanel, "camera"),
            (DisplaysPanel, "displays"),
            (CalibrationSessionsPanel, "calibration"),
            (JobsPanel, "jobs"),
            (HistoryPanel, "history"),
        ]
        # Right section stack: Inspector, Project Properties, Output Settings.
        right: list[tuple[type[ViewModelPanel], str]] = [
            (InspectorPanel, "inspector"),
            (ProjectPropertiesPanel, "project_properties"),
            (OutputSettingsPanel, "output_settings"),
        ]

        areas = (
            Qt.DockWidgetArea.LeftDockWidgetArea,
            Qt.DockWidgetArea.RightDockWidgetArea,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        )

        left_docks: list[QDockWidget] = []
        for cls, vm_key in left:
            dock = self._add_panel(cls(), vms[vm_key], areas[0])
            left_docks.append(dock)
        for dock in left_docks[1:]:
            self.tabifyDockWidget(left_docks[0], dock)
        left_docks[0].raise_()

        right_docks: list[QDockWidget] = []
        for cls, vm_key in right:
            dock = self._add_panel(cls(), vms[vm_key], areas[1])
            right_docks.append(dock)
        for dock in right_docks[1:]:
            self.tabifyDockWidget(right_docks[0], dock)
        right_docks[0].raise_()

        # Bottom: Timeline (full width) + Timeline Properties + AI Assistant
        # stacked to the right (UX §11); Console split beside the timeline.
        timeline_dock = self._add_panel(TimelineWidget(), vms["timeline"], areas[2])
        console_dock = self._add_panel(ConsolePanel(), vms.get("console"), areas[2])
        bottom_right: list[QDockWidget] = [
            self._add_panel(
                TimelinePropertiesPanel(), vms["timeline_properties"], areas[2]
            ),
            self._add_panel(AiAssistantPanel(), vms["ai_assistant"], areas[2]),
        ]
        self.tabifyDockWidget(bottom_right[0], bottom_right[1])
        self.splitDockWidget(timeline_dock, console_dock, Qt.Orientation.Horizontal)
        self.splitDockWidget(console_dock, bottom_right[0], Qt.Orientation.Horizontal)
        timeline_dock.resize(900, 200)

    def _add_panel(
        self, panel: ViewModelPanel, vm: Any, area: Qt.DockWidgetArea
    ) -> QDockWidget:
        """Wrap a panel in a dock under its stable panel_id."""
        panel_id = panel.panel_id
        dock = _PanelDock(_PANEL_TITLES.get(panel_id, panel_id.title()), self)
        dock.setObjectName(panel_id)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea
        )
        dock.setWidget(panel)
        self.addDockWidget(area, dock)
        self._docks[panel_id] = dock
        self._panels[panel_id] = panel

        # Inspector needs both the scene VM and the project VM.
        if isinstance(panel, InspectorPanel):
            panel.bind_viewmodel(vm)
            if self._project_vm is not None:
                panel.bind_project_viewmodel(self._project_vm)
        else:
            panel.bind_viewmodel(vm)

        # User close (title-bar X / view menu) writes the resulting panel
        # state back to the workspace; visibilityChanged is not used because
        # it also fires for window minimization, tab raises, and dock moves.
        dock.closed.connect(lambda pid=panel_id: self._on_dock_visibility(pid, False))
        dock.toggleViewAction().triggered.connect(
            lambda checked, pid=panel_id: self._on_dock_visibility(pid, checked)
        )
        return dock

    # -- Workspaces ---------------------------------------------------------

    def _seed_workspaces(self) -> None:
        """Register the seven preset layouts, only if not already present."""
        ws = self._app.workspace
        for preset in _PRESETS:
            if preset.name not in ws.layout_names:
                ws.add_layout(preset)

        last = ws.settings.last_active_layout
        if ws.settings.restore_last_layout and last in ws.layout_names:
            self._activate_workspace(last)
        else:
            self._activate_workspace("Projection")

        # Ctrl+1..7 switches workspaces (UX §10).
        for index, name in enumerate(_PRESET_NAMES, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(lambda n=name: self._activate_workspace(n))

    def _connect_workspace_events(self) -> None:
        bus: EventBus = self._app.event_bus
        bus.subscribe(WorkspaceLayoutChanged, self._on_workspace_changed)

    async def _on_workspace_changed(self, event: Event) -> None:
        """Apply the active layout to the docks (visibility + geometry)."""
        self._apply_layout()

    def _activate_workspace(self, name: str) -> None:
        ws = self._app.workspace
        if name in ws.layout_names:
            ws.activate_layout(name)

    def _apply_layout(self) -> None:
        ws = self._app.workspace
        layout = ws.active_layout
        if layout is None:
            return

        self._applying_layout = True
        try:
            # Panels absent from the layout are hidden (Appendix A matrix).
            for panel_id, dock in self._docks.items():
                state = layout.panels.get(panel_id)
                dock.setVisible(state is not None and state.visible)
            live_state = layout.panels.get("live")
            if self._viewport is not None:
                self._viewport.set_live_visible(
                    live_state is not None and live_state.visible
                )
        finally:
            self._applying_layout = False

        # Layout lock (R6): Live Show pins all docks.
        locked = bool(layout.metadata.get("locked", False))
        if locked:
            features = QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
        else:
            features = (
                QDockWidget.DockWidgetFeature.DockWidgetClosable
                | QDockWidget.DockWidgetFeature.DockWidgetMovable
                | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            )
        for dock in self._docks.values():
            dock.setFeatures(features)

        # Apply window geometry only when the layout actually changes.
        name = ws.active_layout_name
        if name != self._last_applied_layout:
            self._last_applied_layout = name
            if layout.window_maximized:
                self.showMaximized()
            else:
                self.move(layout.window_x, layout.window_y)
                self.resize(layout.window_width, layout.window_height)

    def _on_dock_visibility(self, panel_id: str, visible: bool) -> None:
        """Write user close/open actions back to the workspace manager.

        Only called from user actions (dock close button via
        ``_PanelDock.closeEvent`` and the view-menu toggle action); the
        ``_applying_layout`` guard additionally protects the layout-apply
        path from feedback loops.
        """
        if self._applying_layout:
            return
        ws = self._app.workspace
        if ws.active_layout is not None:
            ws.set_panel_visible(panel_id, visible)

    # -- Polling ------------------------------------------------------------

    def _poll(self) -> None:
        for panel in self._panels.values():
            panel.refresh()
        if self._viewport is not None:
            self._viewport.refresh()

    def _sync_calibration_overlay(self) -> None:
        """Push the latest calibration detection onto the preview canvas."""
        if self._viewport is None or self._calibration_vm is None:
            return
        corners, image_size = self._calibration_vm.calibration_overlay()
        self._viewport.preview.scene_widget.set_calibration_overlay(corners, image_size)

    # -- Project loading ----------------------------------------------------

    def load_project(self, project: Project) -> None:
        """Load a project into the UI."""
        self._project = project
        self.setWindowTitle(f"ProjectionAI — {project.name}")
        _logger.info("Loaded project: %s", project.name)

    # -- Lifecycle ----------------------------------------------------------

    def _quit(self) -> None:
        """Quit the application (Actions ``File > Quit`` handler)."""
        self.close()

    def _on_output_escape(self) -> None:
        """ESC on the dedicated output window ends the output session."""
        displays_vm = self._displays_vm
        if displays_vm is None:
            return
        run_async(displays_vm.exit_output())

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        self._poll_timer.stop()
        if self._calibration_vm is not None:
            self._calibration_vm.unsubscribe(self._sync_calibration_overlay)
        self._app.event_bus.unsubscribe(
            WorkspaceLayoutChanged, self._on_workspace_changed
        )
        if self._displays_vm is not None:
            self._displays_vm.shutdown()
        ws = self._app.workspace
        if ws is not None:
            ws.update_window_geometry(
                self.x(), self.y(), self.width(), self.height(), self.isMaximized()
            )
            if ws.settings.auto_save_layout:
                ws.save()
        for panel in self._panels.values():
            panel.shutdown()
        if self._viewport is not None:
            self._viewport.shutdown()
        if self._status_bar is not None:
            self._status_bar.shutdown()
        if self._actions is not None:
            self._actions.shutdown()
        if self._output_vm is not None:
            self._output_vm.close()
        if self._displays_vm is not None:
            self._displays_vm.attach_output_window(None)
        if self._output_window is not None:
            self._output_window.output_escape_requested.disconnect(
                self._on_output_escape
            )
            self._output_window.close()
        _logger.debug("Main window closing")
        super().closeEvent(event)
