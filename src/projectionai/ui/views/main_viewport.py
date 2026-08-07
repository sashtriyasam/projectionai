"""MainViewport — the center companion windows: PREVIEW | LIVE.

UX-ARCHITECTURE.md §2.2: the center region is a pair of fixed
companion windows, never tabs. The left pane (PREVIEW) is the editing
viewport with a header of ``scene name · view mode · grid/overlay
toggles``; the right pane (LIVE) is the read-only program output with a
status header (live state · projector · resolution · latency · output
state) and can be hidden by workspaces.

The panes wrap :class:`SceneWidget` canvases bound to the shared
:class:`ScenesViewModel`; the LIVE pane mounts its canvas read-only.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from projectionai.ui.theme import (
    PANEL_BG,
    TEXT_FAINT,
)
from projectionai.ui.viewmodels.devices import DevicesViewModel
from projectionai.ui.viewmodels.output import OutputViewModel
from projectionai.ui.viewmodels.output_settings import OutputSettingsViewModel
from projectionai.ui.viewmodels.scenes import ScenesViewModel
from projectionai.ui.views.scene_widget import VIEW_MODES, SceneWidget


class PreviewViewport(QWidget):
    """PREVIEW pane — the editing viewport with its header controls."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewViewport")
        self._scenes: ScenesViewModel | None = None
        self._output_settings: OutputSettingsViewModel | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header: scene name · view mode · grid/overlay toggles
        header = QHBoxLayout()
        header.setContentsMargins(6, 3, 6, 3)
        header.setSpacing(6)

        self.scene_label = QLabel("No Scene")
        self.scene_label.setObjectName("panelHeader")
        header.addWidget(self.scene_label, stretch=1)

        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems(list(VIEW_MODES))
        self.view_mode_combo.setToolTip("View mode (2D / 3D / UV / Brightness Mask)")
        header.addWidget(self.view_mode_combo)

        self.grid_button = QToolButton()
        self.grid_button.setText("▦ Grid")
        self.grid_button.setCheckable(True)
        self.grid_button.setToolTip("Toggle grid overlay")
        header.addWidget(self.grid_button)

        self.overlay_button = QToolButton()
        self.overlay_button.setText("⧉ Overlays")
        self.overlay_button.setCheckable(True)
        self.overlay_button.setToolTip("Toggle viewport overlays")
        header.addWidget(self.overlay_button)

        layout.addLayout(header)

        self.scene_widget = SceneWidget(read_only=False)
        layout.addWidget(self.scene_widget, stretch=1)

        # Signals
        self.view_mode_combo.currentTextChanged.connect(self._on_view_mode)
        self.grid_button.toggled.connect(self._on_grid_toggled)
        self.scene_widget.grid_toggled.connect(self.grid_button.setChecked)
        self.overlay_button.toggled.connect(self.scene_widget.set_overlays_enabled)

    # -- View model ---------------------------------------------------------

    def bind_viewmodels(
        self,
        scenes: ScenesViewModel,
        output_settings: OutputSettingsViewModel,
    ) -> None:
        """Attach the view models driving this pane."""
        self._scenes = scenes
        self._output_settings = output_settings
        self.scene_widget.bind_scenes(scenes)
        self.grid_button.setChecked(output_settings.grid_enabled)
        # setChecked only emits toggled on a state change; apply the
        # configured value to the canvas directly so both stay in sync.
        self.scene_widget.set_grid_enabled(output_settings.grid_enabled)
        self.refresh()

    def refresh(self) -> None:
        """Re-read the bound view models."""
        if self._scenes is not None:
            scene = self._scenes.active_scene()
            self.scene_label.setText(scene.name if scene is not None else "No Scene")

    # -- Handlers -----------------------------------------------------------

    def _on_view_mode(self, mode: str) -> None:
        self.scene_widget.set_view_mode(mode)

    def _on_grid_toggled(self, checked: bool) -> None:
        """Mirror the grid toggle to the canvas and project settings."""
        self.scene_widget.set_grid_enabled(checked)
        if self._output_settings is not None:
            self._output_settings.set_grid_enabled(checked)


