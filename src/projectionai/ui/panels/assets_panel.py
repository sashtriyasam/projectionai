"""AssetsPanel — asset browser (left dock).

Search + type filter over the project's assets, plus import (shell
stub) and removal. Rendering only — real import/persistence is
application logic, so the panel wires the view model's
``add_from_path`` to a file picker.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QVBoxLayout,
)

from projectionai.domain.asset import Asset, AssetType
from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.panels.common import make_action_button, make_section_header
from projectionai.ui.theme import TEXT_FAINT

_USER_ROLE = int(Qt.ItemDataRole.UserRole)

_ASSET_TYPE_COLORS = {
    AssetType.IMAGE: "#4A90E2",
    AssetType.VIDEO: "#3D7EFF",
    AssetType.MESH: "#B453F7",
    AssetType.MATERIAL: "#FF9E00",
    AssetType.TEXTURE: "#30D158",
    AssetType.CALIBRATION: "#FFC107",
    AssetType.AI_RESULT: "#FF3B30",
    AssetType.AUDIO: "#30D158",
    AssetType.PROJECTION: "#FF9E00",
    AssetType.SHADER: "#B453F7",
    AssetType.UNKNOWN: TEXT_FAINT,
}


class AssetsPanel(ViewModelPanel):
    """Assets dock panel: search, filter, import, remove."""

    panel_id = "assets"

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("assetsPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- Header + filter row ---------------------------------------------
        root.addWidget(make_section_header("ASSETS", self._import_asset))
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(4, 4, 4, 4)
        filter_row.setSpacing(4)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search assets…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._search_changed)
        filter_row.addWidget(self.search_box, stretch=1)
        self.type_filter = QComboBox()
        self.type_filter.currentIndexChanged.connect(self._type_changed)
        filter_row.addWidget(self.type_filter)
        root.addLayout(filter_row)

        # -- Asset list --------------------------------------------------------
        self.asset_list = QListWidget()
        self.asset_list.setObjectName("assetList")
        self.asset_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.asset_list.customContextMenuRequested.connect(self._asset_menu)
        root.addWidget(self.asset_list, stretch=1)

        # -- Action row ---------------------------------------------------------
        actions = QHBoxLayout()
        actions.setContentsMargins(4, 4, 4, 4)
        actions.setSpacing(4)
        actions.addWidget(make_action_button("Import", self._import_asset))
        actions.addWidget(make_action_button("Remove", self._remove_selected))
        actions.addStretch(1)
        root.addLayout(actions)

    # -- Refresh -------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the filter options and asset list from the view model."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._rebuild_type_filter()
            self._rebuild_list()
        finally:
            self._refreshing = False

    def clear(self) -> None:
        """Empty the asset list."""
        self.asset_list.clear()

    def _rebuild_type_filter(self) -> None:
        vm = self._viewmodel
        if vm is None:
            self.type_filter.clear()
            return
        current = self.type_filter.currentData()
        self.type_filter.blockSignals(True)
        try:
            self.type_filter.clear()
            self.type_filter.addItem("All types", None)
            for asset_type in vm.available_types:
                self.type_filter.addItem(asset_type.value.title(), asset_type)
            if current is not None:
                idx = self.type_filter.findData(current)
                if idx >= 0:
                    self.type_filter.setCurrentIndex(idx)
                else:
                    vm.set_type_filter(None)
        finally:
            self.type_filter.blockSignals(False)

    def _rebuild_list(self) -> None:
        vm = self._viewmodel
        self.asset_list.clear()
        if vm is None:
            return
        for asset in vm.assets():
            self.asset_list.addItem(self._make_item(asset))

    @classmethod
    def _make_item(cls, asset: Asset) -> QListWidgetItem:
        item = QListWidgetItem(f"{asset.name}  ·  {asset.type.value}")
        item.setData(_USER_ROLE, asset.id)
        item.setForeground(QColor(_ASSET_TYPE_COLORS.get(asset.type, TEXT_FAINT)))
        return item

    # -- Interactions ----------------------------------------------------------

    def _search_changed(self, text: str) -> None:
        if self._viewmodel is not None:
            self._viewmodel.set_search(text)

    def _type_changed(self, _index: int) -> None:
        if self._viewmodel is None:
            return
        asset_type = self.type_filter.currentData()
        self._viewmodel.set_type_filter(asset_type)

    def _import_asset(self) -> None:
        if self._viewmodel is None:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Asset")
        if file_path:
            self._viewmodel.add_from_path(Path(file_path))

    def _remove_selected(self) -> None:
        if self._viewmodel is None:
            return
        item = self.asset_list.currentItem()
        if item is None:
            return
        result = QMessageBox.question(
            self,
            "Remove Asset",
            f"Remove '{item.text()}'?",
        )
        if result == QMessageBox.StandardButton.Yes:
            self._viewmodel.remove(item.data(_USER_ROLE))

    def _asset_menu(self, pos: QPoint) -> None:
        item = self.asset_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        remove = menu.addAction("Remove")
        chosen = menu.exec(self.asset_list.mapToGlobal(pos))
        if chosen is remove:
            self.asset_list.setCurrentItem(item)
            self._remove_selected()
