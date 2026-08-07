"""InspectorPanel — contextual right-dock property inspector.

Per UX-ARCHITECTURE §4.1, the Inspector re-skills itself from the
current scene selection:

- nothing selected → Scene properties (resolution, color space, grid)
- single node selected → node identity, transform, visibility, components
- multiple selected → multi-selection summary

It binds two view models: :class:`ScenesViewModel` (selection + node
data) and :class:`ProjectViewModel` (scene-level render settings). Both
are optional; the panel degrades to a hint when neither is bound.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLabel, QVBoxLayout

from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.viewmodels.properties import PropertySheet
from projectionai.ui.widgets.property_editor import PropertyEditorWidget

_COLOR_SPACES: list[tuple[str, str]] = [
    ("sRGB", "sRGB"),
    ("Rec.709", "Rec.709"),
    ("DCI-P3", "DCI-P3"),
    ("Display P3", "Display P3"),
]


class InspectorPanel(ViewModelPanel):
    """Contextual Inspector dock panel."""

    panel_id = "inspector"

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("inspectorPanel")
        self._project_vm: Any | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.breadcrumb = QLabel()
        self.breadcrumb.setObjectName("propLabel")
        self.breadcrumb.setWordWrap(True)
        root.addWidget(self.breadcrumb)

        self.editor = PropertyEditorWidget()
        self.editor.row_edited.connect(self._on_row_edited)
        root.addWidget(self.editor, stretch=1)

    # -- View models -----------------------------------------------------------

    def bind_viewmodel(self, viewmodel: Any) -> None:
        """Attach the scenes view model (drives the context)."""
        super().bind_viewmodel(viewmodel)
        self.refresh()

    def bind_project_viewmodel(self, project_vm: Any) -> None:
        """Attach the project view model (scene-level settings)."""
        if self._project_vm is not None and hasattr(self._project_vm, "unsubscribe"):
            self._project_vm.unsubscribe(self._on_project_changed)
        self._project_vm = project_vm
        if project_vm is not None and hasattr(project_vm, "subscribe"):
            project_vm.subscribe(self._on_project_changed)
        self.refresh()

    def unbind_viewmodel(self) -> None:
        """Detach both view models."""
        if self._project_vm is not None and hasattr(self._project_vm, "unsubscribe"):
            self._project_vm.unsubscribe(self._on_project_changed)
        self._project_vm = None
        super().unbind_viewmodel()

    def _on_project_changed(self) -> None:
        if self._refreshing:
            return
        self.refresh()

    # -- Refresh ---------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the contextual property sheet from the selection."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._rebuild()
        finally:
            self._refreshing = False

    def clear(self) -> None:
        """Drop the editor content."""
        self.editor.set_sheet(None)
        self.breadcrumb.setText("")

    def _rebuild(self) -> None:
        scenes = self._viewmodel
        sheet = PropertySheet("Inspector")

        if scenes is None:
            self._build_scene_sheet(sheet)
            self.breadcrumb.setText("No scene selected")
            self.editor.set_sheet(sheet)
            return

        active = scenes.active_scene()
        selection = scenes.selection()
        if not selection:
            self._build_scene_sheet(sheet)
            self.breadcrumb.setText(
                f"Scene: {active.name if active is not None else '—'}"
            )
        elif len(selection) == 1:
            node = scenes.node(next(iter(selection)))
            if node is None:
                self._build_scene_sheet(sheet)
                self.breadcrumb.setText("Scene: —")
            else:
                self._build_node_sheet(sheet, scenes, node)
                self.breadcrumb.setText(self._breadcrumb(scenes, node))
        else:
            self._build_multi_sheet(sheet, scenes, selection)
            self.breadcrumb.setText(f"{len(selection)} objects selected")

        self.editor.set_sheet(sheet)

    # -- Sheet builders ---------------------------------------------------------

    def _build_scene_sheet(self, sheet: PropertySheet) -> None:
        """Scene-level render properties (selection of nothing)."""
        settings = self._settings_snapshot()
        render = sheet.add_section("Scene")
        sheet.add_int(
            render,
            "resolution_width",
            "Width",
            value=settings.get("resolution_width", 1920),
            minimum=64,
            maximum=16384,
            step=8,
            help="Canvas width in pixels",
        )
        sheet.add_int(
            render,
            "resolution_height",
            "Height",
            value=settings.get("resolution_height", 1080),
            minimum=64,
            maximum=16384,
            step=8,
            help="Canvas height in pixels",
        )
        sheet.add_float(
            render,
            "framerate",
            "Frame rate",
            value=float(settings.get("framerate", 30.0)),
            minimum=0.1,
            maximum=240.0,
            step=1.0,
            help="Playback frame rate",
        )
        sheet.add_choice(
            render,
            "color_space",
            "Color space",
            value=str(settings.get("color_space", "sRGB")),
            choices=_COLOR_SPACES,
        )
        grid = sheet.add_section("Grid")
        sheet.add_bool(
            grid,
            "grid_enabled",
            "Enabled",
            value=bool(settings.get("grid_enabled", True)),
        )
        sheet.add_bool(
            grid,
            "snap_to_grid",
            "Snap",
            value=bool(settings.get("snap_to_grid", False)),
        )
        sheet.add_float(
            grid,
            "grid_size",
            "Cell size",
            value=float(settings.get("grid_size", 1.0)),
            minimum=0.01,
            maximum=100.0,
            step=0.1,
        )

    def _build_node_sheet(self, sheet: PropertySheet, scenes: Any, node: Any) -> None:
        """Node identity, transform, visibility, and components."""
        identity = sheet.add_section("Identity")
        sheet.add_label(identity, "node_name", "Name", value=node.name)
        sheet.add_label(identity, "node_id", "ID", value=node.id)
        sheet.add_label(
            identity, "node_visible", "Visible", value=str(bool(node.visible))
        )
        sheet.add_label(identity, "node_locked", "Locked", value=str(bool(node.locked)))

        transform = sheet.add_section("Transform")
        sheet.add_label(
            transform,
            "position",
            "Position",
            value=_fmt_vec3(node.transform.position),
        )
        sheet.add_label(
            transform,
            "scale",
            "Scale",
            value=_fmt_vec3(node.transform.scale),
        )

        if node.components:
            comps = sheet.add_section("Components")
            for comp_type, comp in node.components.items():
                sheet.add_label(
                    comps,
                    f"comp_{comp_type.value}",
                    comp_type.value.title(),
                    value=_component_summary(comp),
                )

        children = sheet.add_section("Children")
        sheet.add_label(
            children,
            "child_count",
            "Count",
            value=str(len(node.children)),
        )

    def _build_multi_sheet(
        self, sheet: PropertySheet, scenes: Any, selection: set[str]
    ) -> None:
        """Multi-selection summary with a node name list."""
        summary = sheet.add_section("Selection")
        sheet.add_label(summary, "count", "Count", value=str(len(selection)))
        names = []
        for node_id in sorted(selection):
            node = scenes.node(node_id)
            if node is not None:
                names.append(node.name)
        sheet.add_label(summary, "names", "Objects", value=", ".join(names) or "—")

    # -- Value plumbing ----------------------------------------------------------

    def _on_row_edited(self, row_id: str, value: Any) -> None:
        """Push scene-level edits back into the project view model."""
        if self._project_vm is None:
            return
        key = _SETTING_KEYS.get(row_id)
        if key is not None:
            self._project_vm.update_setting(key, value)

    def _settings_snapshot(self) -> dict[str, Any]:
        """Current project settings, or built-in defaults when closed."""
        if self._project_vm is None:
            return {}
        return dict(self._project_vm.settings())

    # -- Helpers ------------------------------------------------------------------

    @staticmethod
    def _breadcrumb(scenes: Any, node: Any) -> str:
        """Build ``Scene > Parent > Node`` breadcrumb text."""
        names: list[str] = []
        current = node
        guard = 0
        while current is not None and guard < 64:
            names.insert(0, current.name)
            parent_id = current.parent_id
            current = scenes.node(parent_id) if parent_id is not None else None
            guard += 1
        active = scenes.active_scene()
        if active is not None:
            names.insert(0, active.name)
        return " > ".join(names)


#: Maps inspector row ids to project-settings keys.
_SETTING_KEYS: dict[str, str] = {
    "resolution_width": "resolution_width",
    "resolution_height": "resolution_height",
    "framerate": "framerate",
    "color_space": "color_space",
    "grid_enabled": "grid_enabled",
    "snap_to_grid": "snap_to_grid",
    "grid_size": "grid_size",
}


def _fmt_vec3(values: tuple[float, float, float]) -> str:
    """Format a 3-vector compactly for a read-only label."""
    return ", ".join(f"{v:.2f}" for v in values)


def _component_summary(component: Any) -> str:
    """One-line summary of a scene-graph component."""
    fields = []
    for name in ("asset_id", "intensity", "fov_degrees", "light_type"):
        if hasattr(component, name):
            fields.append(f"{name}={getattr(component, name)}")
    return "; ".join(fields) if fields else str(component)
