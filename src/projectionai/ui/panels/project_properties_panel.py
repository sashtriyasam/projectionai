"""ProjectPropertiesPanel — project info + settings (right dock).

Renders the open project's metadata and editable settings through a
:class:`PropertySheet`. Edits commit back through
:class:`ProjectViewModel` so dirty tracking stays on the event bus.
"""

from __future__ import annotations

from typing import Any

from projectionai.ui.panels.property_panel import PropertyPanel
from projectionai.ui.viewmodels.properties import PropertySheet

_COLOR_SPACES: list[tuple[str, str]] = [
    ("sRGB", "sRGB"),
    ("Rec.709", "Rec.709"),
    ("DCI-P3", "DCI-P3"),
    ("Display P3", "Display P3"),
]

_AI_PROVIDERS: list[tuple[str, str]] = [
    ("Default", ""),
    ("Gemini", "gemini"),
    ("OpenAI", "openai"),
    ("Anthropic", "anthropic"),
    ("Replicate", "replicate"),
]


class ProjectPropertiesPanel(PropertyPanel):
    """Project Properties dock panel."""

    panel_id = "project_properties"

    def build_sheet(self) -> PropertySheet:
        """Build the project info + settings sheet."""
        sheet = PropertySheet("Project")

        info = sheet.add_section("Project")
        sheet.add_label(info, "proj_name", "Name")
        sheet.add_label(info, "proj_path", "Path")
        sheet.add_label(info, "proj_status", "Status")

        settings = sheet.add_section("Settings")
        sheet.add_int(
            settings,
            "resolution_width",
            "Width",
            value=1920,
            minimum=64,
            maximum=16384,
            step=8,
        )
        sheet.add_int(
            settings,
            "resolution_height",
            "Height",
            value=1080,
            minimum=64,
            maximum=16384,
            step=8,
        )
        sheet.add_float(
            settings,
            "framerate",
            "Frame rate",
            value=30.0,
            minimum=0.1,
            maximum=240.0,
            step=1.0,
        )
        sheet.add_choice(
            settings,
            "color_space",
            "Color space",
            value="sRGB",
            choices=_COLOR_SPACES,
        )
        sheet.add_choice(
            settings,
            "default_ai_provider",
            "AI provider",
            value="",
            choices=_AI_PROVIDERS,
        )

        workspace = sheet.add_section("Workspace")
        sheet.add_bool(workspace, "grid_enabled", "Grid", value=True)
        sheet.add_bool(workspace, "snap_to_grid", "Snap to grid", value=False)
        sheet.add_float(
            workspace,
            "grid_size",
            "Grid size",
            value=1.0,
            minimum=0.01,
            maximum=100.0,
            step=0.1,
        )
        return sheet

    def sync_sheet(self, sheet: PropertySheet) -> None:
        """Mirror project state into the sheet."""
        vm = self._viewmodel
        if vm is None:
            return
        sheet.set_value("proj_name", vm.name or "—")
        path = vm.project_path
        sheet.set_value("proj_path", str(path) if path is not None else "—")
        sheet.set_value(
            "proj_status",
            "Modified" if vm.is_dirty else ("Open" if vm.is_open else "Closed"),
        )
        settings = vm.settings()
        for key in (
            "resolution_width",
            "resolution_height",
            "framerate",
            "color_space",
            "default_ai_provider",
            "grid_enabled",
            "snap_to_grid",
            "grid_size",
        ):
            if key in settings:
                sheet.set_value(key, settings[key])

    def apply_row(self, row_id: str, value: Any) -> None:
        """Commit a settings edit to the view model."""
        vm = self._viewmodel
        if vm is None:
            return
        vm.update_setting(row_id, value)
