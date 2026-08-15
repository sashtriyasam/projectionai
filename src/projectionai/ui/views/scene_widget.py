"""SceneWidget — the center viewport canvas (shell placeholder).

Renders a renderer-free preview of the active scene: a dark well
background, an optional grid, node markers for the scene graph's
top-level nodes, and selection outlines. Interaction follows
UX-ARCHITECTURE.md §7.1: LMB selects, click-on-empty deselects, RMB
opens a context menu, wheel zooms. A real GL renderer replaces the
paint routine in a later milestone; the shell keeps the UX contract
(and the offscreen smoke tests) working.

View modes (2D / 3D / UV / Brightness Mask) are cosmetic labels the
paint routine responds to; no projection/warping is performed — see the
shell-only project constraints.
"""

from __future__ import annotations

from typing import override

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QContextMenuEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QMenu, QWidget

from projectionai.ui.theme import (
    ACCENT,
    BORDER,
    BORDER_LIGHT,
    OK_GREEN,
    SELECTION_BG,
    TEXT,
    TEXT_DIM,
    TEXT_FAINT,
    WELL_BG,
    qcolor,
)
from projectionai.ui.viewmodels.scenes import ScenesViewModel

VIEW_MODES: tuple[str, ...] = ("2D", "3D", "UV", "Brightness Mask")


