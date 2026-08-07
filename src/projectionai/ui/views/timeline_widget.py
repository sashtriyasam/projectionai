"""TimelineWidget — the bottom-dock timeline: transport, ruler, tracks.

Renders the Qt-free :class:`TimelineModel` as the show's score
(UX-ARCHITECTURE.md §8): a transport bar (§8.2) with timecode readout,
loop toggle, BPM and master controls; a timecode ruler with snap/BPM
grid toggles and zoom; typed track lanes with color-coded clips and
keyframe diamonds; loop-range shading; and a draggable playhead.

There is no playback engine yet (shell-only constraint) — the transport
play/stop buttons toggle visual state, while scrubbing, frame stepping,
loop range, and clip selection all operate on the model. Follows the
panel contract (``bind_viewmodel`` / ``refresh``) like every other view.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import override

from PySide6.QtCore import QPoint, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QScrollBar,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.theme import (
    ACCENT,
    BORDER,
    BORDER_LIGHT,
    PANEL_ALT_BG,
    SELECTION_BG,
    TEXT_DIM,
    TEXT_FAINT,
    TRACK_BG,
    WARN_YELLOW,
    WELL_BG,
    qcolor,
)
from projectionai.ui.viewmodels.timeline_model import TimelineModel

GUTTER_WIDTH = 150  # px reserved for track names
TRACK_HEIGHT = 26  # px per lane


class TimelineCanvas(QWidget):
    """Custom-painted ruler + lanes + clips + keyframes + playhead."""

    #: Emitted when a clip is clicked: ``(clip_id, track_id)``.
    clip_selected = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timelineCanvas")
        self.setMinimumHeight(120)
        self._model: TimelineModel | None = None
        self._ppf: float = 5.0  # pixels per frame
        self._hscroll: int = 0
        self._selected_clip: str = ""
        self._scrubbing: bool = False

    # -- Model --------------------------------------------------------------

    @property
    def model(self) -> TimelineModel | None:
        """Return the bound timeline model."""
        return self._model

    def set_model(self, model: TimelineModel | None) -> None:
        """Attach a model and repaint."""
        self._model = model
        self._selected_clip = ""
        self.update()

    def bind_viewmodel(self, model: TimelineModel | None) -> None:
        """Panel-contract alias for :meth:`set_model`."""
        self.set_model(model)

    # -- Layout helpers -----------------------------------------------------

    def content_width(self) -> int:
        """Full pixel width of the timeline content (excluding gutter)."""
        if self._model is None:
            return 0
        return int(self._model.duration_frames * self._ppf)

    def x_at_frame(self, frame: int) -> float:
        """Content x for a frame (0 at the gutter edge)."""
        return frame * self._ppf

    def frame_at_x(self, x: int) -> int:
        """Frame under a widget x (accounts for gutter + scroll)."""
        if self._model is None:
            return 0
        content_x = x - GUTTER_WIDTH + self._hscroll
        frame = int(content_x / self._ppf) if self._ppf > 0 else 0
        return max(0, min(frame, self._model.duration_frames))

    def _visible_frame_range(self, model: TimelineModel) -> tuple[int, int]:
        """Inclusive ``(start, end)`` frame interval visible in the content
        area, derived from the scroll offset and widget width and clamped to
        the model's valid frame range."""
        total = model.duration_frames
        start = max(0, int(self._hscroll / self._ppf))
        end = min(total, int((self._hscroll + self.width() - GUTTER_WIDTH) / self._ppf))
        return (start, max(start, end))

    def set_ppf(self, pixels_per_frame: float) -> None:
        """Set zoom (pixels per frame) and repaint."""
        self._ppf = max(0.5, pixels_per_frame)
        self.update()

    def set_hscroll(self, value: int) -> None:
        """Set the horizontal scroll offset in content pixels."""
        self._hscroll = max(0, value)
        self.update()

    def select_clip(self, clip_id: str) -> None:
        """Set the selected clip id and repaint."""
        self._selected_clip = clip_id
        self.update()

    # -- Interaction --------------------------------------------------------

    def _clip_at(self, pos: QPoint) -> tuple[str, str] | None:
        """Return ``(clip_id, track_id)`` under *pos*, or ``None``."""
        model = self._model
        if model is None:
            return None
        content_x = pos.x() - GUTTER_WIDTH + self._hscroll
        ruler_height = 22
        for index, track in enumerate(model.tracks):
            if not track.visible:
                continue
            y = ruler_height + index * TRACK_HEIGHT
            if pos.y() < y or pos.y() >= y + TRACK_HEIGHT:
                continue
            for clip in track.clips:
                x0 = self.x_at_frame(clip.start_frame)
                x1 = self.x_at_frame(clip.end_frame)
                if x0 <= content_x < x1:
                    return (clip.id, track.id)
        return None

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            hit = self._clip_at(pos)
            if hit is not None:
                self._selected_clip = hit[0]
                self.clip_selected.emit(hit[0], hit[1])
                self.update()
            elif pos.x() >= GUTTER_WIDTH:
                # Content area (right of the gutter), no clip under cursor:
                # scrub the playhead. Presses in the track-name gutter are
                # ignored entirely.
                self._selected_clip = ""
                self.update()
                if self._model is not None:
                    self._model.playhead_frame = self.frame_at_x(pos.x())
                self._scrubbing = True
        super().mousePressEvent(event)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._scrubbing and self._model is not None:
            self._model.playhead_frame = self.frame_at_x(event.position().toPoint().x())
        super().mouseMoveEvent(event)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._scrubbing = False
        super().mouseReleaseEvent(event)

    # -- Painting -----------------------------------------------------------

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), qcolor(WELL_BG))
        model = self._model
        if model is None:
            self._paint_empty(painter)
            painter.end()
            return

        ruler_height = 22
        self._paint_gutter(painter, model, ruler_height)
        painter.save()
        # Content (ruler, lanes, clips, keyframes, playhead) is clipped to
        # the region right of the gutter so horizontal scroll can never
        # paint over the fixed track names.
        painter.setClipRect(
            QRectF(GUTTER_WIDTH, 0, self.width() - GUTTER_WIDTH, self.height())
        )
        painter.translate(-self._hscroll, 0)
        self._paint_loop_shading(painter, model, ruler_height)
        self._paint_ruler(painter, model)
        self._paint_lanes(painter, model, ruler_height)
        self._paint_clips(painter, model, ruler_height)
        self._paint_keyframes(painter, model, ruler_height)
        self._paint_playhead(painter, model)
        painter.restore()
        painter.end()

    def _paint_empty(self, painter: QPainter) -> None:
        painter.setPen(qcolor(TEXT_FAINT))
        painter.drawText(
            self.rect(), Qt.AlignmentFlag.AlignCenter, "No timeline loaded"
        )

    def _paint_loop_shading(
        self, painter: QPainter, model: TimelineModel, ruler_height: int
    ) -> None:
        if not model.loop_enabled:
            return
        x0 = self.x_at_frame(model.in_point)
        x1 = self.x_at_frame(model.out_point)
        rect = QRectF(
            GUTTER_WIDTH + x0,
            ruler_height,
            max(0.0, x1 - x0),
            self.height() - ruler_height,
        )
        painter.fillRect(rect, QColor(SELECTION_BG))

    def _paint_ruler(self, painter: QPainter, model: TimelineModel) -> None:
        painter.fillRect(
            QRectF(GUTTER_WIDTH, 0, self.width(), 22), qcolor(PANEL_ALT_BG)
        )
        step = 1
        if self._ppf * step < 8:
            step = int(8 / self._ppf) + 1
        if self._ppf * step < 8:
            step *= 2
        painter.setPen(QPen(qcolor(BORDER), 1))
        total = model.duration_frames
        start_frame, end_frame = self._visible_frame_range(model)
        for frame in range(
            (start_frame // step) * step, min(end_frame, total) + 1, step
        ):
            x = GUTTER_WIDTH + self.x_at_frame(frame)
            painter.drawLine(QPoint(int(x), 14), QPoint(int(x), 22))
        painter.setPen(qcolor(TEXT_DIM))
        label_step = max(1, step * 5)
        for frame in range(
            (start_frame // label_step) * label_step,
            min(end_frame, total) + 1,
            label_step,
        ):
            x = GUTTER_WIDTH + self.x_at_frame(frame)
            painter.drawText(
                QRectF(int(x) + 3, 2, 80, 12),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                model.timecode(frame),
            )

    def _paint_gutter(
        self, painter: QPainter, model: TimelineModel, ruler_height: int
    ) -> None:
        """Draw track names in the fixed gutter column (unscrolled)."""
        painter.setPen(qcolor(BORDER))
        painter.drawLine(QPoint(GUTTER_WIDTH, 0), QPoint(GUTTER_WIDTH, self.height()))
        for index, track in enumerate(model.tracks):
            y = ruler_height + index * TRACK_HEIGHT
            if track.visible:
                painter.setPen(qcolor(TEXT_DIM))
                name = track.name
            else:
                painter.setPen(qcolor(TEXT_FAINT))
                name = f"{track.name} (hidden)"
            painter.drawText(
                QRectF(4, y, GUTTER_WIDTH - 10, TRACK_HEIGHT),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name,
            )

    def _paint_lanes(
        self, painter: QPainter, model: TimelineModel, ruler_height: int
    ) -> None:
        painter.setPen(QPen(qcolor(BORDER), 1))
        for index, _track in enumerate(model.tracks):
            y = ruler_height + index * TRACK_HEIGHT
            if index % 2 == 0:
                painter.fillRect(
                    QRectF(GUTTER_WIDTH, y, self.width(), TRACK_HEIGHT),
                    qcolor(TRACK_BG),
                )
            painter.drawLine(
                QPoint(GUTTER_WIDTH, y + TRACK_HEIGHT),
                QPoint(self.width(), y + TRACK_HEIGHT),
            )

    def _paint_clips(
        self, painter: QPainter, model: TimelineModel, ruler_height: int
    ) -> None:
        start_frame, end_frame = self._visible_frame_range(model)
        for index, track in enumerate(model.tracks):
            if not track.visible:
                continue
            y = ruler_height + index * TRACK_HEIGHT + 2
            for clip in track.clips:
                if clip.end_frame <= start_frame or clip.start_frame > end_frame:
                    continue  # entirely outside the visible frame interval
                x0 = self.x_at_frame(clip.start_frame)
                x1 = self.x_at_frame(clip.end_frame)
                rect = QRectF(GUTTER_WIDTH + x0, y, max(2.0, x1 - x0), TRACK_HEIGHT - 4)
                is_selected = clip.id == self._selected_clip
                painter.setPen(
                    QPen(qcolor(ACCENT if is_selected else BORDER_LIGHT), 1.0)
                )
                painter.setBrush(qcolor(clip.color))
                painter.drawRoundedRect(rect, 3.0, 3.0)
                if rect.width() > 40:
                    painter.setPen(qcolor("#101418"))
                    painter.drawText(
                        rect.adjusted(4, 0, -4, 0),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        clip.name,
                    )

    def _paint_keyframes(
        self, painter: QPainter, model: TimelineModel, ruler_height: int
    ) -> None:
        start_frame, end_frame = self._visible_frame_range(model)
        for index, track in enumerate(model.tracks):
            if not track.visible:
                continue
            y_center = ruler_height + index * TRACK_HEIGHT + TRACK_HEIGHT / 2
            painter.setPen(QPen(qcolor(WARN_YELLOW), 0))
            painter.setBrush(qcolor(WARN_YELLOW))
            for key in track.keyframes:
                if key.frame < start_frame or key.frame > end_frame:
                    continue  # outside the visible frame interval
                x = GUTTER_WIDTH + self.x_at_frame(key.frame)
                painter.drawPolygon(
                    [
                        QPoint(int(x), int(y_center) - 3),
                        QPoint(int(x) + 3, int(y_center)),
                        QPoint(int(x), int(y_center) + 3),
                        QPoint(int(x) - 3, int(y_center)),
                    ]
                )

    def _paint_playhead(self, painter: QPainter, model: TimelineModel) -> None:
        x = GUTTER_WIDTH + self.x_at_frame(model.playhead_frame)
        painter.setPen(QPen(qcolor(ACCENT), 1.5))
        painter.drawLine(QPoint(int(x), 0), QPoint(int(x), self.height()))


class TimelineWidget(ViewModelPanel):
    """Bottom-dock timeline panel: transport + canvas bound to a model."""

    panel_id = "timeline"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._playing: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addLayout(self._build_transport())

        header = QHBoxLayout()
        header.setContentsMargins(6, 2, 6, 2)
        header.setSpacing(6)
        self.snap_button = self._toggle("⧉ Snap", "Toggle frame snapping")
        self.bpm_grid_button = self._toggle("BPM Grid", "Toggle BPM grid overlay")
        header.addWidget(self.snap_button)
        header.addWidget(self.bpm_grid_button)
        header.addStretch(1)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 200)
        self.zoom_slider.setValue(50)
        self.zoom_slider.setMaximumWidth(140)
        self.zoom_slider.valueChanged.connect(self._on_zoom)
        header.addWidget(self.zoom_slider)
        layout.addLayout(header)

        self.canvas = TimelineCanvas()
        layout.addWidget(self.canvas, stretch=1)

        self.scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self.scrollbar.valueChanged.connect(self.canvas.set_hscroll)
        layout.addWidget(self.scrollbar)

    # -- Transport (§8.2) ---------------------------------------------------

    def _build_transport(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(2)

        def _btn(text: str, tip: str, slot: Callable[..., object]) -> QToolButton:
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            return button

        row.addWidget(_btn("⏮", "Go to start", lambda: self._goto(0)))
        row.addWidget(_btn("◀◀", "Step back 10 frames", lambda: self._step(-10)))
        row.addWidget(_btn("◀", "Step back 1 frame", lambda: self._step(-1)))
        self.play_button = _btn(
            "▶", "Play / pause (shell state only)", self._toggle_play
        )
        self.play_button.setCheckable(True)
        row.addWidget(self.play_button)
        self.stop_button = _btn("■", "Stop", self._stop)
        row.addWidget(self.stop_button)
        row.addWidget(_btn("▶▶", "Step forward 1 frame", lambda: self._step(1)))
        row.addWidget(_btn("⏭", "Go to end", self._goto_end))

        self.timecode_label = QLabel("00:00:00:00")
        self.timecode_label.setObjectName("panelHeader")
        self.timecode_label.setStyleSheet(
            f"color: {ACCENT}; font-weight: 700; padding: 0 10px;"
        )
        row.addWidget(self.timecode_label)

        self.loop_button = QToolButton()
        self.loop_button.setText("Loop [In-Out ▾]")
        self.loop_button.setCheckable(True)
        self.loop_button.setToolTip("Toggle loop over the In/Out region")
        self.loop_button.toggled.connect(self._set_loop)
        row.addWidget(self.loop_button)

        self.in_out_label = QLabel("0-3600")
        self.in_out_label.setStyleSheet(f"color: {TEXT_FAINT};")
        row.addWidget(self.in_out_label)

        row.addStretch(1)

        self.bpm_spin = QDoubleSpinBox()
        self.bpm_spin.setRange(1.0, 300.0)
        self.bpm_spin.setValue(120.0)
        self.bpm_spin.setSuffix(" BPM")
        self.bpm_spin.setMaximumWidth(110)
        self.bpm_spin.valueChanged.connect(self._set_bpm)
        row.addWidget(self.bpm_spin)

        self.master_slider = QSlider(Qt.Orientation.Horizontal)
        self.master_slider.setRange(0, 100)
        self.master_slider.setValue(100)
        self.master_slider.setMaximumWidth(120)
        row.addWidget(QLabel("🎚"))
        row.addWidget(self.master_slider)
        self.master_label = QLabel("100%")
        self.master_label.setStyleSheet(f"color: {TEXT_DIM};")
        row.addWidget(self.master_label)
        self.master_slider.valueChanged.connect(
            lambda value: self.master_label.setText(f"{value}%")
        )
        return row

    # -- View model ---------------------------------------------------------

    def bind_viewmodel(self, viewmodel: TimelineModel | None) -> None:
        """Attach a timeline model and refresh."""
        self.unbind_viewmodel()
        self._viewmodel = viewmodel
        if viewmodel is not None:
            viewmodel.subscribe(self._on_viewmodel_changed)
        self.refresh()

    def refresh(self) -> None:
        """Re-read the model into the transport and canvas."""
        model = self._viewmodel
        if model is None:
            self.canvas.set_model(None)
            self.timecode_label.setText("00:00:00:00")
            return
        self.canvas.set_model(model)
        self.timecode_label.setText(model.timecode(model.playhead_frame))
        # Synchronize the toggles/spin without emitting: a refresh-driven
        # setChecked/setValue must not write back into the model (which would
        # re-notify and recursively re-run refresh).
        # Synchronize the toggles/spin without emitting: a refresh-driven
        # setChecked/setValue must not write back into the model (which would
        # re-notify and recursively re-run refresh).
        with QSignalBlocker(self.loop_button):
            self.loop_button.setChecked(model.loop_enabled)
        with QSignalBlocker(self.bpm_spin):
            self.bpm_spin.setValue(model.bpm)
        self.in_out_label.setText(f"{model.in_point}-{model.out_point}")
        self._sync_scrollbar()

    def clear(self) -> None:
        """Drop the timeline model reference."""
        self.canvas.set_model(None)

    # -- Handlers -----------------------------------------------------------

    def _set_loop(self, enabled: bool) -> None:
        """Push the Loop toggle into the model (no-op without a model)."""
        model = self._viewmodel
        if model is not None:
            model.loop_enabled = enabled

    def _set_bpm(self, bpm: float) -> None:
        """Push the BPM spin into the model (no-op without a model)."""
        model = self._viewmodel
        if model is not None:
            model.bpm = bpm

    def _goto(self, frame: int) -> None:
        model = self._viewmodel
        if model is not None:
            model.playhead_frame = frame

    def _goto_end(self) -> None:
        model = self._viewmodel
        if model is not None:
            model.playhead_frame = model.duration_frames

    def _step(self, delta: int) -> None:
        model = self._viewmodel
        if model is not None:
            model.step_frames(delta)

    def _toggle_play(self) -> None:
        self._playing = self.play_button.isChecked()
        # Shell only: no playback engine exists yet.

    def _stop(self) -> None:
        self._playing = False
        self.play_button.setChecked(False)

    def _on_zoom(self, value: int) -> None:
        self.canvas.set_ppf(value / 10.0)
        self._sync_scrollbar()

    def _sync_scrollbar(self) -> None:
        content = self.canvas.content_width()
        viewport = max(self.canvas.width() - GUTTER_WIDTH, 0)
        self.scrollbar.setMaximum(max(0, content - viewport))
        self.scrollbar.setValue(min(self.scrollbar.value(), self.scrollbar.maximum()))

    @staticmethod
    def _toggle(text: str, tip: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setCheckable(True)
        button.setToolTip(tip)
        return button

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_scrollbar()
