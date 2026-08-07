"""Regression tests for TimelineCanvas gutter rendering.

The gutter column (track names, x < GUTTER_WIDTH) must stay fixed while
horizontal content scrolls: scrolled ruler/lane/clip painting may never
paint over it. Rendering happens offscreen (``QT_QPA_PLATFORM=offscreen``)
so the tests run headless on every OS, including CI.
"""

from __future__ import annotations

import os

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.ui.theme import TRACK_BG, WELL_BG, qcolor
from projectionai.ui.viewmodels.timeline_model import TimelineModel
from projectionai.ui.views.timeline_widget import (
    GUTTER_WIDTH,
    TimelineCanvas,
    TimelineWidget,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Return the process-wide QApplication (created once)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def canvas(qapp: QApplication) -> TimelineCanvas:
    """An 800x200 canvas bound to a two-track model with no clips."""
    model = TimelineModel(duration_frames=1200)
    model.add_track(name="Video")
    model.add_track(name="Audio")
    canvas = TimelineCanvas()
    canvas.set_model(model)
    canvas.resize(800, 200)
    return canvas


def test_gutter_stays_fixed_while_content_scrolls(canvas: TimelineCanvas) -> None:
    """Scrolled content never paints over the gutter column."""
    well = qcolor(WELL_BG)

    canvas.set_hscroll(0)
    image0 = canvas.grab().toImage()
    canvas.set_hscroll(500)
    image500 = canvas.grab().toImage()

    # Gutter top strip (ruler row) and lane rows stay background at both
    # scroll positions. Before the fix, the translated ruler/lane fills
    # painted PANEL_ALT_BG / TRACK_BG over the gutter.
    for image in (image0, image500):
        assert image.pixelColor(75, 10) == well
        assert image.pixelColor(75, 30) == well

    # Content right of the gutter actually scrolls: the alternating lane
    # fill visible at x=600 with no scroll is gone once scrolled past it.
    assert image0.pixelColor(600, 30) == qcolor(TRACK_BG)
    assert image500.pixelColor(600, 30) == well


def test_gutter_width_matches_scroll_clip(canvas: TimelineCanvas) -> None:
    """Scrolled content's clip boundary sits exactly at the gutter edge."""
    well = qcolor(WELL_BG)

    canvas.set_hscroll(500)
    image = canvas.grab().toImage()

    # The antialiased gutter border at x=GUTTER_WIDTH blends into the pixel
    # just left of the boundary, so that column is checked for absence of
    # the scrolled lane color instead of an exact background match. A
    # hard-coded or mismatched clip rect paints the lane fill across the
    # gutter (left pixel turns TRACK_BG) or starts it past the gutter
    # (boundary pixel stays WELL_BG) - both fail below.
    assert image.pixelColor(GUTTER_WIDTH - 1, 30) != qcolor(TRACK_BG)
    assert image.pixelColor(GUTTER_WIDTH - 5, 30) == well
    assert image.pixelColor(GUTTER_WIDTH, 30) == qcolor(TRACK_BG)


@pytest.fixture
def canvas_with_clip(qapp: QApplication) -> TimelineCanvas:
    """A canvas whose first track holds a clip at frames 0-24."""
    model = TimelineModel(duration_frames=1200)
    track = model.add_track(name="Video")
    model.add_clip(track.id, "Clip A", start_frame=0, duration_frames=24)
    canvas = TimelineCanvas()
    canvas.set_model(model)
    canvas.resize(800, 200)
    return canvas


def _left_press(canvas: TimelineCanvas, x: int, y: int) -> None:
    """Synthesize a left-button press at widget coordinates (x, y)."""
    local = QPointF(x, y)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        local,
        local,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(event)


def _left_move(canvas: TimelineCanvas, x: int, y: int) -> None:
    """Synthesize a left-button drag to widget coordinates (x, y)."""
    local = QPointF(x, y)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        local,
        local,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseMoveEvent(event)


class TestCanvasMouseInteraction:
    def test_press_on_clip_selects_without_scrubbing(
        self, canvas_with_clip: TimelineCanvas
    ) -> None:
        model = canvas_with_clip.model
        assert model is not None
        clip = model.tracks[0].clips[0]
        model.playhead_frame = 100

        _left_press(canvas_with_clip, 200, 30)  # inside clip (x 150-270, lane 0)

        assert canvas_with_clip._selected_clip == clip.id
        assert canvas_with_clip._scrubbing is False
        assert model.playhead_frame == 100  # clip press never moves the playhead

    def test_press_in_gutter_is_ignored(self, canvas: TimelineCanvas) -> None:
        model = canvas.model
        assert model is not None
        model.playhead_frame = 42

        _left_press(canvas, 10, 30)  # x < GUTTER_WIDTH (track-name gutter)

        assert canvas._selected_clip == ""
        assert canvas._scrubbing is False
        assert model.playhead_frame == 42  # gutter press never moves the playhead

    def test_press_in_content_scrubs_playhead(self, canvas: TimelineCanvas) -> None:
        model = canvas.model
        assert model is not None

        _left_press(canvas, 400, 30)  # content area, no clip under cursor

        assert canvas._scrubbing is True
        assert model.playhead_frame == canvas.frame_at_x(400)

    def test_drag_after_content_press_keeps_scrubbing(
        self, canvas: TimelineCanvas
    ) -> None:
        model = canvas.model
        assert model is not None
        _left_press(canvas, 400, 30)
        _left_move(canvas, 600, 30)
        assert model.playhead_frame == canvas.frame_at_x(600)


class TestBpmFrameRateSeparation:
    """The BPM spin controls model.bpm and never touches model.fps."""

    def test_refresh_populates_bpm_not_fps(self, qapp: QApplication) -> None:
        widget = TimelineWidget()
        model = TimelineModel(fps=25.0, bpm=138.0)
        widget.bind_viewmodel(model)
        assert widget.bpm_spin.value() == 138.0
        assert model.fps == 25.0  # frame rate untouched by refresh

    def test_spin_change_writes_bpm_not_fps(self, qapp: QApplication) -> None:
        widget = TimelineWidget()
        model = TimelineModel(fps=25.0)
        widget.bind_viewmodel(model)
        widget.bpm_spin.setValue(150.0)
        assert model.bpm == 150.0
        assert model.fps == 25.0  # tempo edit never rewrites the frame rate

    def test_fps_change_does_not_reset_bpm(self, qapp: QApplication) -> None:
        widget = TimelineWidget()
        model = TimelineModel(fps=30.0, bpm=120.0)
        widget.bind_viewmodel(model)
        model.fps = 24.0  # external frame-rate change (e.g. properties panel)
        assert widget.bpm_spin.value() == 120.0  # BPM control keeps its tempo


class TestRefreshSignalBlocking:
    """refresh() synchronizes controls without writing back into the model."""

    def test_refresh_bpm_sync_does_not_write_back(self, qapp: QApplication) -> None:
        widget = TimelineWidget()
        model = TimelineModel(bpm=120.0)
        widget.bind_viewmodel(model)
        notifications: list[int] = []
        model.subscribe(lambda: notifications.append(1))

        # User edit then external edit: the refresh() triggered by the second
        # notify must re-sync the spin WITHOUT emitting valueChanged (which
        # would push model.bpm again and add a spurious notify).
        widget.bpm_spin.setValue(150.0)  # user action -> model.bpm 150 (1)
        model.bpm = 200.0  # external edit (2) -> refresh syncs spin to 200

        assert widget.bpm_spin.value() == 200.0  # control re-synced
        assert model.bpm == 200.0
        # Without QSignalBlocker: refresh's setValue(200) re-emits
        # valueChanged -> _set_bpm -> notify (3). With it: stays at 2.
        assert len(notifications) == 2

    def test_refresh_loop_sync_does_not_write_back(self, qapp: QApplication) -> None:
        widget = TimelineWidget()
        model = TimelineModel()
        widget.bind_viewmodel(model)
        notifications: list[int] = []
        model.subscribe(lambda: notifications.append(1))

        widget.loop_button.setChecked(True)  # user action -> loop True (1)
        model.loop_enabled = False  # external property change (2) -> refresh syncs

        assert widget.loop_button.isChecked() is False  # control re-synced
        assert model.loop_enabled is False
        # Without QSignalBlocker: refresh's setChecked(False) -> toggled ->
        # _set_loop -> notify (3). With the blocker it stays at 2.
        assert len(notifications) == 2
