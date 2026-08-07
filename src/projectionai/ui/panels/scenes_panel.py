"""ScenesPanel — Scenes list + Scene Graph tree (left dock).

Two sections per UX-ARCHITECTURE §3.2: a flat scene list with
create/activate/delete, and a hierarchical scene-graph tree for the
active scene with search, add-node, delete, and selection sync.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from projectionai.domain.scene import SceneNode
from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.panels.common import make_section_header
from projectionai.ui.theme import ACCENT, TEXT_FAINT

_USER_ROLE = int(Qt.ItemDataRole.UserRole)


class ScenesPanel(ViewModelPanel):
    """Scenes + Scene Graph dock panel."""

    panel_id = "scenes"

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("scenesPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- Scenes section ---------------------------------------------------
        root.addWidget(make_section_header("SCENES", self._add_scene))
        self.scene_list = QListWidget()
        self.scene_list.setObjectName("sceneList")
        self.scene_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.scene_list.customContextMenuRequested.connect(self._scene_menu)
        self.scene_list.itemClicked.connect(self._scene_clicked)
        root.addWidget(self.scene_list, stretch=2)

        # -- Scene graph section ----------------------------------------------
        root.addWidget(make_section_header("SCENE GRAPH", self._add_node))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter nodes…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_search)
        root.addWidget(self.search_box)
        self.graph_tree = QTreeWidget()
        self.graph_tree.setObjectName("sceneGraphTree")
        self.graph_tree.setHeaderHidden(True)
        self.graph_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.graph_tree.customContextMenuRequested.connect(self._graph_menu)
        self.graph_tree.itemClicked.connect(self._node_clicked)
        root.addWidget(self.graph_tree, stretch=3)

    # -- Refresh -------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild both sections from the bound view model."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._refresh_scenes()
            self._refresh_graph()
        finally:
            self._refreshing = False

    def clear(self) -> None:
        """Empty both sections."""
        self.scene_list.clear()
        self.graph_tree.clear()

    def _refresh_scenes(self) -> None:
        vm = self._viewmodel
        self.scene_list.clear()
        if vm is None:
            return
        active = vm.active_scene()
        for scene in vm.scenes():
            item = QListWidgetItem(scene.name)
            item.setData(_USER_ROLE, scene.id)
            if active is not None and scene.id == active.id:
                item.setForeground(QColor(ACCENT))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.scene_list.addItem(item)

    def _refresh_graph(self) -> None:
        vm = self._viewmodel
        self.graph_tree.clear()
        if vm is None:
            return
        root_id = vm.root_id()
        if root_id is None:
            return
        selected = vm.selection()
        visited: set[str] = set()
        for child in vm.children_of(root_id):
            self._add_tree_node(None, child, selected, visited)
        # Re-apply the query still shown in the search box so rebuilt
        # nodes match the displayed filter.
        self._apply_search(self.search_box.text())

    def _add_tree_node(
        self,
        parent: QTreeWidgetItem | None,
        node: SceneNode,
        selected: set[str],
        visited: set[str],
    ) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        if node.id in visited:
            return
        visited.add(node.id)
        item = QTreeWidgetItem(parent) if parent is not None else QTreeWidgetItem()
        item.setText(0, self._node_label(node))
        item.setData(0, _USER_ROLE, node.id)
        if node.id in selected:
            item.setForeground(0, QColor(ACCENT))
        elif not node.visible:
            item.setForeground(0, QColor(TEXT_FAINT))
        if parent is None:
            self.graph_tree.addTopLevelItem(item)
        for child_id in node.children:
            child = vm.node(child_id)
            if child is not None:
                self._add_tree_node(item, child, selected, visited)
        item.setExpanded(True)

    @staticmethod
    def _node_label(node: SceneNode) -> str:
        label = node.name
        if not node.visible:
            label += "  (hidden)"
        if node.locked:
            label += "  (locked)"
        return label

    def _apply_search(self, text: str) -> None:
        """Filter the tree by node name substring."""
        query = text.strip().lower()
        if not query:
            for item in self._iter_tree_items():
                item.setHidden(False)
            return
        for item in self._iter_tree_items():
            name = (item.text(0) or "").lower()
            item.setHidden(query not in name)
            if not item.isHidden():
                parent = item.parent()
                while parent is not None:
                    parent.setHidden(False)
                    parent = parent.parent()

    def _iter_tree_items(self) -> Iterator[QTreeWidgetItem]:
        stack = [
            self.graph_tree.topLevelItem(i)
            for i in range(self.graph_tree.topLevelItemCount())
        ]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            yield item
            for i in range(item.childCount()):
                stack.append(item.child(i))

    # -- Scenes interactions --------------------------------------------------

    def _scene_clicked(self, item: QListWidgetItem) -> None:
        if self._viewmodel is None:
            return
        scene_id = item.data(_USER_ROLE)
        self._viewmodel.activate_scene(scene_id)

    def _scene_menu(self, pos: QPoint) -> None:
        item = self.scene_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        activate = menu.addAction("Activate")
        delete = menu.addAction("Delete Scene")
        chosen = menu.exec(self.scene_list.mapToGlobal(pos))
        if chosen is delete:
            self._delete_scene(item)
        elif chosen is activate:
            self._scene_clicked(item)

    def _add_scene(self) -> None:
        if self._viewmodel is None:
            return
        name, ok = QInputDialog.getText(self, "New Scene", "Scene name:")
        if ok and name.strip():
            self._viewmodel.create_scene(name.strip())

    def _delete_scene(self, item: QListWidgetItem) -> None:
        if self._viewmodel is None:
            return
        scene_id = item.data(_USER_ROLE)
        result = QMessageBox.question(
            self,
            "Delete Scene",
            f"Delete scene '{item.text()}'?",
        )
        if result == QMessageBox.StandardButton.Yes:
            self._viewmodel.delete_scene(scene_id)

    # -- Scene graph interactions ---------------------------------------------

    def _node_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._viewmodel is None:
            return
        node_id = item.data(0, _USER_ROLE)
        self._viewmodel.select(node_id)

    def _graph_menu(self, pos: QPoint) -> None:
        item = self.graph_tree.itemAt(pos)
        menu = QMenu(self)
        add = menu.addAction("Add Child Node")
        delete = menu.addAction("Delete Node")
        chosen = menu.exec(self.graph_tree.mapToGlobal(pos))
        if chosen is add:
            self._add_node(item)
        elif chosen is delete and item is not None:
            self._delete_node(item)

    def _add_node(self, parent_item: QTreeWidgetItem | None = None) -> None:
        if self._viewmodel is None:
            return
        parent_id = None
        if parent_item is not None:
            parent_id = parent_item.data(0, _USER_ROLE)
        name, ok = QInputDialog.getText(self, "New Node", "Node name:", text="Node")
        if ok and name.strip():
            self._viewmodel.add_node(name.strip(), parent_id=parent_id)

    def _delete_node(self, item: QTreeWidgetItem) -> None:
        if self._viewmodel is None:
            return
        node_id = item.data(0, _USER_ROLE)
        self._viewmodel.remove_node(node_id)