class LiveViewport(QWidget):
    """LIVE pane — the read-only program output window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("liveViewport")
        self._scenes: ScenesViewModel | None = None
        self._output: OutputViewModel | None = None
        self._output_settings: OutputSettingsViewModel | None = None
        self._devices: DevicesViewModel | None = None
        self._latency_ms: float | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header: ● STATE > Projector > res@fps > latency > Output
        header = QHBoxLayout()
        header.setContentsMargins(6, 3, 6, 3)
        header.setSpacing(8)

        self.live_badge = QLabel("● IDLE")
        self.live_badge.setObjectName("liveBadge")
        header.addWidget(self.live_badge)

        header.addWidget(self._separator())

        self.projector_label = QLabel("Projector: Proj 1")
        header.addWidget(self.projector_label)

        header.addWidget(self._separator())

        self.resolution_label = QLabel("1920x1080 @ 30")
        header.addWidget(self.resolution_label)

        header.addWidget(self._separator())

        self.latency_label = QLabel("— ms latency")
        header.addWidget(self.latency_label)

        header.addWidget(self._separator())

        self.output_label = QLabel("Output: IDLE")
        header.addWidget(self.output_label)

        header.addStretch(1)
        layout.addLayout(header)

        self.scene_widget = SceneWidget(read_only=True)
        layout.addWidget(self.scene_widget, stretch=1)

    # -- View model ---------------------------------------------------------

    def bind_viewmodels(
        self,
        scenes: ScenesViewModel,
        output: OutputViewModel,
        output_settings: OutputSettingsViewModel,
        devices: DevicesViewModel,
    ) -> None:
        """Attach the view models driving this pane."""
        self._scenes = scenes
        self._output = output
        self._output_settings = output_settings
        self._devices = devices
        self.scene_widget.bind_scenes(scenes)
        self.refresh()

    def refresh(self) -> None:
        """Re-read the bound view models and update the status header."""
        if self._output is not None:
            state = self._output.label.upper()
            self.live_badge.setText(f"● {state}")
            self.live_badge.setStyleSheet(f"color: {self._output.color};")
            self.output_label.setText(f"Output: {state}")
        if self._output_settings is not None:
            width, height = self._output_settings.resolution
            fps = int(self._output_settings.framerate)
            self.resolution_label.setText(f"{width}x{height} @ {fps}")
        if self._devices is not None:
            projectors = self._devices.projectors()
            name = projectors[0].name if projectors else "Proj 1"
            self.projector_label.setText(f"Projector: {name}")
        if self._latency_ms is not None:
            self.latency_label.setText(f"{self._latency_ms:.1f} ms latency")

    # -- Latency ------------------------------------------------------------

    def set_latency(self, latency_ms: float | None) -> None:
        """Set the measured output latency (``None`` = unknown)."""
        self._latency_ms = latency_ms
        if latency_ms is None:
            self.latency_label.setText("— ms latency")
        else:
            self.latency_label.setText(f"{latency_ms:.1f} ms latency")

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _separator() -> QLabel:
        label = QLabel(">")
        label.setStyleSheet(f"color: {TEXT_FAINT};")
        return label


class MainViewport(QWidget):
    """Center region: PREVIEW (editing) split with LIVE (read-only).

    The LIVE pane is hideable for workspaces that do not show program
    output (UX §2.2: "hidden in some workspaces").
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mainViewport")
        self.setStyleSheet(f"background-color: {PANEL_BG};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("viewportSplitter")
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, stretch=1)

        self.preview = PreviewViewport()
        self.live = LiveViewport()
        self.splitter.addWidget(self.preview)
        self.splitter.addWidget(self.live)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)

    # -- View models ---------------------------------------------------------

    def bind_viewmodels(
        self,
        scenes: ScenesViewModel,
        output: OutputViewModel,
        output_settings: OutputSettingsViewModel,
        devices: DevicesViewModel,
    ) -> None:
        """Bind all view models to the panes."""
        self.preview.bind_viewmodels(scenes, output_settings)
        self.live.bind_viewmodels(scenes, output, output_settings, devices)

    def refresh(self) -> None:
        """Re-read all bound view models."""
        self.preview.refresh()
        self.live.refresh()

    # -- Visibility ----------------------------------------------------------

    def set_live_visible(self, visible: bool) -> None:
        """Show or hide the LIVE pane (per workspace layout)."""
        self.live.setVisible(visible)

    @property
    def is_live_visible(self) -> bool:
        """True when the LIVE pane is currently shown."""
        return self.live.isVisible()

    # -- Convenience accessors ----------------------------------------------

    @property
    def preview_widget(self) -> SceneWidget:
        """The PREVIEW canvas."""
        return self.preview.scene_widget

    @property
    def live_widget(self) -> SceneWidget:
        """The LIVE canvas (read-only)."""
        return self.live.scene_widget

    def shutdown(self) -> None:
        """Release view model references held by the panes."""
        self.preview.scene_widget.bind_scenes(None)
        self.live.scene_widget.bind_scenes(None)
