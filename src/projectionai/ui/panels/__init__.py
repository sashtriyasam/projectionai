"""Dock panels — the collapsible section stacks that fill the docks.

Each panel is a :class:`PanelWidget` subclass with a stable
``panel_id``; the :class:`MainWindow` wraps them in ``QDockWidget``
instances registered under the same id so workspace layouts can show,
hide, and persist them. Panels read from Qt-free view models and are
re-rendered on ``refresh()`` (driven by the main window's poll timer
and by explicit calls after actions).
"""

from projectionai.ui.panels.ai_assistant_panel import AiAssistantPanel
from projectionai.ui.panels.assets_panel import AssetsPanel
from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.panels.calibration_panel import CalibrationSessionsPanel
from projectionai.ui.panels.devices_panel import DevicesPanel
from projectionai.ui.panels.displays_panel import DisplaysPanel
from projectionai.ui.panels.history_panel import HistoryPanel
from projectionai.ui.panels.inspector_panel import InspectorPanel
from projectionai.ui.panels.jobs_panel import JobsPanel
from projectionai.ui.panels.output_settings_panel import OutputSettingsPanel
from projectionai.ui.panels.project_properties_panel import ProjectPropertiesPanel
from projectionai.ui.panels.property_panel import PropertyPanel
from projectionai.ui.panels.scenes_panel import ScenesPanel
from projectionai.ui.panels.timeline_properties_panel import TimelinePropertiesPanel

__all__ = [
    "AiAssistantPanel",
    "AssetsPanel",
    "CalibrationSessionsPanel",
    "DevicesPanel",
    "DisplaysPanel",
    "HistoryPanel",
    "InspectorPanel",
    "JobsPanel",
    "OutputSettingsPanel",
    "ProjectPropertiesPanel",
    "PropertyPanel",
    "ScenesPanel",
    "TimelinePropertiesPanel",
    "ViewModelPanel",
]
