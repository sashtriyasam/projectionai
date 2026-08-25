"""Regression tests for AssetsPanel type-filter rebuild.

When the currently selected asset type disappears from the database
(``available_types``), the combo falls back to "All types" and the
view model's filter must be reset to match, so the asset list is not
silently filtered by a type that no longer exists. Selection must be
preserved while the type remains available, and the rebuild must stay
signal-blocked (no spurious ``currentIndexChanged``). Rendering happens
offscreen (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.domain.asset import Asset, AssetType
from projectionai.managers.asset_manager import AssetManager
from projectionai.ui.panels.assets_panel import AssetsPanel
from projectionai.ui.viewmodels.assets import AssetsViewModel

# qapp provided by pytest-qt (function-scoped) - custom module fixture removed to avoid leak


class _FakeManager:
    """In-memory stand-in for the AssetManager used by the view model."""

    def __init__(self, assets: list[Asset]) -> None:
        self._assets = list(assets)

    def set_assets(self, assets: list[Asset]) -> None:
        self._assets = list(assets)

    def get_all_assets(self) -> list[Asset]:
        return list(self._assets)

    def get_assets_by_type(self, asset_type: AssetType) -> list[Asset]:
        return [a for a in self._assets if a.type is asset_type]


def _asset(name: str, asset_type: AssetType) -> Asset:
    return Asset(name=name, type=asset_type, original_path=Path(name))


def _panel(
    qapp: QApplication, assets: list[Asset]
) -> tuple[AssetsPanel, AssetsViewModel, _FakeManager]:
    """A bound panel whose view model wraps the given assets."""
    manager = _FakeManager(assets)
    vm = AssetsViewModel(cast(AssetManager, manager))
    panel = AssetsPanel()
    panel.bind_viewmodel(vm)
    return panel, vm, manager


class TestRebuildTypeFilter:
    def test_resets_filter_when_current_type_is_gone(self, qapp: QApplication) -> None:
        panel, vm, manager = _panel(
            qapp,
            [_asset("img.png", AssetType.IMAGE), _asset("clip.mp4", AssetType.VIDEO)],
        )
        panel.type_filter.setCurrentIndex(panel.type_filter.findData(AssetType.IMAGE))
        assert vm.type_filter == panel.type_filter.currentData()
        # The IMAGE assets disappear from the database; only VIDEO remains.
        manager.set_assets([_asset("clip.mp4", AssetType.VIDEO)])
        panel.refresh()
        assert vm.type_filter is None
        assert panel.type_filter.currentIndex() == 0
        assert panel.type_filter.currentData() is None

    def test_preserves_selection_when_current_type_still_available(
        self, qapp: QApplication
    ) -> None:
        panel, vm, _ = _panel(
            qapp,
            [_asset("img.png", AssetType.IMAGE), _asset("clip.mp4", AssetType.VIDEO)],
        )
        panel.type_filter.setCurrentIndex(panel.type_filter.findData(AssetType.IMAGE))
        panel.refresh()
        assert panel.type_filter.currentIndex() == panel.type_filter.findData(
            AssetType.IMAGE
        )
        assert vm.type_filter == panel.type_filter.currentData()

    def test_rebuild_restores_selection_without_emitting(
        self, qapp: QApplication
    ) -> None:
        panel, vm, _ = _panel(
            qapp,
            [_asset("img.png", AssetType.IMAGE), _asset("clip.mp4", AssetType.VIDEO)],
        )
        panel.type_filter.setCurrentIndex(panel.type_filter.findData(AssetType.IMAGE))
        emissions: list[int] = []
        panel.type_filter.currentIndexChanged.connect(emissions.append)
        panel.refresh()
        assert panel.type_filter.currentIndex() == panel.type_filter.findData(
            AssetType.IMAGE
        )
        assert emissions == []
        assert vm.type_filter == panel.type_filter.currentData()
