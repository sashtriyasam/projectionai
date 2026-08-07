"""Regression tests for PreviewViewport grid bind-time synchronization.

``bind_viewmodels`` must push ``output_settings.grid_enabled`` onto the
canvas directly: ``QAbstractButton.setChecked`` only emits ``toggled``
on a state change, so a grid-disabled setting equal to the unchecked
button would never reach the canvas via the signal path.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.ui.viewmodels.output_settings import OutputSettingsViewModel
from projectionai.ui.viewmodels.scenes import ScenesViewModel
from projectionai.ui.views.main_viewport import PreviewViewport


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Return the process-wide QApplication (created once)."""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([])
    return app


class _FakeScene:
    name = "Scene A"


class _FakeScenes:
    def active_scene(self) -> _FakeScene:
        return _FakeScene()

    def root_id(self) -> str | None:
        return None

    def subscribe(self, handler: Any) -> None:
        """No-op."""

    def unsubscribe(self, handler: Any) -> None:
        """No-op."""


class _FakeOutputSettings:
    def __init__(self, grid_enabled: bool) -> None:
        self.grid_enabled = grid_enabled
        self.grid_sets: list[bool] = []

    def set_grid_enabled(self, enabled: bool) -> None:
        self.grid_enabled = enabled
        self.grid_sets.append(enabled)


def _bound_preview(
    qapp: QApplication, grid_enabled: bool
) -> tuple[PreviewViewport, _FakeOutputSettings]:
    settings = _FakeOutputSettings(grid_enabled)
    preview = PreviewViewport()
    preview.bind_viewmodels(
        cast(ScenesViewModel, _FakeScenes()),
        cast(OutputSettingsViewModel, settings),
    )
    return preview, settings


class TestGridBindSync:
    def test_disabled_setting_applied_to_canvas(self, qapp: QApplication) -> None:
        # The canvas defaults to grid ON; binding a grid-off setting must
        # turn it off even though setChecked(False) emits no toggled.
        preview, _ = _bound_preview(qapp, grid_enabled=False)
        assert preview.scene_widget.grid_enabled is False
        assert preview.grid_button.isChecked() is False

    def test_enabled_setting_checks_button_and_canvas(self, qapp: QApplication) -> None:
        preview, _ = _bound_preview(qapp, grid_enabled=True)
        assert preview.scene_widget.grid_enabled is True
        assert preview.grid_button.isChecked() is True

    def test_user_toggle_updates_canvas_and_settings(self, qapp: QApplication) -> None:
        preview, settings = _bound_preview(qapp, grid_enabled=False)
        preview.grid_button.setChecked(True)
        assert preview.scene_widget.grid_enabled is True
        assert settings.grid_enabled is True
        assert settings.grid_sets == [True]