class SceneWidget(QWidget):
    """Render-free viewport canvas bound to a :class:`ScenesViewModel`."""

    grid_toggled = Signal(bool)

    def __init__(self, read_only: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sceneWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)
        self._read_only: bool = read_only
        self._scenes: ScenesViewModel | None = None
        self._view_mode: str = VIEW_MODES[0]
        self._grid_enabled: bool = True
        self._grid_size: float = 1.0
        self._overlays_enabled: bool = True
        self._zoom: float = 1.0
        self._scene_name: str = ""
        self._markers: dict[str, QRectF] = {}
        self._calibration_corners: list[tuple[int, int]] | None = None
        self._calibration_image_size: tuple[int, int] | None = None

    # -- View model ---------------------------------------------------------

    @property
    def viewmodel(self) -> ScenesViewModel | None:
        """Return the bound scenes view model, if any."""
        return self._scenes

    def bind_scenes(self, viewmodel: ScenesViewModel | None) -> None:
        """Attach (or detach) a scenes view model and re-render."""
        if self._scenes is not None:
            self._scenes.unsubscribe(self.refresh)
        self._scenes = viewmodel
        if viewmodel is not None:
            viewmodel.subscribe(self.refresh)
        self.refresh()

    # -- State --------------------------------------------------------------

    @property
    def view_mode(self) -> str:
        """Current view mode (2D / 3D / UV / Brightness Mask)."""
        return self._view_mode

    def set_view_mode(self, mode: str) -> None:
        """Set the view mode label and repaint."""
        if mode in VIEW_MODES:
            self._view_mode = mode
            self.update()

    @property
    def grid_enabled(self) -> bool:
        """True when the grid is drawn."""
        return self._grid_enabled

    def set_grid_enabled(self, enabled: bool) -> None:
        """Toggle the grid overlay."""
        self._grid_enabled = bool(enabled)
        self.grid_toggled.emit(self._grid_enabled)
        self.update()

    @property
    def grid_size(self) -> float:
        """Grid cell size in world units."""
        return self._grid_size

    def set_grid_size(self, size: float) -> None:
        """Set the grid cell size."""
        self._grid_size = max(float(size), 0.01)
        self.update()

    @property
    def overlays_enabled(self) -> bool:
        """True when corner labels / overlays are drawn."""
        return self._overlays_enabled

    def set_overlays_enabled(self, enabled: bool) -> None:
        """Toggle the corner overlay labels."""
        self._overlays_enabled = bool(enabled)
        self.update()

    @property
    def zoom(self) -> float:
        """Current zoom factor."""
        return self._zoom

    @property
    def scene_name(self) -> str:
        """Name of the active scene (``""`` when none)."""
        return self._scene_name

    # -- Calibration overlay ---------------------------------------------------

    def set_calibration_overlay(
        self,
        corners: list[tuple[int, int]] | None,
        image_size: tuple[int, int] | None = None,
    ) -> None:
        """Show detected board corners on the canvas (``None`` clears)."""
        self._calibration_corners = corners
        self._calibration_image_size = image_size
        self.update()

    # -- Interaction (UX §7.1) ----------------------------------------------

    def selected_ids(self) -> set[str]:
        """Ids of the selected nodes in the bound scene."""
        if self._scenes is None:
            return set()
        return set(self._scenes.selection())

    def marker_rect(self, node_id: str) -> QRectF | None:
        """Screen rect of a node marker, or ``None``."""
        return self._markers.get(node_id)

    def _hit_test(self, pos: QPoint) -> str | None:
        """Return the node id under *pos*, or ``None``."""
        for node_id, rect in self._markers.items():
            if rect.contains(QPointF(pos)):
                return node_id
        return None

    def _on_lmb(self, pos: QPoint) -> None:
        """Left-click handler: select / toggle / clear (no-op when read-only)."""
        if self._read_only or self._scenes is None:
            return
        node_id = self._hit_test(pos)
        if node_id is None:
            self._scenes.clear_selection()
        elif node_id in self._scenes.selection():
            self._scenes.deselect(node_id)
        else:
            self._scenes.select(node_id)

    # -- Refresh ------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the view model and recompute markers."""
        self._markers = {}
        self._scene_name = ""
        vm = self._scenes
        if vm is None:
            self.update()
            return
        scene = vm.active_scene()
        if scene is None:
            self.update()
            return
        self._scene_name = scene.name
        root_id = vm.root_id()
        children = vm.children_of(root_id) if root_id is not None else []
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        scale = min(width, height) / 8.0 * self._zoom
        cx = width / 2.0
        cy = height / 2.0
        marker_w = 44.0
        marker_h = 26.0
        for node in children:
            if not node.visible:
                continue
            x, _y, z = node.transform.position
            px = cx + x * scale
            py = cy - z * scale
            self._markers[node.id] = QRectF(
                px - marker_w / 2.0, py - marker_h / 2.0, marker_w, marker_h
            )
        self.update()

    # -- Painting -----------------------------------------------------------

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), qcolor(WELL_BG))
        self._paint_grid(painter)
        self._paint_markers(painter)
        self._paint_calibration(painter)
        self._paint_overlay(painter)
        painter.end()

    def _paint_grid(self, painter: QPainter) -> None:
        """Draw the world grid and center axes."""
        if not self._grid_enabled:
            return
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return
        cell = min(width, height) / 8.0 * self._zoom * self._grid_size
        if cell < 4.0:
            return
        painter.setPen(QPen(qcolor(BORDER), 1))
        x = width / 2.0 % cell
        while x < width:
            painter.drawLine(QPointF(x, 0), QPointF(x, height))
            x += cell
        y = height / 2.0 % cell
        while y < height:
            painter.drawLine(QPointF(0, y), QPointF(width, y))
            y += cell
        painter.setPen(QPen(qcolor(BORDER_LIGHT), 1))
        painter.drawLine(QPointF(width / 2.0, 0), QPointF(width / 2.0, height))
        painter.drawLine(QPointF(0, height / 2.0), QPointF(width, height / 2.0))

    def _paint_markers(self, painter: QPainter) -> None:
        """Draw scene node markers with selection outlines."""
        vm = self._scenes
        if vm is None:
            return
        selected = vm.selection()
        for node_id, rect in self._markers.items():
            node = vm.node(node_id)
            name = node.name if node is not None else node_id[:6]
            is_selected = node_id in selected
            painter.setPen(
                QPen(
                    qcolor(ACCENT if is_selected else BORDER_LIGHT),
                    1.5 if is_selected else 1.0,
                )
            )
            painter.setBrush(
                qcolor(SELECTION_BG) if is_selected else Qt.BrushStyle.NoBrush
            )
            painter.drawRoundedRect(rect, 4.0, 4.0)
            painter.setPen(qcolor(TEXT if is_selected else TEXT_DIM))
            painter.drawText(
                rect.adjusted(4.0, 0, -4.0, 0), Qt.AlignmentFlag.AlignCenter, name
            )

    def _paint_calibration(self, painter: QPainter) -> None:
        """Draw the detected board corners as individual green markers."""
        corners = self._calibration_corners
        if not corners:
            return
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        image_size = self._calibration_image_size
        if image_size is not None and image_size[0] > 0 and image_size[1] > 0:
            sx = width / image_size[0]
            sy = height / image_size[1]
        else:
            sx = 1.0
            sy = 1.0
        painter.setPen(QPen(qcolor(OK_GREEN), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for x, y in corners:
            point = QPointF(x * sx, y * sy)
            painter.drawEllipse(point, 2.0, 2.0)

    def _paint_overlay(self, painter: QPainter) -> None:
        """Draw the corner labels (scene · view mode, zoom)."""
        if not self._overlays_enabled:
            return
        width = self.width()
        height = self.height()
        tag = f"{self._scene_name} — {self._view_mode}"
        if self._read_only:
            tag = f"LIVE · {tag}"
        painter.setPen(qcolor(TEXT_DIM))
        painter.drawText(8, 16, tag)
        painter.setPen(qcolor(TEXT_FAINT))
        painter.drawText(
            QRectF(0, height - 22, width - 8, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
            f"Zoom {int(self._zoom * 100)}%",
        )

    # -- Event handlers -----------------------------------------------------

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        self.refresh()
        super().resizeEvent(event)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_lmb(event.position().toPoint())
        super().mousePressEvent(event)

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        factor = 1.2 if delta > 0 else 1.0 / 1.2
        self._zoom = max(0.1, min(20.0, self._zoom * factor))
        self.refresh()
        event.accept()

    @override
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        deselect = menu.addAction("Deselect")
        deselect.setEnabled(bool(self._scenes is not None and self._scenes.selection()))
        toggle_grid = menu.addAction("Toggle Grid")
        toggle_grid.setCheckable(True)
        toggle_grid.setChecked(self._grid_enabled)
        chosen = menu.exec(event.globalPos())
        if chosen is deselect and self._scenes is not None:
            self._scenes.clear_selection()
        elif chosen is toggle_grid:
            self.set_grid_enabled(not self._grid_enabled)
