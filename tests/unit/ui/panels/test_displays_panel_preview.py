"""Regression tests for DisplaysPanel preview-target combo.

The preview combo must treat ``vm.preview_display_id`` as the sole
source of truth during refresh — it must not restore a stale prior
selection after selecting the view-model value. User activation must
call ``DisplaysViewModel.set_preview`` only while a session exists.
Rendering happens offscreen (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.hardware.models import DisplayInfo
from projectionai.ui.panels.displays_panel import DisplaysPanel


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Return the process-wide QApplication (created once)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _Session:
    """Marker for a live output session."""


class _FakeViewModel:
    """Duck-typed stand-in for DisplaysViewModel."""

    def __init__(
        self,
        displays: tuple[DisplayInfo, ...],
        preview_display_id: str | None,
        session: Any = None,
    ) -> None:
        self._displays = displays
        self._preview_display_id = preview_display_id
        self.session = session
        self.output_state = type("_State", (), {"value": "idle"})()
        self.preview_calls: list[str | None] = []

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

    @property
    def preview_display_id(self) -> str | None:
        return self._preview_display_id

    async def set_preview(self, display_id: str | None) -> None:
        self.preview_calls.append(display_id)

    def subscribe(self, handler: Any) -> None:
        """No-op: tests drive refresh directly."""


def _displays(*ids: str) -> tuple[DisplayInfo, ...]:
    return tuple(
        DisplayInfo(display_id=display_id, index=i, name=f"Display {display_id}")
        for i, display_id in enumerate(ids)
    )


class TestRefreshSourceOfTruth:
    def test_refresh_selects_vm_preview_not_stale_selection(
        self, qapp: QApplication
    ) -> None:
        vm = _FakeViewModel(_displays("d1", "d2"), preview_display_id="d1")
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        # User picks d2 manually, then the view model moves preview to d1.
        d2 = panel.preview_combo.findData("d2")
        assert d2 >= 0
        panel.preview_combo.setCurrentIndex(d2)

        vm._preview_display_id = "d1"
        panel.refresh()

        assert panel.preview_combo.currentData() == "d1"

    def test_refresh_falls_back_to_none_when_vm_has_no_preview(
        self, qapp: QApplication
    ) -> None:
        vm = _FakeViewModel(_displays("d1"), preview_display_id="d1")
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        # Session ends: view model now reports no preview target.
        vm._preview_display_id = None
        panel.refresh()

        assert panel.preview_combo.currentData() is None


class TestUserActivation:
    def test_activation_calls_set_preview_when_session_exists(
        self, qapp: QApplication
    ) -> None:
        vm = _FakeViewModel(
            _displays("d1", "d2"), preview_display_id="d1", session=_Session()
        )
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        panel.preview_combo.setCurrentIndex(panel.preview_combo.findData("d2"))
        panel._preview_activated(panel.preview_combo.currentIndex())

        assert vm.preview_calls == ["d2"]

    def test_activation_ignored_without_session(self, qapp: QApplication) -> None:
        vm = _FakeViewModel(_displays("d1"), preview_display_id="d1")
        panel = DisplaysPanel()
        panel.bind_viewmodel(vm)

        panel.preview_combo.setCurrentIndex(panel.preview_combo.findData("d1"))
        panel._preview_activated(panel.preview_combo.currentIndex())

        assert vm.preview_calls == []
